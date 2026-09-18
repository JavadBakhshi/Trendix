"""Grouped indicator votes — correlated oscillators share one vote."""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_indicators(df: pd.DataFrame, regime: str) -> dict:
    if df.empty:
        return {"score": 0.0, "trend_vote": 0, "momentum_vote": 0, "reasons": []}
    row = df.iloc[-1]
    price = float(row["close"])
    reasons = []

    trend_votes = []
    ema50 = _f(row.get("ema50"))
    sma200 = _f(row.get("sma200"))
    kijun = _f(row.get("kijun"))
    tenkan = _f(row.get("tenkan"))
    psar = _f(row.get("psar"))
    plus_di = _f(row.get("plus_di"))
    minus_di = _f(row.get("minus_di"))
    if ema50 == ema50:
        trend_votes.append(1 if price > ema50 else -1)
    if sma200 == sma200:
        trend_votes.append(1 if price > sma200 else -1)
    if kijun == kijun and tenkan == tenkan:
        trend_votes.append(1 if tenkan > kijun and price > kijun else -1 if tenkan < kijun and price < kijun else 0)
    if psar == psar:
        trend_votes.append(1 if price > psar else -1)
    if plus_di == plus_di and minus_di == minus_di:
        trend_votes.append(1 if plus_di > minus_di else -1)
    trend_vote = float(np.mean(trend_votes)) if trend_votes else 0.0
    if trend_vote > 0.2:
        reasons.append({"id": "trend", "text": "گروه روند (EMA/Ichimoku/PSAR/ADX) صعودی است", "bias": "buy"})
    elif trend_vote < -0.2:
        reasons.append({"id": "trend", "text": "گروه روند نزولی است", "bias": "sell"})

    mom = []
    rsi = _f(row.get("rsi"))
    macd_h = _f(row.get("macd_hist"))
    stoch = _f(row.get("stoch_k"))
    cci = _f(row.get("cci"))
    willr = _f(row.get("willr"))
    if rsi == rsi:
        mom.append(1 if rsi < 35 else -1 if rsi > 65 else 0.3 if rsi > 55 else -0.3 if rsi < 45 else 0)
    if macd_h == macd_h:
        mom.append(1 if macd_h > 0 else -1)
    if stoch == stoch:
        mom.append(1 if stoch < 25 else -1 if stoch > 75 else 0)
    if cci == cci:
        mom.append(1 if cci < -100 else -1 if cci > 100 else 0)
    if willr == willr:
        mom.append(1 if willr < -80 else -1 if willr > -20 else 0)
    momentum_vote = float(np.median(mom)) if mom else 0.0
    if abs(momentum_vote) >= 0.5:
        reasons.append(
            {
                "id": "momentum",
                "text": "گروه مومنتوم (RSI/MACD/Stoch/CCI) " + ("خرید" if momentum_vote > 0 else "فروش"),
                "bias": "buy" if momentum_vote > 0 else "sell",
            }
        )

    family = _family(regime)
    bb = _f(row.get("bb_pct"))
    vol_vote = 0.0
    if bb == bb:
        if family == "ranging":
            vol_vote = 1 if bb <= 0.2 else -1 if bb >= 0.8 else 0
        elif family == "trending":
            vol_vote = 0.4 if 0.55 <= bb <= 0.9 else -0.4 if 0.1 <= bb <= 0.45 else 0

    if family == "trending":
        score = 55 * trend_vote + 25 * momentum_vote + 20 * vol_vote
    elif family == "ranging":
        score = 20 * trend_vote + 35 * momentum_vote + 45 * vol_vote
    else:
        score = 40 * trend_vote + 30 * momentum_vote + 30 * vol_vote

    return {
        "score": float(np.clip(score, -100, 100)),
        "trend_vote": round(trend_vote, 2),
        "momentum_vote": round(momentum_vote, 2),
        "reasons": reasons,
    }


def _family(regime: str) -> str:
    if regime in {"strong_bull", "strong_bear", "weak_trend", "breakout", "trending"}:
        return "trending"
    if regime in {"range", "ranging", "mean_reversion"}:
        return "ranging"
    if regime in {"compression"}:
        return "compression"
    return "ranging"


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
