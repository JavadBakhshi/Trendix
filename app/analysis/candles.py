"""Candlestick patterns and buyer/seller pressure."""

from __future__ import annotations

import numpy as np
import pandas as pd


def analyze_candles(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 5:
        return {"score": 0.0, "patterns": [], "pressure": "neutral", "reasons": []}
    last = df.iloc[-2:] if len(df) >= 2 else df.iloc[-1:]
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else row
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    po, ph, pl, pc = float(prev["open"]), float(prev["high"]), float(prev["low"]), float(prev["close"])
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    upper = h - max(c, o)
    lower = min(c, o) - l
    vol_ratio = float(row["volume_ratio"]) if "volume_ratio" in row and pd.notna(row["volume_ratio"]) else 1.0

    patterns = []
    score = 0.0

    def add(name, name_fa, bias, pts, conf):
        patterns.append({"name": name, "name_fa": name_fa, "bias": bias, "confidence": conf})
        nonlocal score
        score += pts

    bull = c > o
    if body / rng < 0.12:
        add("doji", "دوجی", "neutral", 0, 70)
    if lower > body * 2 and upper < body * 0.4 and body / rng < 0.4:
        add("hammer" if bull or lower > upper else "pin_bar", "چکش / پین بار", "buy", 16, 74)
    if upper > body * 2 and lower < body * 0.4 and body / rng < 0.4:
        add("shooting_star", "ستاره دنباله‌دار", "sell", -16, 74)
    if body / rng > 0.78:
        add("marubozu", "ماروبوزو", "buy" if bull else "sell", 12 if bull else -12, 68)
    if c > o and pc < po and c >= po and o <= pc:
        add("engulfing", "پوشای صعودی", "buy", 18, 76)
    if c < o and pc > po and c <= po and o >= pc:
        add("engulfing", "پوشای نزولی", "sell", -18, 76)
    if h < ph and l > pl:
        add("inside_bar", "اینساید بار", "neutral", 0, 62)
    if h > ph and l < pl:
        add("outside_bar", "اوتساید بار", "buy" if bull else "sell", 8 if bull else -8, 60)

    if len(df) >= 3:
        a, b, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if float(a["close"]) < float(a["open"]) and abs(float(b["close"]) - float(b["open"])) / max(float(b["high"]) - float(b["low"]), 1e-9) < 0.35 and float(c3["close"]) > float(c3["open"]) and float(c3["close"]) > (float(a["open"]) + float(a["close"])) / 2:
            add("morning_star", "ستاره صبحگاهی", "buy", 16, 73)
        if float(a["close"]) > float(a["open"]) and abs(float(b["close"]) - float(b["open"])) / max(float(b["high"]) - float(b["low"]), 1e-9) < 0.35 and float(c3["close"]) < float(c3["open"]) and float(c3["close"]) < (float(a["open"]) + float(a["close"])) / 2:
            add("evening_star", "ستاره شامگاهی", "sell", -16, 73)

    if vol_ratio >= 1.4:
        score += 6 if bull else -6
    wick_dom = "buyers" if lower > upper * 1.4 else "sellers" if upper > lower * 1.4 else "neutral"
    pressure = "buy" if (bull and body / rng > 0.5) or wick_dom == "buyers" else "sell" if (not bull and body / rng > 0.5) or wick_dom == "sellers" else "neutral"
    if wick_dom == "buyers":
        score += 6
    elif wick_dom == "sellers":
        score -= 6

    reasons = [{"id": "candle", "text": f"کندل: {p['name_fa']}", "bias": p["bias"]} for p in patterns[:3]]
    if not reasons:
        reasons.append({"id": "candle", "text": "کندل خاصی با اطمینان بالا دیده نشد", "bias": "neutral"})
    return {
        "score": float(np.clip(score, -100, 100)),
        "patterns": patterns[:5],
        "pressure": pressure,
        "body_ratio": round(body / rng, 3),
        "volume_ratio": round(vol_ratio, 2),
        "reasons": reasons,
    }
