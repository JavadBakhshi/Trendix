"""Regime, volume, volatility, sessions, and statistical layers."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd


def analyze_regime(df: pd.DataFrame) -> dict:
    row = df.iloc[-1]
    adx = _f(row.get("adx"))
    bb_width = _f(row.get("bb_width"))
    atr_pct = _f(row.get("atr_pct"))
    plus_di = _f(row.get("plus_di"))
    minus_di = _f(row.get("minus_di"))
    widths = df["bb_width"].dropna() if "bb_width" in df.columns else pd.Series(dtype=float)
    atrs = df["atr_pct"].dropna() if "atr_pct" in df.columns else pd.Series(dtype=float)
    bb_pctile = float((widths < bb_width).mean() * 100) if len(widths) > 10 and bb_width == bb_width else 50
    atr_pctile = float((atrs < atr_pct).mean() * 100) if len(atrs) > 10 and atr_pct == atr_pct else 50
    rets = df["close"].pct_change().dropna()
    ac = float(rets.tail(60).autocorr(lag=1) or 0) if len(rets) > 20 else 0.0
    bull = plus_di == plus_di and minus_di == minus_di and plus_di > minus_di
    bear = plus_di == plus_di and minus_di == minus_di and minus_di > plus_di

    if adx == adx and adx >= 28 and bull:
        regime, family, regime_fa = "strong_bull", "trending", "روند صعودی قوی"
    elif adx == adx and adx >= 28 and bear:
        regime, family, regime_fa = "strong_bear", "trending", "روند نزولی قوی"
    elif adx == adx and adx >= 18:
        regime, family, regime_fa = "weak_trend", "trending", "روند ضعیف"
    elif bb_pctile <= 22:
        regime, family, regime_fa = "compression", "compression", "فشردگی / آماده شکست"
    elif ac < -0.08:
        regime, family, regime_fa = "mean_reversion", "ranging", "محیط بازگشت به میانگین"
    else:
        regime, family, regime_fa = "range", "ranging", "رنج"

    if atr_pctile >= 80:
        vol_reg, vol_fa = "high", "بالا"
    elif atr_pctile <= 25:
        vol_reg, vol_fa = "low", "پایین"
    else:
        vol_reg, vol_fa = "normal", "متوسط"

    direction = "up" if bull else "down" if bear else "sideways"
    score = 0.0
    if regime == "strong_bull":
        score = 22
    elif regime == "strong_bear":
        score = -22
    elif regime == "weak_trend":
        score = 8 if direction == "up" else -8 if direction == "down" else 0
    return {
        "regime": regime,
        "regime_fa": regime_fa,
        "family": family,
        "volatility": vol_reg,
        "volatility_fa": vol_fa,
        "adx": None if adx != adx else round(adx, 1),
        "bb_width_percentile": round(bb_pctile, 1),
        "atr_percentile": round(atr_pctile, 1),
        "direction": direction,
        "autocorr": round(ac, 3),
        "score": score,
        "reasons": [
            {"id": "regime", "text": f"رژیم بازار: {regime_fa} · نوسان {vol_fa}", "bias": "buy" if score > 0 else "sell" if score < 0 else "neutral"}
        ],
    }


def analyze_volume(df: pd.DataFrame, source: str | None) -> dict:
    row = df.iloc[-1]
    vr = _f(row.get("volume_ratio"))
    ret = _f(row.get("ret_1"))
    obv = df["obv"] if "obv" in df.columns else None
    score = 0.0
    reasons = []
    note = "حجم صرافی/تیک‌والیوم است نه حجم متمرکز کل بازار فارکس."
    if source:
        note = f"منبع حجم: {source}. در فارکس حجم واقعی متمرکز نیست."
    if vr == vr:
        if vr >= 1.6 and ret == ret:
            score += 14 if ret > 0 else -14
            reasons.append({"id": "vol_spike", "text": "اسپایک حجم حرکت قیمت را تأیید می‌کند", "bias": "buy" if ret > 0 else "sell"})
        elif vr < 0.7:
            reasons.append({"id": "vol_dry", "text": "حجم ضعیف است؛ احتمال حرکت کاذب بیشتر است", "bias": "neutral"})
    if obv is not None and len(obv.dropna()) > 20:
        obv_slope = float(obv.dropna().iloc[-1] - obv.dropna().iloc[-15])
        px_slope = float(df["close"].iloc[-1] - df["close"].iloc[-15])
        if obv_slope > 0 and px_slope < 0:
            score += 8
            reasons.append({"id": "obv_div", "text": "واگرایی مثبت حجم (OBV بالا، قیمت ضعیف)", "bias": "buy"})
        elif obv_slope < 0 and px_slope > 0:
            score -= 8
            reasons.append({"id": "obv_div", "text": "واگرایی منفی حجم (OBV پایین، قیمت قوی)", "bias": "sell"})
    poc = _poc(df)
    return {
        "score": float(np.clip(score, -100, 100)),
        "volume_ratio": None if vr != vr else round(vr, 2),
        "source_note": note,
        "poc": poc,
        "reasons": reasons or [{"id": "volume", "text": note, "bias": "neutral"}],
    }


def _poc(df: pd.DataFrame) -> float | None:
    if len(df) < 20:
        return None
    prices = ((df["high"] + df["low"] + df["close"]) / 3).tail(80)
    vols = df["volume"].tail(80)
    if vols.sum() <= 0:
        return None
    bins = np.linspace(float(prices.min()), float(prices.max()), 16)
    idx = np.clip(np.digitize(prices, bins) - 1, 0, 14)
    acc = np.zeros(15)
    for i, v in zip(idx, vols):
        acc[i] += float(v)
    return float((bins[int(acc.argmax())] + bins[min(int(acc.argmax()) + 1, 14)]) / 2)


def analyze_stats(df: pd.DataFrame) -> dict:
    rets = df["close"].pct_change().dropna()
    if len(rets) < 40:
        return {"score": 0.0, "zscore": None, "style": "unknown", "hit_rate": None, "reasons": []}
    mu, sd = float(rets.mean()), float(rets.std() or 1e-9)
    last = float(rets.iloc[-1])
    z = (last - mu) / sd
    # autocorrelation of returns: >0 momentum persistence, <0 mean reversion
    ac = float(rets.autocorr(lag=1) or 0)
    window = rets.tail(80)
    # conditional: after similar z, next return sign
    nxt = rets.shift(-1)
    similar = (rets.abs() - abs(z) * sd).abs()  # dummy
    # simpler: if z extreme and ac negative -> fade
    score = 0.0
    style = "momentum" if ac > 0.08 else "mean_reversion" if ac < -0.08 else "mixed"
    if style == "mean_reversion":
        if z <= -1.4:
            score += 16
        elif z >= 1.4:
            score -= 16
    else:
        if last > 0:
            score += 10
        elif last < 0:
            score -= 10
    # walk-forward directional hit rate of last-bar sign persistence
    persist = (np.sign(rets) == np.sign(rets.shift(1))).tail(60).mean()
    hit = float(persist) if persist == persist else None
    reasons = [
        {
            "id": "stats",
            "text": f"آمار: Z={z:.2f} · سبک { 'مومنتوم' if style=='momentum' else 'بازگشت به میانگین' if style=='mean_reversion' else 'ترکیبی'}",
            "bias": "buy" if score > 0 else "sell" if score < 0 else "neutral",
        }
    ]
    return {
        "score": float(np.clip(score, -100, 100)),
        "zscore": round(z, 2),
        "autocorr": round(ac, 3),
        "style": style,
        "hit_rate": None if hit is None else round(hit * 100, 1),
        "reasons": reasons,
    }


def analyze_session(interval: str, symbol: str) -> dict:
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 8:
        session, session_fa = "asia", "آسیا"
    elif 8 <= hour < 13:
        session, session_fa = "london", "لندن"
    elif 13 <= hour < 16:
        session, session_fa = "overlap", "هم‌پوشانی لندن/نیویورک"
    elif 16 <= hour < 21:
        session, session_fa = "newyork", "نیویورک"
    else:
        session, session_fa = "off", "بعد از سشن آمریکا"
    # Forex majors prefer London/NY; crypto is 24h
    is_fx = symbol in {"EURUSD", "DXY", "XAUUSD", "GBPUSD", "USDJPY"}
    score = 0.0
    if is_fx and session in {"london", "overlap", "newyork"}:
        score = 6
        text = f"سشن فعال: {session_fa} — نقدینگی برای فارکس مناسب‌تر است"
    elif is_fx and session in {"asia", "off"}:
        score = -4
        text = f"سشن {session_fa}: برای فارکس معمولاً نوسان و نقدینگی کمتر است"
    else:
        text = f"سشن فعلی (UTC): {session_fa}"
    weekday = datetime.now(timezone.utc).strftime("%A")
    return {
        "session": session,
        "session_fa": session_fa,
        "hour_utc": hour,
        "weekday": weekday,
        "score": score,
        "reasons": [{"id": "session", "text": text, "bias": "neutral"}],
    }


def _f(value) -> float:
    try:
        v = float(value)
        return v
    except (TypeError, ValueError):
        return float("nan")
