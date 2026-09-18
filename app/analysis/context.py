"""External context: economic calendar risk and market sentiment."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

_CACHE: dict[str, tuple[object, float]] = {}


def _get(key: str, ttl: float):
    item = _CACHE.get(key)
    if not item:
        return None
    val, exp = item
    if time.time() > exp:
        return None
    return val


def _set(key: str, val, ttl: float) -> None:
    _CACHE[key] = (val, time.time() + ttl)


async def fear_greed(client: httpx.AsyncClient) -> dict:
    cached = _get("fng", 600)
    if cached is not None:
        return cached
    empty = {"value": None, "label": None, "score": 0.0, "reasons": []}
    try:
        r = await client.get("https://api.alternative.me/fng/", params={"limit": 1}, timeout=8)
        r.raise_for_status()
        row = (r.json().get("data") or [{}])[0]
        value = int(row.get("value") or 0)
        label = row.get("value_classification") or ""
        # extreme fear can be contrarian buy for crypto; for FX treat as risk-off (USD/JPY, gold)
        score = 0.0
        if value <= 25:
            score = 8
            text = f"ترس بازار (Fear & Greed={value}) — تمایل به دارایی امن / برگشت"
        elif value >= 75:
            score = -8
            text = f"طمع بازار (Fear & Greed={value}) — احتیاط برای خرید هیجانی"
        else:
            text = f"احساسات بازار متعادل است ({value})"
        out = {
            "value": value,
            "label": label,
            "score": score,
            "reasons": [{"id": "sentiment", "text": text, "bias": "buy" if score > 0 else "sell" if score < 0 else "neutral"}],
        }
        _set("fng", out, 600)
        return out
    except Exception:
        _set("fng", empty, 120)
        return empty


async def news_risk(client: httpx.AsyncClient, symbol: str) -> dict:
    cached = _get("cal", 180)
    events = cached
    if events is None:
        events = await _calendar(client)
        _set("cal", events, 180)
    now = datetime.now(timezone.utc)
    related = _currencies_for(symbol)
    upcoming = []
    for ev in events:
        dt = ev.get("dt")
        if not dt:
            continue
        minutes = (dt - now).total_seconds() / 60
        if -30 <= minutes <= 180 and ev.get("impact") in {"High", "Medium"}:
            if not related or ev.get("country") in related or ev.get("currency") in related:
                upcoming.append({**ev, "minutes": round(minutes)})
    upcoming.sort(key=lambda e: abs(e["minutes"]))
    high = [e for e in upcoming if e.get("impact") == "High" and 0 <= e["minutes"] <= 90]
    score = 0.0
    if high:
        score = -18
        text = f"خبر پرریسک نزدیک است: {high[0]['title']} تا {high[0]['minutes']} دقیقه"
        level = "high"
    elif upcoming:
        score = -8
        text = f"رویداد اقتصادی در راه است: {upcoming[0]['title']}"
        level = "medium"
    else:
        text = "خبر پرریسکِ نزدیک برای این نماد دیده نشد"
        level = "low"
    return {
        "level": level,
        "score": score,
        "events": [
            {
                "title": e.get("title"),
                "impact": e.get("impact"),
                "minutes": e.get("minutes"),
                "currency": e.get("currency") or e.get("country"),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
            }
            for e in upcoming[:6]
        ],
        "reasons": [{"id": "news", "text": text, "bias": "neutral"}],
    }


async def _calendar(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=8)
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return []
    out = []
    for row in rows[:200]:
        try:
            dt = datetime.fromisoformat(str(row.get("date") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        out.append(
            {
                "title": row.get("title") or row.get("event") or "",
                "country": row.get("country") or "",
                "currency": row.get("currency") or row.get("country") or "",
                "impact": row.get("impact") or "",
                "forecast": row.get("forecast"),
                "previous": row.get("previous"),
                "actual": row.get("actual"),
                "dt": dt,
            }
        )
    return out


def _currencies_for(symbol: str) -> set[str]:
    s = symbol.upper()
    mapping = {
        "EURUSD": {"EUR", "USD", "EMU", "United States", "European Monetary Union"},
        "GBPUSD": {"GBP", "USD", "United Kingdom", "United States"},
        "USDJPY": {"USD", "JPY", "United States", "Japan"},
        "AUDUSD": {"AUD", "USD", "Australia", "United States"},
        "USDCAD": {"USD", "CAD", "United States", "Canada"},
        "USDCHF": {"USD", "CHF", "United States", "Switzerland"},
        "NZDUSD": {"NZD", "USD", "New Zealand", "United States"},
        "EURJPY": {"EUR", "JPY", "EMU", "Japan", "European Monetary Union"},
        "GBPJPY": {"GBP", "JPY", "United Kingdom", "Japan"},
        "EURGBP": {"EUR", "GBP", "EMU", "United Kingdom", "European Monetary Union"},
        "DXY": {"USD", "United States"},
        "XAUUSD": {"USD", "United States"},
        "BTCUSDT": {"USD", "United States"},
        "ETHUSDT": {"USD", "United States"},
    }
    if s in mapping:
        return mapping[s]
    if s.endswith("USDT") or s.endswith("USD"):
        return {"USD", "United States"}
    return set()
