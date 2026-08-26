"""Market structure, S/R, liquidity, Fibonacci, pivots, and simple chart patterns."""

from __future__ import annotations

import numpy as np
import pandas as pd


def analyze_structure(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 30:
        return _empty()
    price = float(df["close"].iloc[-1])
    atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else price * 0.01
    swings = _swings(df, left=3, right=3)
    trend = _structure_trend(swings)
    bos, choch = _bos_choch(df, swings, price)
    levels = _sr_levels(df, swings, price, atr)
    fib = _fibonacci(swings, price)
    pivots = _pivots(df)
    fvg = _fair_value_gaps(df, atr)
    liquidity = _liquidity(swings, price, atr)
    pattern = _chart_pattern(swings, price, atr)
    premium = price > ((levels["nearest_support"] + levels["nearest_resistance"]) / 2) if levels["nearest_support"] and levels["nearest_resistance"] else False

    score = 0.0
    reasons = []
    if trend == "up":
        score += 28
        reasons.append({"id": "structure", "text": "ساختار بازار صعودی است (Higher High / Higher Low)", "bias": "buy"})
    elif trend == "down":
        score -= 28
        reasons.append({"id": "structure", "text": "ساختار بازار نزولی است (Lower High / Lower Low)", "bias": "sell"})
    else:
        reasons.append({"id": "structure", "text": "ساختار بازار رنج / بدون روند واضح است", "bias": "neutral"})

    if bos == "bullish":
        score += 18
        reasons.append({"id": "bos", "text": "شکست ساختار صعودی (BOS) رخ داده", "bias": "buy"})
    elif bos == "bearish":
        score -= 18
        reasons.append({"id": "bos", "text": "شکست ساختار نزولی (BOS) رخ داده", "bias": "sell"})
    if choch == "bullish":
        score += 14
        reasons.append({"id": "choch", "text": "تغییر شخصیت بازار به صعودی (CHoCH)", "bias": "buy"})
    elif choch == "bearish":
        score -= 14
        reasons.append({"id": "choch", "text": "تغییر شخصیت بازار به نزولی (CHoCH)", "bias": "sell"})

    if liquidity.get("sweep") == "sell_side":
        score += 10
        reasons.append({"id": "liq", "text": "جمع‌آوری نقدینگی سمت فروش (Liquidity Sweep)", "bias": "buy"})
    elif liquidity.get("sweep") == "buy_side":
        score -= 10
        reasons.append({"id": "liq", "text": "جمع‌آوری نقدینگی سمت خرید (Liquidity Sweep)", "bias": "sell"})

    if pattern:
        score += 12 if pattern["bias"] == "buy" else -12 if pattern["bias"] == "sell" else 0
        reasons.append({"id": "pattern", "text": f"الگوی {pattern['name_fa']} با اطمینان {pattern['confidence']}٪", "bias": pattern["bias"]})

    if premium and trend == "up":
        score -= 6
        reasons.append({"id": "premium", "text": "قیمت در ناحیه Premium است؛ ورود بهتر روی پولبک", "bias": "neutral"})
    elif not premium and trend == "down":
        score += 6
        reasons.append({"id": "discount", "text": "قیمت در ناحیه Discount است؛ فروش روی برگشت محتمل‌تر", "bias": "neutral"})

    return {
        "trend": trend,
        "trend_label": {"up": "صعودی", "down": "نزولی", "sideways": "رنج"}[trend],
        "bos": bos,
        "choch": choch,
        "levels": levels,
        "fib": fib,
        "pivots": pivots,
        "fvg": fvg,
        "liquidity": liquidity,
        "pattern": pattern,
        "premium": premium,
        "score": float(np.clip(score, -100, 100)),
        "reasons": reasons,
    }


def _swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> dict:
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    highs, lows = [], []
    for i in range(left, len(df) - right):
        window_h = high[i - left : i + right + 1]
        window_l = low[i - left : i + right + 1]
        if high[i] >= window_h.max():
            highs.append({"i": i, "price": float(high[i]), "time": df["time"].iloc[i]})
        if low[i] <= window_l.min():
            lows.append({"i": i, "price": float(low[i]), "time": df["time"].iloc[i]})
    return {"highs": highs[-12:], "lows": lows[-12:]}


def _structure_trend(swings: dict) -> str:
    highs = [s["price"] for s in swings["highs"][-4:]]
    lows = [s["price"] for s in swings["lows"][-4:]]
    hh = len(highs) >= 2 and highs[-1] > highs[-2]
    hl = len(lows) >= 2 and lows[-1] > lows[-2]
    lh = len(highs) >= 2 and highs[-1] < highs[-2]
    ll = len(lows) >= 2 and lows[-1] < lows[-2]
    if hh and hl:
        return "up"
    if lh and ll:
        return "down"
    return "sideways"


def _bos_choch(df: pd.DataFrame, swings: dict, price: float) -> tuple[str | None, str | None]:
    bos = choch = None
    if swings["highs"] and price > swings["highs"][-1]["price"] and float(df["close"].iloc[-1]) > swings["highs"][-1]["price"]:
        bos = "bullish"
    if swings["lows"] and price < swings["lows"][-1]["price"] and float(df["close"].iloc[-1]) < swings["lows"][-1]["price"]:
        bos = "bearish"
    if len(swings["highs"]) >= 2 and len(swings["lows"]) >= 2:
        prev_up = swings["highs"][-1]["price"] > swings["highs"][-2]["price"]
        if prev_up and bos == "bearish":
            choch = "bearish"
        if not prev_up and bos == "bullish":
            choch = "bullish"
    return bos, choch


def _sr_levels(df: pd.DataFrame, swings: dict, price: float, atr: float) -> dict:
    raw = [s["price"] for s in swings["highs"] + swings["lows"]]
    raw += [
        float(df["high"].tail(24).max()),
        float(df["low"].tail(24).min()),
        float(df["high"].iloc[-2]) if len(df) > 2 else price,
        float(df["low"].iloc[-2]) if len(df) > 2 else price,
    ]
    clustered = _cluster(raw, atr * 0.35)
    supports = sorted([lv for lv in clustered if lv < price], reverse=True)
    resists = sorted([lv for lv in clustered if lv > price])
    ns = supports[0] if supports else None
    nr = resists[0] if resists else None
    return {
        "supports": supports[:4],
        "resistances": resists[:4],
        "nearest_support": ns,
        "nearest_resistance": nr,
        "support_strength": _strength(ns, clustered, atr) if ns else 0,
        "resistance_strength": _strength(nr, clustered, atr) if nr else 0,
        "prev_day_high": float(df["high"].tail(min(len(df), 48)).max()),
        "prev_day_low": float(df["low"].tail(min(len(df), 48)).min()),
    }


def _cluster(levels: list[float], tol: float) -> list[float]:
    if not levels:
        return []
    levels = sorted(levels)
    groups = [[levels[0]]]
    for lv in levels[1:]:
        if abs(lv - groups[-1][-1]) <= max(tol, 1e-9):
            groups[-1].append(lv)
        else:
            groups.append([lv])
    return [float(np.mean(g)) for g in groups]


def _strength(level: float, clustered: list[float], atr: float) -> int:
    hits = sum(1 for lv in clustered if abs(lv - level) <= atr * 0.4)
    return int(np.clip(40 + hits * 18, 20, 95))


def _fibonacci(swings: dict, price: float) -> dict:
    if not swings["highs"] or not swings["lows"]:
        return {}
    hi = max(s["price"] for s in swings["highs"][-4:])
    lo = min(s["price"] for s in swings["lows"][-4:])
    span = hi - lo
    if span <= 0:
        return {}
    retr = {r: hi - span * r for r in (0.236, 0.382, 0.5, 0.618, 0.786)}
    nearest = min(retr.items(), key=lambda kv: abs(kv[1] - price))
    return {
        "high": hi,
        "low": lo,
        "retracements": retr,
        "nearest": nearest[0],
        "nearest_price": nearest[1],
        "extension_127": hi + span * 0.272,
        "extension_161": hi + span * 0.618,
    }


def _pivots(df: pd.DataFrame) -> dict:
    prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    h, l, c = float(prev["high"]), float(prev["low"]), float(prev["close"])
    p = (h + l + c) / 3
    r1 = 2 * p - l
    s1 = 2 * p - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    return {"p": p, "r1": r1, "s1": s1, "r2": r2, "s2": s2}


def _fair_value_gaps(df: pd.DataFrame, atr: float) -> list[dict]:
    gaps = []
    for i in range(2, len(df)):
        a_high = float(df["high"].iloc[i - 2])
        a_low = float(df["low"].iloc[i - 2])
        c_high = float(df["high"].iloc[i])
        c_low = float(df["low"].iloc[i])
        if c_low > a_high and (c_low - a_high) > atr * 0.15:
            gaps.append({"type": "bullish", "low": a_high, "high": c_low})
        elif c_high < a_low and (a_low - c_high) > atr * 0.15:
            gaps.append({"type": "bearish", "low": c_high, "high": a_low})
    return gaps[-4:]


def _liquidity(swings: dict, price: float, atr: float) -> dict:
    eq_high = False
    eq_low = False
    highs = [s["price"] for s in swings["highs"][-5:]]
    lows = [s["price"] for s in swings["lows"][-5:]]
    if len(highs) >= 2 and abs(highs[-1] - highs[-2]) <= atr * 0.25:
        eq_high = True
    if len(lows) >= 2 and abs(lows[-1] - lows[-2]) <= atr * 0.25:
        eq_low = True
    sweep = None
    if lows and price < min(lows[-2:]) and price > min(lows[-2:]) - atr:
        sweep = "sell_side"
    if highs and price > max(highs[-2:]) and price < max(highs[-2:]) + atr:
        sweep = "buy_side"
    return {
        "equal_highs": eq_high,
        "equal_lows": eq_low,
        "buy_side": max(highs) if highs else None,
        "sell_side": min(lows) if lows else None,
        "sweep": sweep,
    }


def _chart_pattern(swings: dict, price: float, atr: float) -> dict | None:
    highs = [s["price"] for s in swings["highs"][-5:]]
    lows = [s["price"] for s in swings["lows"][-5:]]
    if len(highs) >= 2 and abs(highs[-1] - highs[-2]) <= atr * 0.3 and price < min(highs[-2:]) - atr * 0.1:
        return {"name": "double_top", "name_fa": "کله‌دوقلو", "bias": "sell", "confidence": 72}
    if len(lows) >= 2 and abs(lows[-1] - lows[-2]) <= atr * 0.3 and price > max(lows[-2:]) + atr * 0.1:
        return {"name": "double_bottom", "name_fa": "کف دوقلو", "bias": "buy", "confidence": 72}
    if len(highs) >= 3 and highs[-2] > highs[-1] and highs[-2] > highs[-3] and abs(highs[-1] - highs[-3]) <= atr * 0.45:
        return {"name": "head_shoulders", "name_fa": "سر و شانه", "bias": "sell", "confidence": 64}
    if len(highs) >= 3 and highs[-1] < highs[-2] < highs[-3] and len(lows) >= 2 and lows[-1] > lows[-2]:
        return {"name": "triangle", "name_fa": "مثلث", "bias": "neutral", "confidence": 58}
    if len(highs) >= 2 and len(lows) >= 2:
        rng_now = abs(highs[-1] - lows[-1])
        rng_prev = abs(highs[-2] - lows[-2]) if len(highs) > 1 else rng_now
        if rng_prev > 0 and rng_now / rng_prev < 0.55:
            return {"name": "flag", "name_fa": "پرچم / فشردگی", "bias": "neutral", "confidence": 55}
    return None


def _empty() -> dict:
    return {
        "trend": "sideways",
        "trend_label": "رنج",
        "bos": None,
        "choch": None,
        "levels": {"supports": [], "resistances": [], "nearest_support": None, "nearest_resistance": None, "support_strength": 0, "resistance_strength": 0},
        "fib": {},
        "pivots": {},
        "fvg": [],
        "liquidity": {},
        "pattern": None,
        "premium": False,
        "score": 0.0,
        "reasons": [],
    }
