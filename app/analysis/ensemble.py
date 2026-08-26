"""Weighted ensemble: regime-aware layers, risk, explainable output."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.candles import analyze_candles
from app.analysis.indicator_votes import score_indicators
from app.analysis.layers import analyze_regime, analyze_session, analyze_stats, analyze_volume
from app.analysis.ml_models import score_ml
from app.analysis.structure import analyze_structure
from app.config import HORIZON_FA, TIMEFRAMES


BASE_WEIGHTS = {
    "structure": 0.22,
    "indicators": 0.16,
    "candles": 0.09,
    "volume": 0.08,
    "stats": 0.10,
    "ml": 0.16,
    "mtf": 0.11,
    "session": 0.04,
    "sentiment": 0.04,
}


def combine(
    df: pd.DataFrame,
    interval: str,
    symbol: str,
    volume_source: str | None,
    mtf: dict | None = None,
    sentiment: dict | None = None,
    news: dict | None = None,
) -> dict:
    if df.empty or len(df) < 30:
        return empty_prediction(interval)

    price = float(df["close"].iloc[-1])
    atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else price * 0.008
    regime = analyze_regime(df)
    structure = analyze_structure(df)
    candles = analyze_candles(df)
    volume = analyze_volume(df, volume_source)
    stats = analyze_stats(df)
    indicators = score_indicators(df, regime["regime"])
    ml = score_ml(df)
    session = analyze_session(interval, symbol)
    mtf_score, mtf_reasons = _mtf_score(mtf)

    weights = dict(BASE_WEIGHTS)
    if regime["regime"] == "trending":
        weights["structure"] += 0.06
        weights["indicators"] += 0.03
        weights["stats"] -= 0.04
        weights["candles"] -= 0.02
    elif regime["regime"] == "ranging":
        weights["stats"] += 0.05
        weights["indicators"] += 0.03
        weights["structure"] -= 0.04
        weights["ml"] -= 0.02
    if news and news.get("level") == "high":
        for k in weights:
            weights[k] *= 0.85
        weights["session"] += 0.05

    layers = {
        "structure": structure["score"],
        "indicators": indicators["score"],
        "candles": candles["score"],
        "volume": volume["score"],
        "stats": stats["score"],
        "ml": ml["score"],
        "mtf": mtf_score,
        "session": session["score"],
        "sentiment": (sentiment or {}).get("score") or 0.0,
    }
    wsum = sum(weights.values()) or 1
    final = sum(layers[k] * weights[k] for k in layers) / wsum
    news_pen = (news or {}).get("score") or 0.0
    final = float(np.clip(final + news_pen * 0.35, -100, 100))

    agreement = _agreement(layers)
    if final >= 16:
        direction, label = "buy", "خرید"
    elif final <= -16:
        direction, label = "sell", "فروش"
    else:
        direction, label = "neutral", "نگه‌دار / خنثی"
    if abs(final) >= 42:
        label = "خرید قوی" if direction == "buy" else "فروش قوی" if direction == "sell" else label

    probability = int(np.clip(50 + final * 0.42, 8, 92))
    if direction == "sell":
        probability = 100 - probability
    if direction == "neutral":
        probability = int(50 + final * 0.15)

    confidence = int(np.clip(32 + abs(final) * 0.5 + agreement * 18, 18, 90))
    if news and news.get("level") == "high":
        confidence = max(18, confidence - 18)
        direction, label = "neutral", "صبر به‌خاطر خبر"
    if ml.get("hit_rate") and ml["hit_rate"] < 52:
        confidence = max(18, confidence - 8)

    conf_level = "HIGH" if confidence >= 70 else "MEDIUM" if confidence >= 50 else "LOW"
    conf_fa = {"HIGH": "بالا", "MEDIUM": "متوسط", "LOW": "پایین"}[conf_level]

    expected = ml["expected_return"] if ml.get("ok") else final / 9000
    if regime["volatility"] == "high":
        expected *= 1.15
    elif regime["volatility"] == "low":
        expected *= 0.7
    if direction == "sell" and expected > 0:
        expected = -abs(expected)
    if direction == "buy" and expected < 0:
        expected = abs(expected)
    if direction == "neutral":
        expected *= 0.25

    target = price * (1 + expected)
    change_pct = (target - price) / price * 100
    risk = _risk_plan(price, atr, direction, structure.get("levels") or {}, expected)
    seconds = next((tf["seconds"] for tf in TIMEFRAMES if tf["id"] == interval), 3600)
    last_ts = int(df.iloc[-1]["time"].timestamp())
    forecast = _forecast(price, expected, last_ts, seconds)

    reasons = []
    for block in (
        structure.get("reasons"),
        indicators.get("reasons"),
        candles.get("reasons"),
        volume.get("reasons"),
        stats.get("reasons"),
        ml.get("reasons"),
        mtf_reasons,
        session.get("reasons"),
        (sentiment or {}).get("reasons"),
        (news or {}).get("reasons"),
        regime.get("reasons"),
    ):
        reasons.extend(block or [])
    reasons = [r for r in reasons if r.get("bias") != "neutral"][:8] + [r for r in reasons if r.get("bias") == "neutral"][:4]

    risks = []
    if news and news.get("level") in {"high", "medium"}:
        risks.append((news["reasons"] or [{}])[0].get("text") or "ریسک خبر")
    if regime["volatility"] == "high":
        risks.append("نوسان بالاست؛ استاپ را بزرگ‌تر در نظر بگیرید")
    if agreement < 0.35:
        risks.append("لایه‌های مدل با هم هم‌جهت نیستند")
    if not risks:
        risks.append("ریسک معمولی بازار؛ این خروجی توصیه سرمایه‌گذاری نیست")

    layer_pct = {k: int(np.clip(50 + v * 0.45, 5, 95)) for k, v in layers.items()}
    summary = (
        f"{label} با احتمال {probability}٪ و اطمینان {conf_fa}. "
        f"رژیم: {regime['regime_fa']} · نوسان {regime['volatility_fa']}. "
        f"{reasons[0]['text'] if reasons else ''}"
    )

    return {
        "direction": direction,
        "label": label,
        "probability": probability,
        "confidence": confidence,
        "confidence_level": conf_level,
        "confidence_fa": conf_fa,
        "target_price": _round_price(target),
        "change_pct": round(change_pct, 3),
        "expected_move": round(change_pct, 3),
        "horizon": HORIZON_FA.get(interval, interval),
        "interval": interval,
        "entry_zone": risk["entry_zone"],
        "stop_loss": risk["stop_loss"],
        "tp1": risk["tp1"],
        "tp2": risk["tp2"],
        "risk_reward": risk["rr"],
        "regime": regime["regime"],
        "regime_fa": regime["regime_fa"],
        "volatility": regime["volatility"],
        "volatility_fa": regime["volatility_fa"],
        "structure": {
            "trend": structure["trend_label"],
            "bos": structure["bos"],
            "choch": structure["choch"],
            "pattern": structure.get("pattern"),
            "support": structure["levels"].get("nearest_support"),
            "resistance": structure["levels"].get("nearest_resistance"),
            "support_strength": structure["levels"].get("support_strength"),
            "resistance_strength": structure["levels"].get("resistance_strength"),
            "liquidity": structure.get("liquidity"),
        },
        "candles": candles.get("patterns"),
        "layers": layer_pct,
        "layer_scores": {k: round(v, 1) for k, v in layers.items()},
        "ml": {
            "up_prob": ml.get("up_prob"),
            "down_prob": ml.get("down_prob"),
            "hit_rate": ml.get("hit_rate"),
            "ok": ml.get("ok"),
        },
        "session": session.get("session_fa"),
        "sentiment": sentiment or {},
        "news_risk": (news or {}).get("level", "low"),
        "news_events": (news or {}).get("events") or [],
        "volume_note": volume.get("source_note"),
        "reasons": reasons[:10],
        "risks": risks[:4],
        "summary": summary,
        "forecast": forecast,
        "ta_score": round(indicators["score"], 1),
        "ml_ok": bool(ml.get("ok")),
        "disclaimer": "این پیش‌بینی آموزشی است، بک‌تست تضمینی برای آینده نیست و توصیه مالی محسوب نمی‌شود.",
    }


def _mtf_score(mtf: dict | None) -> tuple[float, list[dict]]:
    if not mtf:
        return 0.0, []
    votes = []
    reasons = []
    for tf, info in mtf.items():
        d = info.get("direction")
        if d == "buy":
            votes.append(1)
        elif d == "sell":
            votes.append(-1)
        else:
            votes.append(0)
        reasons.append({"id": "mtf", "text": f"{tf}: {info.get('label', d)}", "bias": d or "neutral"})
    if not votes:
        return 0.0, []
    mean = float(np.mean(votes))
    # higher TFs already listed first if caller orders them
    score = mean * 70
    if abs(mean) >= 0.6:
        reasons.insert(0, {"id": "confluence", "text": "هم‌جهتی تایم‌فریم‌ها (Confluence) برقرار است", "bias": "buy" if mean > 0 else "sell"})
    return float(np.clip(score, -100, 100)), reasons[:6]


def _agreement(layers: dict) -> float:
    signs = [np.sign(v) for v in layers.values() if abs(v) >= 6]
    if len(signs) < 2:
        return 0.4
    maj = np.sign(np.mean(signs))
    return float(np.mean([1 if s == maj else 0 for s in signs]))


def _risk_plan(price: float, atr: float, direction: str, levels: dict, expected: float) -> dict:
    sl_dist = max(atr * 1.4, price * 0.002)
    if direction == "buy":
        support = levels.get("nearest_support")
        sl = min(price - sl_dist, support - atr * 0.15) if support else price - sl_dist
        entry_lo, entry_hi = price - atr * 0.25, price + atr * 0.05
        r = price - sl
        tp1, tp2 = price + r * 1.6, price + r * 2.6
    elif direction == "sell":
        resist = levels.get("nearest_resistance")
        sl = max(price + sl_dist, resist + atr * 0.15) if resist else price + sl_dist
        entry_lo, entry_hi = price - atr * 0.05, price + atr * 0.25
        r = sl - price
        tp1, tp2 = price - r * 1.6, price - r * 2.6
    else:
        sl = price - sl_dist
        tp1 = price + sl_dist
        tp2 = price + sl_dist * 2
        entry_lo, entry_hi = price - atr * 0.2, price + atr * 0.2
        r = sl_dist
    rr = round(abs((tp1 - price) / r), 2) if r else None
    return {
        "entry_zone": [_round_price(entry_lo), _round_price(entry_hi)],
        "stop_loss": _round_price(sl),
        "tp1": _round_price(tp1),
        "tp2": _round_price(tp2),
        "rr": rr,
    }


def _forecast(price: float, expected: float, last_ts: int, step: int) -> list[dict]:
    pts = [{"time": last_ts, "value": price}]
    value = price
    for i in range(1, 9):
        value *= 1 + expected * (0.72 ** (i - 1))
        pts.append({"time": last_ts + step * i, "value": round(value, 8)})
    return pts


def _round_price(value: float) -> float:
    abs_v = abs(value)
    if abs_v >= 1000:
        return round(value, 2)
    if abs_v >= 50:
        return round(value, 3)
    if abs_v >= 1:
        return round(value, 5)
    return round(value, 6)


def empty_prediction(interval: str) -> dict:
    return {
        "direction": "neutral",
        "label": "خنثی",
        "probability": 50,
        "confidence": 0,
        "confidence_level": "LOW",
        "confidence_fa": "پایین",
        "target_price": 0,
        "change_pct": 0,
        "expected_move": 0,
        "horizon": HORIZON_FA.get(interval, interval),
        "interval": interval,
        "entry_zone": [0, 0],
        "stop_loss": 0,
        "tp1": 0,
        "tp2": 0,
        "risk_reward": None,
        "regime": "unknown",
        "regime_fa": "نامشخص",
        "volatility": "normal",
        "volatility_fa": "متوسط",
        "structure": {},
        "candles": [],
        "layers": {},
        "layer_scores": {},
        "ml": {},
        "session": None,
        "sentiment": {},
        "news_risk": "low",
        "news_events": [],
        "volume_note": None,
        "reasons": [],
        "risks": [],
        "summary": "داده کافی برای پیش‌بینی وجود ندارد.",
        "forecast": [],
        "ta_score": 0,
        "ml_ok": False,
        "disclaimer": "این پیش‌بینی آموزشی است و توصیه مالی نیست.",
    }
