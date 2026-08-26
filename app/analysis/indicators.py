"""Technical indicators computed with pandas/numpy (no TA-Lib)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]

    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["ema12"] = close.ewm(span=12, adjust=False).mean()
    out["ema26"] = close.ewm(span=26, adjust=False).mean()
    out["ema21"] = close.ewm(span=21, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()

    out["macd"] = out["ema12"] - out["ema26"]
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    out["rsi"] = _rsi(close, 14)
    out["cci"] = _cci(high, low, close, 20)
    out["willr"] = _williams(high, low, close, 14)
    out["roc"] = close.pct_change(12) * 100
    out["momentum"] = close.diff(10)

    std20 = close.rolling(20).std()
    out["bb_mid"] = out["sma20"]
    out["bb_upper"] = out["sma20"] + 2 * std20
    out["bb_lower"] = out["sma20"] - 2 * std20
    band = (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
    out["bb_pct"] = (close - out["bb_lower"]) / band
    out["bb_width"] = band / out["bb_mid"].replace(0, np.nan)

    out["stoch_k"] = _stoch_k(high, low, close, 14)
    out["stoch_d"] = out["stoch_k"].rolling(3).mean()

    out["atr"] = _atr(high, low, close, 14)
    adx = _adx(high, low, close, 14)
    out["adx"] = adx["adx"]
    out["plus_di"] = adx["plus_di"]
    out["minus_di"] = adx["minus_di"]

    out["tenkan"] = (high.rolling(9).max() + low.rolling(9).min()) / 2
    out["kijun"] = (high.rolling(26).max() + low.rolling(26).min()) / 2
    out["psar"] = _psar(high, low)

    typical = (high + low + close) / 3
    out["vwap"] = (typical * volume).cumsum() / volume.replace(0, np.nan).cumsum()
    out["obv"] = (np.sign(close.diff().fillna(0)) * volume).cumsum()
    out["mfi"] = _mfi(high, low, close, volume, 14)

    out["volume_sma"] = volume.rolling(20).mean()
    out["volume_ratio"] = volume / out["volume_sma"].replace(0, np.nan)
    out["range"] = high - low
    out["body"] = (close - out["open"]).abs()
    out["upper_wick"] = high - pd.concat([close, out["open"]], axis=1).max(axis=1)
    out["lower_wick"] = pd.concat([close, out["open"]], axis=1).min(axis=1) - low

    out["ret_1"] = close.pct_change(1)
    out["ret_3"] = close.pct_change(3)
    out["ret_5"] = close.pct_change(5)
    out["ret_10"] = close.pct_change(10)
    out["ret_20"] = close.pct_change(20)

    sma50 = out["sma50"].replace(0, np.nan)
    sma200 = out["sma200"].replace(0, np.nan)
    out["dist_sma50"] = (close - out["sma50"]) / sma50
    out["dist_sma200"] = (close - out["sma200"]) / sma200
    out["atr_pct"] = out["atr"] / close.replace(0, np.nan)
    return out


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _stoch_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    lowest = low.rolling(period).min()
    highest = high.rolling(period).max()
    denom = (highest - lowest).replace(0, np.nan)
    return 100 * (close - lowest) / denom


def _wma(values: np.ndarray) -> float:
    if np.any(~np.isfinite(values)):
        return np.nan
    weights = np.arange(1, len(values) + 1)
    return float(np.dot(values, weights) / weights.sum())


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def _williams(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return -100 * (hh - close) / (hh - ll).replace(0, np.nan)


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    mf = tp * volume
    delta = tp.diff()
    pos = mf.where(delta > 0, 0.0).rolling(period).sum()
    neg = mf.where(delta < 0, 0.0).rolling(period).sum()
    ratio = pos / neg.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict[str, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def _psar(high: pd.Series, low: pd.Series, step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    n = len(high)
    psar = np.zeros(n)
    if n < 3:
        return pd.Series(psar, index=high.index)
    bull = True
    af = step
    hp = float(high.iloc[0])
    lp = float(low.iloc[0])
    psar[0] = float(low.iloc[0])
    for i in range(1, n):
        h = float(high.iloc[i])
        l = float(low.iloc[i])
        prev = psar[i - 1]
        if bull:
            psar[i] = prev + af * (hp - prev)
            psar[i] = min(psar[i], float(low.iloc[i - 1]), float(low.iloc[max(0, i - 2)]))
            if l < psar[i]:
                bull = False
                psar[i] = hp
                lp = l
                af = step
            else:
                if h > hp:
                    hp = h
                    af = min(max_step, af + step)
        else:
            psar[i] = prev + af * (lp - prev)
            psar[i] = max(psar[i], float(high.iloc[i - 1]), float(high.iloc[max(0, i - 2)]))
            if h > psar[i]:
                bull = True
                psar[i] = lp
                hp = h
                af = step
            else:
                if l < lp:
                    lp = l
                    af = min(max_step, af + step)
    return pd.Series(psar, index=high.index)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def last_snapshot(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    row = df.iloc[-1]
    price = float(row["close"])
    rsi = _f(row.get("rsi"))
    macd = _f(row.get("macd"))
    macd_hist = _f(row.get("macd_hist"))
    ma50 = _f(row.get("sma50"))
    ma200 = _f(row.get("sma200"))
    bb_pct = _f(row.get("bb_pct"))
    bb_upper = _f(row.get("bb_upper"))
    bb_lower = _f(row.get("bb_lower"))

    rsi_signal, rsi_label = _rsi_signal(rsi)
    macd_signal, macd_label = _macd_signal(macd, macd_hist, _f(row.get("macd_signal")))
    ma50_signal, ma50_label = _ma_signal(price, ma50)
    ma200_signal, ma200_label = _ma_signal(price, ma200)
    boll_signal, boll_label = _boll_signal(bb_pct)

    return {
        "price": price,
        "rsi": {
            "value": round(rsi, 1) if rsi == rsi else None,
            "signal": rsi_signal,
            "label": rsi_label,
            "gauge": _clip(rsi, 0, 100),
        },
        "macd": {
            "value": round(macd, 4) if macd == macd else None,
            "hist": round(macd_hist, 4) if macd_hist == macd_hist else None,
            "signal": macd_signal,
            "label": macd_label,
            "gauge": _macd_gauge(macd_hist, price),
        },
        "ma50": {
            "value": round(ma50, 4) if ma50 == ma50 else None,
            "signal": ma50_signal,
            "label": ma50_label,
            "gauge": _ma_gauge(price, ma50),
        },
        "ma200": {
            "value": round(ma200, 4) if ma200 == ma200 else None,
            "signal": ma200_signal,
            "label": ma200_label,
            "gauge": _ma_gauge(price, ma200),
        },
        "boll": {
            "value": round(bb_pct * 100, 1) if bb_pct == bb_pct else None,
            "upper": round(bb_upper, 4) if bb_upper == bb_upper else None,
            "lower": round(bb_lower, 4) if bb_lower == bb_lower else None,
            "signal": boll_signal,
            "label": boll_label,
            "gauge": _clip((bb_pct or 0.5) * 100, 0, 100),
        },
        "stoch": {
            "k": round(_f(row.get("stoch_k")), 1),
            "d": round(_f(row.get("stoch_d")), 1),
        },
        "atr": _f(row.get("atr")),
        "volume_ratio": _f(row.get("volume_ratio")),
    }


def overlay_series(df: pd.DataFrame) -> dict:
    def series(col: str) -> list[dict]:
        if col not in df.columns:
            return []
        points = []
        for _, row in df.iterrows():
            val = row[col]
            if pd.isna(val):
                continue
            points.append({"time": int(row["time"].timestamp()), "value": float(val)})
        return points

    return {
        "sma50": series("sma50"),
        "sma200": series("sma200"),
        "ema21": series("ema21"),
        "bb_upper": series("bb_upper"),
        "bb_mid": series("bb_mid"),
        "bb_lower": series("bb_lower"),
        "rsi": series("rsi"),
        "macd": series("macd"),
        "macd_signal": series("macd_signal"),
        "macd_hist": [
            {
                "time": int(row["time"].timestamp()),
                "value": float(row["macd_hist"]),
                "color": "#22c55e" if float(row["macd_hist"]) >= 0 else "#ef4444",
            }
            for _, row in df.iterrows()
            if not pd.isna(row.get("macd_hist"))
        ],
    }


def _f(value) -> float:
    try:
        v = float(value)
        if np.isnan(v):
            return float("nan")
        return v
    except (TypeError, ValueError):
        return float("nan")


def _clip(value: float, lo: float, hi: float) -> float:
    if value != value:
        return 50.0
    return max(lo, min(hi, float(value)))


def _rsi_signal(rsi: float) -> tuple[str, str]:
    if rsi != rsi:
        return "neutral", "خنثی"
    if rsi >= 70:
        return "sell", "اشباع خرید"
    if rsi <= 30:
        return "buy", "اشباع فروش"
    if rsi >= 55:
        return "buy", "خرید"
    if rsi <= 45:
        return "sell", "فروش"
    return "neutral", "خنثی"


def _macd_signal(macd: float, hist: float, signal: float) -> tuple[str, str]:
    if hist != hist:
        return "neutral", "خنثی"
    if hist > 0 and macd > signal:
        return "buy", "خرید"
    if hist < 0 and macd < signal:
        return "sell", "فروش"
    return "neutral", "خنثی"


def _ma_signal(price: float, ma: float) -> tuple[str, str]:
    if ma != ma or not ma:
        return "neutral", "خنثی"
    if price > ma:
        return "buy", "خرید"
    if price < ma:
        return "sell", "فروش"
    return "neutral", "خنثی"


def _boll_signal(pct: float) -> tuple[str, str]:
    if pct != pct:
        return "neutral", "در محدوده"
    if pct <= 0.15:
        return "buy", "نزدیک کف"
    if pct >= 0.85:
        return "sell", "نزدیک سقف"
    return "neutral", "در محدوده"


def _macd_gauge(hist: float, price: float) -> float:
    if hist != hist or not price:
        return 50.0
    # Scale histogram relative to price into 0–100 around 50.
    scaled = 50 + (hist / price) * 8000
    return _clip(scaled, 5, 95)


def _ma_gauge(price: float, ma: float) -> float:
    if ma != ma or not ma:
        return 50.0
    dist = (price - ma) / ma
    return _clip(50 + dist * 400, 8, 92)
