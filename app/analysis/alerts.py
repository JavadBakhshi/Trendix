"""Scan a universe of symbols and rank actionable buy/sell alerts."""

from __future__ import annotations

import asyncio

from app.analysis.indicators import add_indicators
from app.analysis.predictor import predict
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

_SEM = asyncio.Semaphore(4)


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


async def scan_alerts(extra: list[str] | None = None) -> dict:
    symbols = list(dict.fromkeys(DEFAULT_UNIVERSE + [s.upper() for s in (extra or []) if s]))
    results = await asyncio.gather(*[_score_symbol(s) for s in symbols], return_exceptions=True)
    scored = [r for r in results if isinstance(r, dict)]
    buys = sorted([r for r in scored if r["action"] == "buy"], key=lambda x: x["rank"], reverse=True)
    sells = sorted([r for r in scored if r["action"] == "sell"], key=lambda x: x["rank"], reverse=True)
    waits = sorted([r for r in scored if r["action"] == "wait"], key=lambda x: x["rank"], reverse=True)
    if not buys and scored:
        rel = max(scored, key=lambda x: x.get("probability") or 0)
        buys = [_as_relative(rel, "buy")]
    if not sells and scored:
        ordered = sorted(scored, key=lambda x: x.get("probability") or 100)
        cand = ordered[0]
        if buys and cand["symbol"] == buys[0]["symbol"] and len(ordered) > 1:
            cand = ordered[1]
        sells = [_as_relative(cand, "sell")]
    best_buy = buys[0] if buys else None
    best_sell = sells[0] if sells else None
    return {
        "best_buy": best_buy,
        "best_sell": best_sell,
        "buys": buys[:5],
        "sells": sells[:5],
        "watched": waits[:6],
        "headline": _headline(best_buy, best_sell),
        "disclaimer": "هشدار معاملاتی آموزشی است، تأخیر داده دارد و توصیه مالی نیست.",
    }


async def _score_symbol(symbol: str) -> dict | None:
    async with _SEM:
        try:
            ticker, h1, m15 = await asyncio.gather(
                market.ticker(symbol),
                market.klines_df(symbol, "1h"),
                market.klines_df(symbol, "15m"),
            )
        except Exception:
            return None
        if h1 is None or getattr(h1, "empty", True):
            return None
        p1 = predict(add_indicators(h1), "1h", symbol)
        p15 = predict(add_indicators(m15), "15m", symbol) if m15 is not None and not m15.empty else {}
        d1 = p1.get("direction") or "neutral"
        d15 = p15.get("direction") or "neutral"
        agree = d1 == d15 and d1 in {"buy", "sell"}
        news = p1.get("news_risk") or "low"
        conf = int(p1.get("confidence") or 0)
        prob = int(p1.get("probability") or 50)
        move = float(p1.get("change_pct") or 0)
        if d1 == "buy" or (d1 == "neutral" and prob >= 54):
            action = "buy"
        elif d1 == "sell" or (d1 == "neutral" and prob <= 46):
            action = "sell"
        else:
            action = "wait"

        if action == "wait":
            rank = conf / 5
            strength = "ضعیف"
        else:
            lean_prob = prob if action == "buy" else max(0, 100 - prob)
            rank = conf * 0.4 + lean_prob * 0.3
            rank += 16 if agree else 0
            rank += min(14, abs(move) * 7)
            if d1 == "neutral":
                rank *= 0.72
            if news == "high":
                rank -= 18
            elif news == "medium":
                rank -= 8
            if rank >= 68 and agree and news != "high" and d1 == action:
                strength = "قوی"
            elif rank >= 46 and d1 == action:
                strength = "متوسط"
            else:
                strength = "ضعیف"
        meta = _pack(symbol)
        name = ticker.get("name_fa") or meta["name_fa"]
        if action == "buy":
            command = f"این را بخر: {name}"
            if d1 != "buy":
                detail = "هنوز سیگنال قطعی نیست؛ فقط تمایل نسبی به خرید نسبت به بقیه دیده می‌شود."
            else:
                detail = f"مدل در تایم ۱ ساعت سمت خرید است" + (" و ۱۵ دقیقه هم تأیید می‌کند." if agree else ".")
        elif action == "sell":
            command = f"این را بفروش: {name}"
            if d1 != "sell":
                detail = "هنوز سیگنال قطعی نیست؛ فقط تمایل نسبی به فروش نسبت به بقیه دیده می‌شود."
            else:
                detail = f"مدل در تایم ۱ ساعت سمت فروش است" + (" و ۱۵ دقیقه هم تأیید می‌کند." if agree else ".")
        else:
            command = f"صبر کن: {name}"
            if news == "high":
                detail = "خبر پرریسک نزدیک است؛ حتی اگر تمایل وجود دارد عجله نکنید."
            else:
                detail = "سیگنال به‌اندازهٔ کافی هم‌جهت یا قوی نیست."
        reasons = [r.get("text") for r in (p1.get("reasons") or []) if r.get("text")][:3]
        return {
            "symbol": symbol,
            "name_fa": name,
            "name_en": ticker.get("name_en") or meta["name_en"],
            "icon": ticker.get("image") or ticker.get("icon") or meta["icon"],
            "price": ticker.get("price"),
            "change_24h": ticker.get("change_24h"),
            "price_prefix": ticker.get("price_prefix", meta.get("price_prefix", "$")),
            "action": action,
            "command": command,
            "detail": detail,
            "strength": strength,
            "rank": round(float(rank), 1),
            "agree": agree,
            "confidence": conf,
            "probability": prob,
            "expected_move": round(move, 3),
            "regime": p1.get("regime_fa"),
            "horizon": p1.get("horizon"),
            "entry_zone": p1.get("entry_zone"),
            "stop_loss": p1.get("stop_loss"),
            "tp1": p1.get("tp1"),
            "tp2": p1.get("tp2"),
            "news_risk": news,
            "reasons": reasons,
        }


def _as_relative(row: dict, action: str) -> dict:
    out = dict(row)
    out["action"] = action
    out["strength"] = "ضعیف"
    out["rank"] = max(8.0, float(row.get("rank") or 0) * 0.6)
    name = row.get("name_fa") or row.get("symbol")
    if action == "buy":
        out["command"] = f"بهترین تمایل خرید (نسبی): {name}"
        out["detail"] = "بین نمادهای اسکن‌شده بیشترین تمایل به خرید را دارد؛ هنوز هشدار قوی نیست."
    else:
        out["command"] = f"بهترین تمایل فروش (نسبی): {name}"
        out["detail"] = "بین نمادهای اسکن‌شده بیشترین تمایل به فروش را دارد؛ هنوز هشدار قوی نیست."
    return out


def _headline(best_buy: dict | None, best_sell: dict | None) -> str:
    if best_buy and best_sell and best_buy["rank"] >= 58 and best_sell["rank"] >= 58:
        return f"بهترین خرید: {best_buy['name_fa']}  ·  بهترین فروش: {best_sell['name_fa']}"
    if best_buy and best_buy["rank"] >= 58:
        return f"الان این را بخر: {best_buy['name_fa']}"
    if best_sell and best_sell["rank"] >= 58:
        return f"الان این را بفروش: {best_sell['name_fa']}"
    if best_buy or best_sell:
        pick = best_buy if (best_buy and (not best_sell or best_buy["rank"] >= best_sell["rank"])) else best_sell
        return f"فرصت نسبی: {pick['command']} — هنوز سیگنال خیلی قوی نیست"
    return "الان هشدار قوی برای خرید یا فروش نیست؛ صبر منطقی‌تر است"
