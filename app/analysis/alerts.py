"""Fast multi-TF alert scan. Suggestions respect the user's min success filter."""

from __future__ import annotations

import asyncio
import time

from app.analysis.evidence import evaluate
from app.analysis.indicators import add_indicators
from app.analysis.predictor import predict
from app.config import HORIZON_FA
from app.data.coins import MACRO_ASSETS, meta_for, pack_macro
from app.data.market import market

DEFAULT_UNIVERSE = [
    "XAUUSD",
    "EURUSD",
    "DXY",
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
]

# Full predict only on signal TFs. Context TFs stay lean for speed.
PRIMARY_INTERVALS = ["1h", "15m", "5m"]
LEAN_INTERVALS = ["1d", "3h", "30m"]
ALL_INTERVALS = ["1d", "3h", "1h", "30m", "15m", "5m"]
CONTEXT_INTERVALS = ["1d", "3h", "1h"]
ALERT_TIERS = {"high_conviction", "strong", "moderate"}
_SEM = asyncio.Semaphore(8)
_SCAN_CACHE: dict = {"at": 0.0, "key": "", "rows": None, "refreshing": False}
_SCAN_TTL = 40.0
_STALE_TTL = 120.0
_PRED_CACHE: dict[str, tuple[float, dict | None]] = {}
_PRED_TTL = 55.0

TIER_FA = {
    "high_conviction": "قانع‌کننده",
    "strong": "قوی",
    "moderate": "قابل پیشنهاد",
    "avoid": "اجتناب",
    "no_trade": "بدون معامله",
}
DIR_FA = {"buy": "خرید", "sell": "فروش", "wait": "صبر", "neutral": "خنثی"}
TF_FA = {k: v.replace(" آینده", "") for k, v in HORIZON_FA.items()}
TF_ORDER = {tf: i for i, tf in enumerate(ALL_INTERVALS)}


def _pack(symbol: str) -> dict:
    spec = next((a for a in MACRO_ASSETS if a["symbol"] == symbol), None)
    if spec:
        return pack_macro(spec)
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    meta = meta_for(base)
    return {
        "symbol": symbol,
        "base": base,
        "name_en": meta["en"],
        "name_fa": meta["fa"],
        "icon": f"https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/{base.lower()}.png",
        "category": "crypto",
        "price_prefix": "$",
    }


def _mt_symbol(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return symbol[:-4] + "USD"
    return symbol


async def scan_alerts(extra: list[str] | None = None, min_odds: int = 50) -> dict:
    symbols = list(dict.fromkeys(DEFAULT_UNIVERSE + [s.upper() for s in (extra or []) if s]))
    min_odds = int(max(40, min(78, min_odds or 50)))
    cache_key = ",".join(symbols)
    now = time.time()
    age = now - float(_SCAN_CACHE.get("at") or 0)
    have = _SCAN_CACHE["rows"] is not None and _SCAN_CACHE["key"] == cache_key

    if have and age < _SCAN_TTL:
        scored = _SCAN_CACHE["rows"]
    elif have and age < _STALE_TTL:
        scored = _SCAN_CACHE["rows"]
        if not _SCAN_CACHE.get("refreshing"):
            _SCAN_CACHE["refreshing"] = True
            asyncio.create_task(_refresh_rows(symbols, cache_key))
    else:
        scored = await _compute_rows(symbols)
        _SCAN_CACHE.update({"at": now, "key": cache_key, "rows": scored, "refreshing": False})

    return _assemble(scored, min_odds, now)


async def warm_alerts_cache(extra: list[str] | None = None) -> None:
    """Precompute universe so the first UI hit is fast."""
    symbols = list(dict.fromkeys(DEFAULT_UNIVERSE + [s.upper() for s in (extra or []) if s]))
    cache_key = ",".join(symbols)
    try:
        scored = await _compute_rows(symbols)
        _SCAN_CACHE.update({"at": time.time(), "key": cache_key, "rows": scored, "refreshing": False})
    except Exception:
        _SCAN_CACHE["refreshing"] = False


async def _refresh_rows(symbols: list[str], cache_key: str) -> None:
    try:
        scored = await _compute_rows(symbols)
        _SCAN_CACHE.update({"at": time.time(), "key": cache_key, "rows": scored, "refreshing": False})
    except Exception:
        _SCAN_CACHE["refreshing"] = False


async def _compute_rows(symbols: list[str]) -> list[dict]:
    results = await asyncio.gather(*[_score_symbol(s) for s in symbols], return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


def _assemble(scored: list[dict], min_odds: int, now: float) -> dict:
    live = []
    watched = []
    for row in scored:
        item = dict(row)
        success = int(item.get("success_pct") or 0)
        action = item.get("action")
        has_edge = bool(item.get("has_edge"))
        conflict = bool(item.get("mtf_conflict"))
        news = item.get("news_risk") or "low"

        # Soft direction from edge + HTF lean when model is waiting for a precise entry.
        if action not in {"buy", "sell"} and has_edge and success >= min_odds and news != "high":
            htf = item.get("context_bias") if item.get("context_bias") in {"buy", "sell"} else None
            ltf = item.get("lean") if item.get("lean") in {"buy", "sell"} else None
            soft = htf or ltf
            if soft in {"buy", "sell"}:
                item["action"] = soft
                item["status"] = "alert"
                item["quality"] = "moderate"
                item["quality_fa"] = "قابل پیشنهاد"
                item["strength"] = "قابل پیشنهاد"
                item["command"] = f"{'🟢 BUY' if soft == 'buy' else '🔴 SELL'}  {item.get('mt_symbol')}"
                clash = ""
                if htf and ltf and htf != ltf:
                    clash = f" · توجه: کوتاه‌مدت به سمت {DIR_FA.get(ltf)} متمایل است"
                    item["mtf_conflict"] = False
                    item["quality_fa"] = "قابل پیشنهاد (با احتیاط)"
                item["detail"] = (
                    f"لبه تأییدشده روی {item.get('interval_fa')} · جهت {DIR_FA.get(soft)} "
                    f"از بافت بالاتر (ستاپ کامل هنوز نیست) · احتمال {success}٪{clash}"
                )
                action = soft
                live.append(item)
                continue
            item["status"] = "edge_wait"
            watched.append(item)
            continue

        if action in {"buy", "sell"} and news != "high" and success >= min_odds and not conflict:
            item["status"] = "alert"
            if item.get("quality") not in ALERT_TIERS:
                item["quality"] = "strong" if has_edge and (success >= 58 or item.get("mtf_aligned")) else "moderate"
                item["quality_fa"] = TIER_FA.get(item["quality"], item["quality"])
                item["strength"] = item["quality_fa"]
            if not has_edge:
                item["detail"] = f"{item.get('detail')} · لبه آماری ضعیف‌تر از فیلتر کاربر".strip(" ·")
            live.append(item)
        elif action in {"buy", "sell"} and has_edge and conflict and success >= min_odds:
            item["status"] = "edge_wait"
            item["quality"] = "moderate"
            item["quality_fa"] = "تضاد بازه‌ها"
            item["command"] = f"⏳ تضاد بازه‌ها  {item.get('mt_symbol')}"
            watched.append(item)
        elif item.get("status") == "edge_wait" or (has_edge and action == "wait"):
            item["status"] = "edge_wait"
            watched.append(item)
        elif action in {"buy", "sell"} and success >= min_odds and not has_edge:
            item["status"] = "setup_no_edge"
            watched.append(item)

    buys = sorted([r for r in live if r["action"] == "buy"], key=lambda x: (x.get("rank") or 0, x.get("success_pct") or 0), reverse=True)
    sells = sorted([r for r in live if r["action"] == "sell"], key=lambda x: (x.get("rank") or 0, x.get("success_pct") or 0), reverse=True)
    waits = sorted(watched, key=lambda x: (x.get("rank") or 0, x.get("success_pct") or 0), reverse=True)
    research = sorted(
        scored,
        key=lambda x: (
            1 if x.get("has_edge") else 0,
            1 if x.get("action") in {"buy", "sell"} else 0,
            int(x.get("success_pct") or 0),
            float(x.get("expectancy") or -9),
        ),
        reverse=True,
    )
    no_trade = sorted(
        [r for r in scored if not r.get("has_edge") and r.get("action") == "wait"],
        key=lambda x: float(x.get("expectancy") or -9),
        reverse=True,
    )
    best_buy = buys[0] if buys else None
    best_sell = sells[0] if sells else None
    return {
        "best_buy": best_buy,
        "best_sell": best_sell,
        "buys": buys[:6],
        "sells": sells[:6],
        "watched": waits[:8],
        "research": research[:8],
        "no_trade": no_trade[:6],
        "min_odds": min_odds,
        "updated_at": int(now),
        "headline": _headline(best_buy, best_sell, scored, waits, min_odds),
        "disclaimer": (
            f"فیلتر موفقیت ≥ {min_odds}٪ روی پیشنهاد فعال اعمال می‌شود. "
            "اسکن خودکار بدون رفرش صفحه به‌روز می‌شود. هشدار صوتی فقط بعد از زدن دکمهٔ فعال‌سازی و برای پیشنهاد فعال کار می‌کند."
        ),
    }


async def _score_symbol(symbol: str) -> dict | None:
    async with _SEM:
        try:
            ticker = await market.ticker(symbol)
        except Exception:
            return None
        primary = await asyncio.gather(
            *[_load_full(symbol, iv) for iv in PRIMARY_INTERVALS],
            return_exceptions=True,
        )
        lean = await asyncio.gather(
            *[_load_lean(symbol, iv) for iv in LEAN_INTERVALS],
            return_exceptions=True,
        )
        candidates = []
        for interval, packed in zip(PRIMARY_INTERVALS, primary):
            if isinstance(packed, Exception) or not packed:
                continue
            candidates.append(_candidate_from_pred(symbol, ticker, interval, packed, full=True))
        for interval, packed in zip(LEAN_INTERVALS, lean):
            if isinstance(packed, Exception) or not packed:
                continue
            candidates.append(_candidate_from_lean(symbol, ticker, interval, packed))
        if not candidates:
            return None
        stack = _build_tf_stack(candidates)
        context = _context_bias(stack)
        for row in candidates:
            _apply_mtf_context(row, stack, context)
        best = _pick_best(candidates)
        best["tf_stack"] = stack
        best["context_bias"] = context.get("bias")
        best["context_bias_fa"] = context.get("bias_fa")
        best["setup_map"] = _setup_map_text(stack)
        if best.get("mtf_note"):
            best["detail"] = f"{best['detail']} · {best['mtf_note']}".strip(" ·")
        return best


async def _load_full(symbol: str, interval: str) -> dict | None:
    key = f"full:{symbol}:{interval}"
    hit = _PRED_CACHE.get(key)
    if hit and time.time() - hit[0] < _PRED_TTL:
        return hit[1]
    try:
        df = await market.klines_df(symbol, interval)
    except Exception:
        _PRED_CACHE[key] = (time.time(), None)
        return None
    if df is None or getattr(df, "empty", True):
        _PRED_CACHE[key] = (time.time(), None)
        return None
    try:
        out = predict(add_indicators(df), interval, symbol)
    except Exception:
        out = None
    _PRED_CACHE[key] = (time.time(), out)
    return out


async def _load_lean(symbol: str, interval: str) -> dict | None:
    """Regime/lean only — no full ensemble. Keeps the TF map cheap."""
    key = f"lean:{symbol}:{interval}"
    hit = _PRED_CACHE.get(key)
    if hit and time.time() - hit[0] < _PRED_TTL:
        return hit[1]
    try:
        df = await market.klines_df(symbol, interval)
    except Exception:
        _PRED_CACHE[key] = (time.time(), None)
        return None
    if df is None or getattr(df, "empty", True):
        _PRED_CACHE[key] = (time.time(), None)
        return None
    try:
        work = add_indicators(df)
        ev = evaluate(work, interval, symbol)
        core = ev.get("core") or {}
        out = {
            "interval": interval,
            "core": core,
            "evidence": ev,
            "regime": core.get("regime"),
            "regime_fa": core.get("regime_fa"),
            "structure": {
                "trend": {
                    "up": "صعودی",
                    "down": "نزولی",
                    "sideways": "رنج",
                }.get(
                    "up" if "bull" in (core.get("regime") or "") else "down" if "bear" in (core.get("regime") or "") else "sideways",
                    "رنج",
                )
            },
        }
    except Exception:
        out = None
    _PRED_CACHE[key] = (time.time(), out)
    return out


def _candidate_from_pred(symbol: str, ticker: dict, interval: str, p1: dict, full: bool = True) -> dict:
    meta = _pack(symbol)
    name = ticker.get("name_fa") or meta["name_fa"]
    d1 = p1.get("direction") or "wait"
    quality = p1.get("quality") or "no_trade"
    news = p1.get("news_risk") or "low"
    conf = int(p1.get("confidence") or 0)
    prob = int(p1.get("probability") or 50)
    ev = p1.get("evidence") or {}
    oos = ev.get("oos") or {}
    expectancy = float(oos.get("expectancy") or 0)
    has_edge = bool(ev.get("has_edge"))
    best_strat = ev.get("best_strategy") or {}
    if has_edge and best_strat.get("has_edge") and best_strat.get("expectancy") is not None:
        expectancy = float(best_strat["expectancy"])
    plan = p1.get("plan") or {}
    reasons = [r.get("text") for r in (p1.get("reasons") or []) if r.get("text")][:4]
    core = ev.get("core") or {}
    core_side = core.get("side") if core.get("side") in {"buy", "sell", "wait"} else d1
    strategy = p1.get("primary_strategy_fa") or p1.get("primary_strategy") or core.get("strategy_fa") or "—"
    regime = p1.get("regime_fa") or "—"
    regime_id = p1.get("regime") or core.get("regime") or ""
    structure = (p1.get("structure") or {}).get("trend") or ""
    lean = _regime_lean(regime_id, structure, core_side if core_side in {"buy", "sell"} else None)

    action = d1 if d1 in {"buy", "sell"} else "wait"

    if action in {"buy", "sell"} and has_edge:
        status = "alert" if quality in ALERT_TIERS else "candidate"
    elif has_edge and action == "wait":
        status = "edge_wait"
        quality = "moderate"
    elif action in {"buy", "sell"} and not has_edge:
        status = "setup_no_edge"
        quality = "moderate"
    else:
        status = "no_edge"
        quality = "no_trade"

    success = int(plan.get("success_pct") or prob) if action in {"buy", "sell"} else (
        int(round(float(ev.get("calibrated_p") or 0.5) * 100)) if status == "edge_wait" else int(prob or 0)
    )

    rank = conf * 0.35 + max(-1.0, expectancy) * 55 + success * 0.25
    rank += max(0, 8 - TF_ORDER.get(interval, 5))
    if status in {"alert", "candidate"}:
        rank += 22
    elif status == "edge_wait":
        rank += 10
    if news == "high":
        rank -= 20

    if action == "buy":
        command = f"🟢 BUY  {_mt_symbol(symbol)}"
        entry, sl, tp = plan.get("buy_at"), plan.get("buy_sl"), plan.get("buy_tp")
        rr = plan.get("buy_rr") or plan.get("min_rr") or 2
        detail = f"ستاپ {TF_FA.get(interval, interval)}: {strategy} · رژیم {regime} · احتمال {success}٪"
    elif action == "sell":
        command = f"🔴 SELL  {_mt_symbol(symbol)}"
        entry, sl, tp = plan.get("sell_at"), plan.get("sell_sl"), plan.get("sell_tp")
        rr = plan.get("sell_rr") or plan.get("min_rr") or 2
        detail = f"ستاپ {TF_FA.get(interval, interval)}: {strategy} · رژیم {regime} · احتمال {success}٪"
    elif status == "edge_wait":
        command = f"⏳ دیده‌بان  {_mt_symbol(symbol)}"
        entry = sl = tp = None
        rr = plan.get("min_rr") or 2
        strat_fa = (best_strat or {}).get("strategy_fa") or strategy or "—"
        if strat_fa in {"بدون ستاپ معتبر", "none", None}:
            strat_fa = "کتاب معاملات تأییدشده"
        detail = f"لبه روی {TF_FA.get(interval, interval)} ({strat_fa} · EV {expectancy:+.2f}R) — ستاپ ورودی نیست."
    else:
        command = f"NO TRADE  {_mt_symbol(symbol)}"
        entry = sl = tp = None
        rr = plan.get("min_rr") or 2
        detail = p1.get("no_trade_reason") or (ev.get("verdict") or "لبه خارج از نمونه تأیید نشد.")

    return {
        "symbol": symbol,
        "mt_symbol": _mt_symbol(symbol),
        "name_fa": name,
        "name_en": ticker.get("name_en") or meta["name_en"],
        "icon": ticker.get("image") or ticker.get("icon") or meta["icon"],
        "price": ticker.get("price"),
        "change_24h": ticker.get("change_24h"),
        "price_prefix": ticker.get("price_prefix", meta.get("price_prefix", "$")),
        "market": p1.get("market"),
        "interval": interval,
        "interval_fa": TF_FA.get(interval, interval),
        "action": action,
        "status": status,
        "command": command,
        "detail": detail,
        "quality": quality,
        "quality_fa": p1.get("quality_fa") or TIER_FA.get(quality, quality),
        "strength": p1.get("quality_fa") or TIER_FA.get(quality, quality),
        "rank": round(float(rank), 1),
        "confidence": conf,
        "probability": prob,
        "success_pct": success,
        "expectancy": expectancy,
        "oos_trades": oos.get("trades") or 0,
        "oos_pf": oos.get("profit_factor"),
        "has_edge": has_edge,
        "min_rr": plan.get("min_rr") or 2,
        "rr": rr,
        "relative": False,
        "regime": regime,
        "horizon": p1.get("horizon"),
        "holding_period": p1.get("holding_period"),
        "primary_strategy": strategy,
        "invalidation": p1.get("invalidation"),
        "structure": structure,
        "core_side": core_side if core_side in {"buy", "sell", "wait"} else action,
        "lean": lean,
        "regime_id": regime_id,
        "entry": entry,
        "entry_zone": [entry, entry] if entry else p1.get("entry_zone"),
        "stop_loss": sl,
        "tp1": tp,
        "tp2": plan.get("buy_tp2") if action == "buy" else plan.get("sell_tp2") if action == "sell" else None,
        "buy_at": plan.get("buy_at"),
        "buy_sl": plan.get("buy_sl"),
        "buy_tp": plan.get("buy_tp"),
        "sell_at": plan.get("sell_at"),
        "sell_sl": plan.get("sell_sl"),
        "sell_tp": plan.get("sell_tp"),
        "news_risk": news,
        "reasons": reasons,
        "best_strategy": (best_strat or {}).get("strategy_fa"),
        "best_strategy_ev": (best_strat or {}).get("expectancy"),
        "mtf_aligned": None,
        "mtf_conflict": False,
        "mtf_note": "",
        "setup_map": "",
        "tf_stack": [],
        "full": full,
    }


def _candidate_from_lean(symbol: str, ticker: dict, interval: str, lean: dict) -> dict:
    meta = _pack(symbol)
    core = lean.get("core") or {}
    ev = lean.get("evidence") or {}
    regime_id = lean.get("regime") or core.get("regime") or ""
    regime = lean.get("regime_fa") or core.get("regime_fa") or "—"
    structure = ((lean.get("structure") or {}).get("trend") or "")
    lean_side = _regime_lean(regime_id, structure, core.get("side") if core.get("side") in {"buy", "sell"} else None)
    oos = ev.get("out_of_sample") or ev.get("oos") or {}
    return {
        "symbol": symbol,
        "mt_symbol": _mt_symbol(symbol),
        "name_fa": ticker.get("name_fa") or meta["name_fa"],
        "name_en": ticker.get("name_en") or meta["name_en"],
        "icon": ticker.get("image") or ticker.get("icon") or meta["icon"],
        "price": ticker.get("price"),
        "price_prefix": ticker.get("price_prefix", meta.get("price_prefix", "$")),
        "interval": interval,
        "interval_fa": TF_FA.get(interval, interval),
        "action": "wait",
        "status": "lean",
        "command": "",
        "detail": "",
        "quality": "no_trade",
        "quality_fa": "نقشه",
        "rank": 0,
        "success_pct": 0,
        "expectancy": float(oos.get("expectancy") or 0),
        "oos_trades": oos.get("trades") or 0,
        "has_edge": bool(ev.get("has_edge")),
        "regime": regime,
        "regime_id": regime_id,
        "primary_strategy": core.get("strategy_fa") or "—",
        "structure": structure,
        "core_side": core.get("side") or "wait",
        "lean": lean_side,
        "mtf_aligned": None,
        "mtf_conflict": False,
        "mtf_note": "",
        "full": False,
        "news_risk": "low",
        "reasons": [],
    }


def _regime_lean(regime_id: str, structure: str, core_side: str | None) -> str:
    if core_side in {"buy", "sell"}:
        return core_side
    if regime_id in {"strong_bull", "breakout"}:
        return "buy"
    if regime_id in {"strong_bear"}:
        return "sell"
    if structure in {"صعودی", "up"}:
        return "buy"
    if structure in {"نزولی", "down"}:
        return "sell"
    return "wait"


def _build_tf_stack(candidates: list[dict]) -> list[dict]:
    by_tf = {c["interval"]: c for c in candidates}
    stack = []
    for tf in ALL_INTERVALS:
        row = by_tf.get(tf)
        if not row:
            continue
        side = row.get("action") if row.get("action") in {"buy", "sell"} else (row.get("core_side") or "wait")
        if side not in {"buy", "sell"}:
            side = "wait"
        lean = row.get("lean") if row.get("lean") in {"buy", "sell"} else side
        display = side if side in {"buy", "sell"} else lean
        stack.append(
            {
                "interval": tf,
                "interval_fa": TF_FA.get(tf, tf),
                "side": side,
                "side_fa": DIR_FA.get(side, side),
                "lean": display,
                "lean_fa": DIR_FA.get(display, display),
                "regime": row.get("regime"),
                "strategy": row.get("primary_strategy"),
                "has_edge": bool(row.get("has_edge")),
                "expectancy": row.get("expectancy"),
                "status": row.get("status"),
                "role": "context" if tf in CONTEXT_INTERVALS else "signal",
            }
        )
    return stack


def _context_bias(stack: list[dict]) -> dict:
    for tf in CONTEXT_INTERVALS:
        hit = next((s for s in stack if s["interval"] == tf and s["side"] in {"buy", "sell"}), None)
        if hit:
            return {"bias": hit["side"], "bias_fa": hit["side_fa"], "interval": tf, "interval_fa": hit["interval_fa"], "regime": hit.get("regime")}
    for tf in CONTEXT_INTERVALS:
        hit = next((s for s in stack if s["interval"] == tf and s.get("lean") in {"buy", "sell"}), None)
        if hit:
            return {"bias": hit["lean"], "bias_fa": hit.get("lean_fa") or DIR_FA.get(hit["lean"], hit["lean"]), "interval": tf, "interval_fa": hit["interval_fa"], "regime": hit.get("regime")}
    return {"bias": "wait", "bias_fa": "خنثی / نامشخص", "interval": None, "interval_fa": None, "regime": None}


def _apply_mtf_context(row: dict, stack: list[dict], context: dict) -> None:
    if not row.get("full"):
        return
    bias = context.get("bias") or "wait"
    action = row.get("action")
    notes = []
    if bias in {"buy", "sell"}:
        notes.append(f"بافت بالاتر ({context.get('interval_fa') or 'HTF'}): {context.get('bias_fa')}")
    if action in {"buy", "sell"} and bias in {"buy", "sell"}:
        if action == bias:
            row["mtf_aligned"] = True
            row["mtf_conflict"] = False
            row["rank"] = round(float(row["rank"]) + 14, 1)
            notes.append("هم‌جهت با تایم بالاتر")
        else:
            row["mtf_aligned"] = False
            row["mtf_conflict"] = True
            row["rank"] = round(float(row["rank"]) - 18, 1)
            notes.append(f"تضاد: {row.get('interval_fa')} {DIR_FA.get(action)} در برابر {context.get('interval_fa')} {context.get('bias_fa')}")
    row["mtf_note"] = " · ".join(notes)
    row["setup_map"] = _setup_map_text(stack)


def _setup_map_text(stack: list[dict]) -> str:
    parts = []
    for s in stack:
        display = s.get("side") if s.get("side") in {"buy", "sell"} else s.get("lean") or "wait"
        mark = {"buy": "▲", "sell": "▼", "wait": "•"}.get(display, "•")
        edge = "+" if s.get("has_edge") else ""
        reg = f"/{s['regime']}" if s.get("regime") else ""
        parts.append(f"{s['interval_fa']}{edge} {mark}{DIR_FA.get(display, display)}{reg}")
    return " | ".join(parts)


def _pick_best(candidates: list[dict]) -> dict:
    full = [c for c in candidates if c.get("full")]
    pool = full or candidates
    order = {"alert": 0, "candidate": 1, "edge_wait": 2, "setup_no_edge": 3, "no_edge": 4, "lean": 5}
    ranked = sorted(
        pool,
        key=lambda c: (
            order.get(c.get("status"), 9),
            0 if c.get("mtf_aligned") else 1,
            1 if c.get("mtf_conflict") else 0,
            -float(c.get("rank") or 0),
            -int(c.get("success_pct") or 0),
            TF_ORDER.get(c.get("interval") or "5m", 9),
        ),
    )
    return ranked[0]


def _headline(best_buy, best_sell, scored, waits, min_odds: int) -> str:
    if best_buy and best_sell:
        return f"پیشنهاد فعال (≥{min_odds}٪): خرید {best_buy['name_fa']} · فروش {best_sell['name_fa']}"
    if best_buy:
        return f"پیشنهاد فعال (≥{min_odds}٪): {best_buy['command']} · {best_buy.get('interval_fa')} · {best_buy.get('success_pct')}٪"
    if best_sell:
        return f"پیشنهاد فعال (≥{min_odds}٪): {best_sell['command']} · {best_sell.get('interval_fa')} · {best_sell.get('success_pct')}٪"
    if waits:
        top = max(waits, key=lambda x: int(x.get("success_pct") or 0))
        return (
            f"پیشنهاد فعال بالای {min_odds}٪ نیست — {len(waits)} مورد در دیده‌بان "
            f"(نزدیک‌ترین: {top['name_fa']} {top.get('success_pct') or 0}٪)"
        )
    return f"NO TRADE — هیچ ستاپی با موفقیت ≥ {min_odds}٪ پیدا نشد"
