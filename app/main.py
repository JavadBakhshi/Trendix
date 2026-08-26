from __future__ import annotations

import asyncio
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.analysis.predictor import analyze, predict
from app.analysis.indicators import add_indicators
from app.analysis.context import fear_greed, news_risk
from app.analysis.brief import build_brief
from app.analysis.alerts import scan_alerts
from app.config import DEFAULT_SYMBOL, TIMEFRAME_IDS, TIMEFRAMES
from app.data.market import market

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await market.ensure_source()
    except Exception:
        pass
    yield
    await market.close()


app = FastAPI(title="CryptoAnalyzer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _interval_or_400(interval: str) -> str:
    if interval not in TIMEFRAME_IDS:
        raise HTTPException(400, "بازه زمانی نامعتبر است")
    return interval


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/health")
async def health():
    source = None
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
        perf = await market.performance(symbol, ticker_data["price"])
        return jsonable({
            "source": market.source,
            "ticker": ticker_data,
            "interval": interval,
            "performance": perf,
            "indicators": result["indicators"],
            "prediction": result["prediction"],
            "candles": result["candles"],
            "volume": result["volume"],
            "overlays": result["overlays"],
        })
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
async def alerts(extra: str = Query("")):
    extras = [s.strip().upper() for s in extra.split(",") if s.strip()]
    key = ",".join(extras)
    now = time.time()
    if _ALERTS_CACHE["data"] is not None and _ALERTS_CACHE["key"] == key and now - _ALERTS_CACHE["at"] < 45:
        return jsonable(_ALERTS_CACHE["data"])
    try:
        data = await scan_alerts(extras)
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
