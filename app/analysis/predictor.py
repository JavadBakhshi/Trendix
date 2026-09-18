"""Orchestrate indicators, ensemble prediction, and chart payloads."""

from __future__ import annotations

import pandas as pd

from app.analysis.ensemble import combine, empty_prediction
from app.analysis.indicators import add_indicators, last_snapshot, overlay_series


def analyze(
    df: pd.DataFrame,
    interval: str,
    symbol: str = "BTCUSDT",
    volume_source: str | None = None,
    mtf: dict | None = None,
    sentiment: dict | None = None,
    news: dict | None = None,
) -> dict:
    work = add_indicators(df)
    pred = combine(
        work,
        interval,
        symbol,
        volume_source,
        mtf=mtf,
        sentiment=sentiment,
        news=news,
    )
    return {
        "indicators": last_snapshot(work),
        "prediction": pred,
        "overlays": overlay_series(work),
        "candles": _candles(work),
        "volume": _volume(work),
    }


def predict(
    df: pd.DataFrame,
    interval: str,
    symbol: str = "BTCUSDT",
    mtf: dict | None = None,
    news: dict | None = None,
    sentiment: dict | None = None,
) -> dict:
    if df.empty:
        return empty_prediction(interval)
    work = df if "rsi" in df.columns else add_indicators(df)
    return combine(work, interval, symbol, None, mtf=mtf, sentiment=sentiment, news=news)


def _candles(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "time": int(row["time"].timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
    return out


def _volume(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        color = "#22c55e66" if float(row["close"]) >= float(row["open"]) else "#ef444466"
        out.append({"time": int(row["time"].timestamp()), "value": float(row["volume"]), "color": color})
    return out
