from __future__ import annotations

import asyncio
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.analysis.predictor import analyze, predict
from app.analysis.indicators import add_indicators
from app.analysis.context import fear_greed, news_risk
from app.analysis.brief import build_brief
from app.analysis.alerts import scan_alerts, warm_alerts_cache
from app.analysis.backtest import run_backtest
from app.config import DEFAULT_SYMBOL, TIMEFRAME_IDS, TIMEFRAMES
from app.data.market import market

BASE_DIR = Path(__file__).resolve().parent
_ALERTS_CACHE: dict = {"at": 0.0, "key": "", "data": None}
_ALERTS_REFRESHING = False


async def _alerts_bg_refresh(extras: list[str], min_odds: int, key: str) -> None:
    global _ALERTS_REFRESHING
    try:
        data = await scan_alerts(extras, min_odds=min_odds)
        _ALERTS_CACHE.update({"at": time.time(), "key": key, "data": data})
    except Exception:
        pass
    finally:
        _ALERTS_REFRESHING = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.trading.scheduler import ensure_started, stop_loop

    try:
        await market.ensure_source()
    except Exception:
        pass
    # Free hosts (e.g. Render 512MB) can OOM if we warm the full alert scan at boot.
    if os.environ.get("SKIP_ALERT_WARM", "0") != "1":
        asyncio.create_task(warm_alerts_cache())
    # In-app scalper loop (reads enabled flag from local MT5 settings).
    await ensure_started()
    yield
    await stop_loop()
    await market.close()


app = FastAPI(title="CryptoAnalyzer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _interval_or_400(interval: str) -> str:
    if interval not in TIMEFRAME_IDS:
        raise HTTPException(400, "بازه زمانی نامعتبر است")
    return interval


@app.get("/")
async def index():
    return FileResponse(
        BASE_DIR / "templates" / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
async def health():
    # Liveness only — never probe exchanges here (proxy bootstrap can hang).
    return {
        "ok": True,
        "source": market.source,
        "proxy": bool(
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("ALL_PROXY")
        ),
    }


@app.get("/api/ready")
async def ready():
    try:
        source = await market.ensure_source()
    except Exception as exc:
        return {"ok": False, "source": None, "error": str(exc)}
    return {"ok": True, "source": source}


@app.get("/api/timeframes")
async def timeframes():
    return TIMEFRAMES


@app.get("/api/coins")
async def coins():
    try:
        return await market.coins()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/ticker")
async def ticker(symbol: str = Query(DEFAULT_SYMBOL)):
    try:
        return await market.ticker(symbol)
    except Exception as exc:
        raise HTTPException(404, f"نماد پیدا نشد: {exc}") from exc


@app.get("/api/analysis")
async def analysis(
    symbol: str = Query(DEFAULT_SYMBOL),
    interval: str = Query("5m"),
):
    interval = _interval_or_400(interval)
    try:
        fetches = [
            market.ticker(symbol),
            market.klines_df(symbol, interval),
            fear_greed(market._client),
            news_risk(market._client, symbol),
        ]
        extra = []
        if interval not in {"1h", "3h", "1d", "1w"}:
            extra.append("1h")
            fetches.append(market.klines_df(symbol, "1h"))
        if interval not in {"1d", "1w"}:
            extra.append("1d")
            fetches.append(market.klines_df(symbol, "1d"))
        packed = await asyncio.gather(*fetches, return_exceptions=True)
        ticker_data = packed[0]
        df = packed[1]
        sentiment = packed[2] if not isinstance(packed[2], Exception) else {}
        news = packed[3] if not isinstance(packed[3], Exception) else {}
        if isinstance(ticker_data, Exception):
            raise ticker_data
        if isinstance(df, Exception) or getattr(df, "empty", True):
            raise HTTPException(404, "کندل برای این نماد دریافت نشد")

        mtf = {}
        for i, tf in enumerate(extra):
            hdf = packed[4 + i]
            if isinstance(hdf, Exception) or hdf is None or getattr(hdf, "empty", True):
                continue
            try:
                p = predict(hdf, tf, symbol)
                mtf[tf] = {"direction": p.get("direction"), "label": p.get("label"), "confidence": p.get("confidence")}
            except Exception:
                continue

        result = analyze(
            df,
            interval,
            symbol=symbol,
            volume_source=market.source,
            mtf=mtf,
            sentiment=sentiment if isinstance(sentiment, dict) else {},
            news=news if isinstance(news, dict) else {},
        )
        candles = result["candles"]
        live = ticker_data.get("price")
        if candles and live is not None:
            last = dict(candles[-1])
            price = float(live)
            last["close"] = price
            last["high"] = max(float(last["high"]), price)
            last["low"] = min(float(last["low"]), price)
            candles[-1] = last
        perf = await market.performance(symbol, ticker_data["price"])
        return jsonable({
            "source": market.source,
            "ticker": ticker_data,
            "interval": interval,
            "performance": perf,
            "indicators": result["indicators"],
            "prediction": result["prediction"],
            "candles": candles,
            "volume": result["volume"],
            "overlays": result["overlays"],
        })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/backtest")
async def backtest(
    symbol: str = Query(DEFAULT_SYMBOL),
    interval: str = Query("30m"),
):
    interval = _interval_or_400(interval)
    try:
        df = await market.klines_df(symbol, interval)
        data = run_backtest(df, interval, symbol)
        ticker_data = await market.ticker(symbol)
        return jsonable({"ticker": ticker_data, "source": market.source, **data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/predictions")
async def predictions(symbol: str = Query(DEFAULT_SYMBOL)):
    """Score every requested timeframe for the analysis page."""

    async def one(interval: str) -> dict:
        df = await market.klines_df(symbol, interval)
        if df.empty:
            return {"interval": interval, "error": "no data"}
        work = add_indicators(df)
        pred = predict(work, interval, symbol)
        last = work.iloc[-1]
        return {
            "interval": interval,
            "price": float(last["close"]),
            "prediction": pred,
            "rsi": None if pd_na(last.get("rsi")) else round(float(last["rsi"]), 1),
            "macd_hist": None if pd_na(last.get("macd_hist")) else round(float(last["macd_hist"]), 4),
        }

    try:
        ticker_data = await market.ticker(symbol)
        rows = await asyncio.gather(*[one(tf) for tf in TIMEFRAME_IDS])
        buys = sum(1 for r in rows if r.get("prediction", {}).get("direction") == "buy")
        sells = sum(1 for r in rows if r.get("prediction", {}).get("direction") == "sell")
        if buys > sells + 1:
            consensus, consensus_label = "buy", "خرید"
        elif sells > buys + 1:
            consensus, consensus_label = "sell", "فروش"
        else:
            consensus, consensus_label = "neutral", "خنثی"
        brief = build_brief(ticker_data, rows, consensus, consensus_label)
        return jsonable({
            "ticker": ticker_data,
            "source": market.source,
            "consensus": consensus,
            "consensus_label": consensus_label,
            "buy_count": buys,
            "sell_count": sells,
            "timeframes": rows,
            "brief": brief,
        })
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


_ALERTS_CACHE: dict = {"at": 0.0, "key": "", "data": None}


@app.get("/api/alerts")
async def alerts(
    extra: str = Query(""),
    min_odds: int = Query(50, ge=40, le=78),
):
    global _ALERTS_REFRESHING
    extras = [s.strip().upper() for s in extra.split(",") if s.strip()]
    key = f"{','.join(extras)}|{min_odds}"
    now = time.time()
    age = now - float(_ALERTS_CACHE.get("at") or 0)
    have = _ALERTS_CACHE["data"] is not None and _ALERTS_CACHE["key"] == key
    if have and age < 18:
        return jsonable(_ALERTS_CACHE["data"])
    if have and age < 90:
        if not _ALERTS_REFRESHING:
            _ALERTS_REFRESHING = True
            asyncio.create_task(_alerts_bg_refresh(extras, min_odds, key))
        return jsonable(_ALERTS_CACHE["data"])
    try:
        data = await scan_alerts(extras, min_odds=min_odds)
        _ALERTS_CACHE.update({"at": now, "key": key, "data": data})
        return jsonable(data)
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/markets")
async def markets():
    try:
        return await market.markets()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/news")
async def news():
    try:
        return await market.news()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/autotrade/status")
async def autotrade_status():
    from app.trading.executor import status_bundle
    from app.trading.scheduler import loop_status

    try:
        data = await status_bundle()
        data["scheduler"] = loop_status()
        return jsonable(data)
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/autotrade/config")
async def autotrade_config(payload: dict):
    """Save MT5 settings locally (password never returned in clear text)."""
    from app.trading.secrets import save
    from app.trading.scheduler import ensure_started

    allowed = {
        "enabled", "login", "password", "server", "terminal_path",
        "mode", "risk_percent", "max_positions", "min_odds", "cooldown_sec", "magic",
    }
    data = {k: payload[k] for k in allowed if k in payload}
    if "risk_percent" in data:
        data["risk_percent"] = float(max(0.1, min(3.0, float(data["risk_percent"]))))
    if "max_positions" in data:
        data["max_positions"] = int(max(1, min(8, int(data["max_positions"]))))
    if "min_odds" in data:
        data["min_odds"] = int(max(40, min(78, int(data["min_odds"]))))
    if "cooldown_sec" in data:
        data["cooldown_sec"] = int(max(45, min(3600, int(data["cooldown_sec"]))))
    if "mode" in data and data["mode"] not in {"scalping", "intraday", "swing"}:
        data["mode"] = "scalping"
    view = save(data)
    await ensure_started()
    return jsonable(view)


@app.post("/api/autotrade/test")
async def autotrade_test():
    from app.trading.executor import connect_from_secrets
    from app.trading import mt5_bridge

    result = connect_from_secrets()
    if result.get("ok"):
        mt5_bridge.shutdown()
    return jsonable(result)


@app.post("/api/autotrade/run")
async def autotrade_run():
    """One scan→trade cycle (manual trigger from UI)."""
    from app.trading.executor import run_once

    try:
        return jsonable(await run_once())
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/autotrade/start")
async def autotrade_start(payload: dict | None = None):
    """Enable scalping loop inside the web app (no separate file)."""
    from app.trading.secrets import load, save
    from app.trading.scheduler import ensure_started, loop_status

    payload = payload or {}
    cfg = load()
    updates = {
        "enabled": True,
        "mode": payload.get("mode") or cfg.get("mode") or "scalping",
    }
    for key in ("login", "password", "server", "terminal_path", "risk_percent", "max_positions", "min_odds", "cooldown_sec"):
        if key in payload and payload[key] not in (None, ""):
            updates[key] = payload[key]
    if updates.get("mode") not in {"scalping", "intraday", "swing"}:
        updates["mode"] = "scalping"
    view = save(updates)
    await ensure_started()
    return jsonable({"ok": True, "config": view, "scheduler": loop_status()})


@app.post("/api/autotrade/stop")
async def autotrade_stop():
    from app.trading.secrets import save
    from app.trading.scheduler import loop_status

    view = save({"enabled": False})
    return jsonable({"ok": True, "config": view, "scheduler": loop_status()})


def jsonable(value):
    if hasattr(value, "item") and not isinstance(value, (bytes, str, dict, list, tuple)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def pd_na(value) -> bool:
    try:
        v = float(value)
        return v != v
    except (TypeError, ValueError):
        return True
