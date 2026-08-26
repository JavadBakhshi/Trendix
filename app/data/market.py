"""OHLCV and ticker adapters with exchange fallbacks (Binance → Bybit → OKX)."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import httpx
import pandas as pd

from app.config import (
    CACHE_TTL_KLINES,
    CACHE_TTL_MARKETS,
    CACHE_TTL_NEWS,
    CACHE_TTL_TICKER,
    HTTP_TIMEOUT,
    KLINE_LIMIT,
)
from app.data.coins import (
    COINS,
    MACRO_ASSETS,
    gecko_ids_for,
    icon_url,
    macro_spec,
    meta_for,
    normalize_symbol,
    pack_macro,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

YAHOO_INTERVAL = {
    "5m": ("5m", "7d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h": ("60m", "6mo"),
    "1d": ("1d", "2y"),
    "1w": ("1wk", "10y"),
}


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        value, expires = item
        if time.time() > expires:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._data[key] = (value, time.time() + ttl)


def _yahoo_get_sync(url: str, params: dict[str, str]) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"yahoo http {exc.code}") from exc


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class MarketData:
    def __init__(self) -> None:
        self.source: str | None = None
        self._cache = TTLCache()
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers=HEADERS,
            follow_redirects=True,
        )
        self._gecko_cache: dict[str, dict] = {}
        self._yahoo_lock = asyncio.Lock()
        self._yahoo_chart_cache: dict[str, tuple[dict, float]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def ensure_source(self) -> str:
        if self.source:
            return self.source
        async with self._lock:
            if self.source:
                return self.source
            probes = [
                ("binance", self._probe_binance),
                ("bybit", self._probe_bybit),
                ("okx", self._probe_okx),
            ]
            for name, probe in probes:
                try:
                    await probe()
                    self.source = name
                    return name
                except Exception:
                    continue
            raise RuntimeError("هیچ منبع داده در دسترسی نیست. اتصال اینترنت را بررسی کنید.")

    async def _probe_binance(self) -> None:
        for url in (
            "https://data-api.binance.vision/api/v3/ping",
            "https://api.binance.com/api/v3/ping",
        ):
            try:
                r = await self._client.get(url)
                r.raise_for_status()
                self._binance_base = url.replace("/api/v3/ping", "")
                return
            except Exception:
                continue
        raise RuntimeError("binance down")

    async def _probe_bybit(self) -> None:
        r = await self._client.get("https://api.bybit.com/v5/market/time")
        r.raise_for_status()
        if r.json().get("retCode") not in (0, "0", None) and "time" not in str(r.json()).lower():
            data = r.json()
            if data.get("retCode") not in (0, "0"):
                raise RuntimeError("bybit error")

    async def _probe_okx(self) -> None:
        r = await self._client.get("https://www.okx.com/api/v5/public/time")
        r.raise_for_status()
        if r.json().get("code") not in ("0", 0):
            raise RuntimeError("okx error")

    async def coins(self) -> list[dict]:
        cached = self._cache.get("coins")
        if cached is not None:
            return cached
        items: list[dict] = []
        try:
            source = await self.ensure_source()
            if source == "binance":
                items = await self._binance_coins()
            elif source == "bybit":
                items = await self._bybit_coins()
            else:
                items = await self._okx_coins()
            rank = {k: i for i, k in enumerate(COINS)}
            items.sort(key=lambda c: (rank.get(c["base"], 10_000), c["base"]))
        except Exception:
            items = []
        macros = [pack_macro(spec) for spec in MACRO_ASSETS]
        macro_syms = {m["symbol"] for m in macros}
        items = macros + [c for c in items if c["symbol"] not in macro_syms]
        self._cache.set("coins", items, 300)
        return items

    async def ticker(self, symbol: str) -> dict:
        symbol = normalize_symbol(symbol)
        cached = self._cache.get(f"ticker:{symbol}")
        if cached is not None:
            return cached
        spec = macro_spec(symbol)
        if spec:
            data = await self._macro_ticker(spec)
            self._cache.set(f"ticker:{symbol}", data, CACHE_TTL_TICKER)
            return data
        source = await self.ensure_source()
        if source == "binance":
            data = await self._binance_ticker(symbol)
        elif source == "bybit":
            data = await self._bybit_ticker(symbol)
        else:
            data = await self._okx_ticker(symbol)
        gecko = await self._enrich_gecko(data["base"])
        data.update(gecko)
        self._cache.set(f"ticker:{symbol}", data, CACHE_TTL_TICKER)
        return data

    async def klines(self, symbol: str, interval: str, limit: int = KLINE_LIMIT) -> list[dict]:
        symbol = normalize_symbol(symbol)
        key = f"klines:{symbol}:{interval}:{limit}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        spec = macro_spec(symbol)
        if spec:
            if interval == "3h":
                raw = await self._macro_klines(spec, "1h", min(limit * 3, 800))
                rows = self._resample(raw, "3h")
            else:
                rows = await self._macro_klines(spec, interval, limit)
            self._cache.set(key, rows, CACHE_TTL_KLINES)
            return rows
        source = await self.ensure_source()
        if interval == "3h":
            raw = await self._fetch_klines(source, symbol, "1h", min(limit * 3, 1000))
            rows = self._resample(raw, "3h")
        else:
            rows = await self._fetch_klines(source, symbol, interval, limit)
        self._cache.set(key, rows, CACHE_TTL_KLINES)
        return rows

    async def klines_df(self, symbol: str, interval: str, limit: int = KLINE_LIMIT) -> pd.DataFrame:
        rows = await self.klines(symbol, interval, limit)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    async def performance(self, symbol: str, price: float) -> dict[str, float]:
        symbol = normalize_symbol(symbol)
        cached = self._cache.get(f"perf:{symbol}")
        if cached is not None:
            return cached

        k5, k1h, k1d = await asyncio.gather(
            self.klines(symbol, "5m", 250),
            self.klines(symbol, "1h", 200),
            self.klines(symbol, "1d", 14),
        )
        now = int(time.time())
        specs = {
            "5m": (k5, 5 * 60),
            "15m": (k5, 15 * 60),
            "30m": (k5, 30 * 60),
            "1h": (k1h, 60 * 60),
            "3h": (k1h, 3 * 60 * 60),
            "1d": (k1d, 24 * 60 * 60),
            "1w": (k1d, 7 * 24 * 60 * 60),
        }
        out: dict[str, float] = {}
        for tf, (rows, delta) in specs.items():
            past = self._price_at(rows, now - delta)
            if past and past > 0 and price > 0:
                out[tf] = round((price - past) / past * 100, 2)
            else:
                out[tf] = 0.0
        self._cache.set(f"perf:{symbol}", out, CACHE_TTL_TICKER)
        return out

    async def markets(self) -> list[dict]:
        cached = self._cache.get("markets")
        if cached is not None:
            return cached
        source = await self.ensure_source()
        if source == "binance":
            rows = await self._binance_markets()
        elif source == "bybit":
            rows = await self._bybit_markets()
        else:
            rows = await self._okx_markets()
        rows = [r for r in rows if r["quote_volume"] > 0]
        rows.sort(key=lambda r: r["quote_volume"], reverse=True)
        top = rows[:80]
        await self._enrich_markets(top)
        macros = []
        for spec in MACRO_ASSETS:
            try:
                t = await self.ticker(spec["symbol"])
                macros.append(
                    {
                        "symbol": t["symbol"],
                        "base": t["base"],
                        "quote": t["quote"],
                        "name_en": t["name_en"],
                        "name_fa": t["name_fa"],
                        "icon": t.get("icon") or t.get("image"),
                        "price": t["price"],
                        "change_24h": t["change_24h"],
                        "high_24h": t["high_24h"],
                        "low_24h": t["low_24h"],
                        "volume_24h": t.get("volume_24h") or 0,
                        "quote_volume": t.get("volume_24h") or 0,
                        "market_cap": 0.0,
                        "circulating_supply": 0.0,
                        "category": "macro",
                        "price_prefix": spec.get("price_prefix", ""),
                        "market_label": spec.get("market_label", ""),
                    }
                )
            except Exception:
                continue
        top = macros + top
        self._cache.set("markets", top, CACHE_TTL_MARKETS)
        return top

    async def news(self) -> list[dict]:
        cached = self._cache.get("news")
        if cached is not None:
            return cached
        try:
            r = await self._client.get(
                "https://min-api.cryptocompare.com/data/v2/news/",
                params={"lang": "EN", "extraParams": "cryptoanalyzer"},
            )
            r.raise_for_status()
            items = r.json().get("Data", [])[:24]
            news = [
                {
                    "id": str(n.get("id")),
                    "title": n.get("title") or "",
                    "body": (n.get("body") or "")[:280],
                    "url": n.get("url") or n.get("guid") or "",
                    "source": (n.get("source_info") or {}).get("name") or n.get("source") or "",
                    "image": n.get("imageurl") or "",
                    "time": n.get("published_on") or 0,
                    "categories": n.get("categories") or "",
                }
                for n in items
            ]
        except Exception:
            news = []
        self._cache.set("news", news, CACHE_TTL_NEWS)
        return news

    async def _macro_ticker(self, spec: dict) -> dict:
        fallback = spec.get("binance")
        if fallback:
            try:
                await self.ensure_source()
                data = await self._binance_ticker(fallback)
                packed = pack_macro(spec)
                data.update(packed)
                data["image"] = spec["icon"]
                return data
            except Exception:
                pass
        return await self._yahoo_ticker(spec)

    async def _macro_klines(self, spec: dict, interval: str, limit: int) -> list[dict]:
        fallback = spec.get("binance")
        if fallback:
            try:
                source = await self.ensure_source()
                rows = await self._fetch_klines(source, fallback, interval, limit)
                if rows:
                    return rows
            except Exception:
                pass
        rows = await self._yahoo_klines(spec, interval, limit)
        if rows:
            return rows
        raise RuntimeError(f"داده {spec['name_fa']} در دسترس نیست")

    async def _yahoo_chart(self, yahoo_symbol: str, interval: str, range_: str) -> dict:
        cache_key = f"{yahoo_symbol}:{interval}:{range_}"
        hit = self._yahoo_chart_cache.get(cache_key)
        if hit and time.time() < hit[1]:
            return hit[0]
        last_err: Exception | None = None
        async with self._yahoo_lock:
            hit = self._yahoo_chart_cache.get(cache_key)
            if hit and time.time() < hit[1]:
                return hit[0]
            for host in (
                "https://query2.finance.yahoo.com",
                "https://query1.finance.yahoo.com",
            ):
                try:
                    payload = await asyncio.to_thread(
                        _yahoo_get_sync,
                        f"{host}/v8/finance/chart/{yahoo_symbol}",
                        {"interval": interval, "range": range_, "includePrePost": "false"},
                    )
                    result = (payload.get("chart") or {}).get("result")
                    if not result:
                        raise RuntimeError("yahoo empty")
                    chart = result[0]
                    self._yahoo_chart_cache[cache_key] = (chart, time.time() + 45)
                    return chart
                except Exception as exc:
                    last_err = exc
                    continue
        raise last_err or RuntimeError("yahoo failed")

    def _yahoo_rows(self, chart: dict, limit: int) -> list[dict]:
        stamps = chart.get("timestamp") or []
        quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        rows = []
        for i, ts in enumerate(stamps):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            if o is None or h is None or low is None or c is None:
                continue
            vol = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
            rows.append(
                {
                    "time": int(ts),
                    "open": float(o),
                    "high": float(h),
                    "low": float(low),
                    "close": float(c),
                    "volume": float(vol),
                }
            )
        return rows[-limit:]

    async def _yahoo_klines(self, spec: dict, interval: str, limit: int) -> list[dict]:
        y_int, y_range = YAHOO_INTERVAL.get(interval, ("60m", "6mo"))
        last_err: Exception | None = None
        for ysym in (spec.get("yahoo"), spec.get("yahoo_alt")):
            if not ysym:
                continue
            try:
                chart = await self._yahoo_chart(ysym, y_int, y_range)
                rows = self._yahoo_rows(chart, limit)
                if rows:
                    return rows
            except Exception as exc:
                last_err = exc
                continue
        if last_err:
            raise last_err
        return []

    async def _yahoo_ticker(self, spec: dict) -> dict:
        last_err: Exception | None = None
        for ysym in (spec.get("yahoo"), spec.get("yahoo_alt")):
            if not ysym:
                continue
            for interval, range_ in (("5m", "5d"), ("1d", "3mo")):
                try:
                    chart = await self._yahoo_chart(ysym, interval, range_)
                    meta = chart.get("meta") or {}
                    rows = self._yahoo_rows(chart, 400)
                    price = _to_float(meta.get("regularMarketPrice"))
                    if not price and rows:
                        price = rows[-1]["close"]
                    if not price:
                        continue
                    prev = _to_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
                    change = ((price - prev) / prev * 100) if prev else 0.0
                    high = _to_float(meta.get("regularMarketDayHigh"))
                    low = _to_float(meta.get("regularMarketDayLow"))
                    if rows:
                        recent = [r for r in rows if r["time"] >= int(time.time()) - 26 * 3600] or rows[-80:]
                        if not high:
                            high = max(r["high"] for r in recent)
                        if not low:
                            low = min(r["low"] for r in recent)
                    packed = pack_macro(spec)
                    packed.update(
                        {
                            "price": price,
                            "change_24h": change,
                            "high_24h": high,
                            "low_24h": low,
                            "volume_24h": _to_float(meta.get("regularMarketVolume")),
                            "volume_base": _to_float(meta.get("regularMarketVolume")),
                            "market_cap": 0.0,
                            "circulating_supply": 0.0,
                            "image": spec["icon"],
                        }
                    )
                    return packed
                except Exception as exc:
                    last_err = exc
                    continue
        raise last_err or RuntimeError("yahoo ticker failed")

    async def _fetch_klines(self, source: str, symbol: str, interval: str, limit: int) -> list[dict]:
        if source == "binance":
            return await self._binance_klines(symbol, interval, limit)
        if source == "bybit":
            return await self._bybit_klines(symbol, interval, limit)
        return await self._okx_klines(symbol, interval, limit)

    def _resample(self, rows: list[dict], rule: str) -> list[dict]:
        if not rows:
            return []
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        agg = df.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        out = []
        for ts, row in agg.iterrows():
            out.append(
                {
                    "time": int(ts.timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return out

    @staticmethod
    def _price_at(rows: list[dict], ts: int) -> float | None:
        if not rows:
            return None
        chosen = None
        for row in rows:
            if row["time"] <= ts:
                chosen = row
            else:
                break
        if chosen is None:
            chosen = rows[0]
        return float(chosen["close"])

    def _base_of(self, symbol: str) -> str:
        if symbol.endswith("USDT"):
            return symbol[:-4]
        if symbol.endswith("USD"):
            return symbol[:-3]
        return symbol

    @staticmethod
    def _keep_base(base: str) -> bool:
        base = (base or "").upper()
        if not base or base in {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}:
            return False
        if base.endswith(("UP", "DOWN")):
            return False
        return True

    def _pack_coin(self, base: str) -> dict:
        meta = meta_for(base)
        return {
            "symbol": f"{base}USDT",
            "base": base,
            "quote": "USDT",
            "name_en": meta["en"],
            "name_fa": meta["fa"],
            "icon": icon_url(base),
        }

    async def _enrich_gecko(self, base: str) -> dict:
        if base in self._gecko_cache and (time.time() - self._gecko_cache[base].get("_ts", 0)) < 120:
            data = dict(self._gecko_cache[base])
            data.pop("_ts", None)
            return data
        meta = meta_for(base)
        empty = {"market_cap": 0.0, "circulating_supply": 0.0, "image": icon_url(base)}
        if not meta.get("gecko"):
            return empty
        try:
            r = await self._client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "ids": meta["gecko"]},
            )
            r.raise_for_status()
            arr = r.json()
            if not arr:
                return empty
            coin = arr[0]
            data = {
                "market_cap": _to_float(coin.get("market_cap")),
                "circulating_supply": _to_float(coin.get("circulating_supply")),
                "image": coin.get("image") or icon_url(base),
            }
            data["_ts"] = time.time()
            self._gecko_cache[base] = data
            out = dict(data)
            out.pop("_ts")
            return out
        except Exception:
            return empty

    async def _enrich_markets(self, rows: list[dict]) -> None:
        ids = gecko_ids_for([r["base"] for r in rows[:40]])
        if not ids:
            return
        try:
            r = await self._client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "ids": ",".join(ids), "per_page": 80},
            )
            r.raise_for_status()
            by_id = {c["id"]: c for c in r.json()}
        except Exception:
            return
        for row in rows:
            gid = meta_for(row["base"]).get("gecko")
            coin = by_id.get(gid) if gid else None
            if not coin:
                continue
            row["market_cap"] = _to_float(coin.get("market_cap"))
            row["circulating_supply"] = _to_float(coin.get("circulating_supply"))
            if coin.get("image"):
                row["icon"] = coin["image"]

    # ── Binance ──────────────────────────────────────────────
    async def _binance_coins(self) -> list[dict]:
        r = await self._client.get(f"{self._binance_base}/api/v3/exchangeInfo")
        r.raise_for_status()
        out = []
        for s in r.json().get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            if not self._keep_base(s.get("baseAsset")):
                continue
            out.append(self._pack_coin(s["baseAsset"]))
        return out

    async def _binance_ticker(self, symbol: str) -> dict:
        r = await self._client.get(
            f"{self._binance_base}/api/v3/ticker/24hr",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        t = r.json()
        base = self._base_of(symbol)
        meta = meta_for(base)
        return {
            "symbol": symbol,
            "base": base,
            "quote": "USDT",
            "name_en": meta["en"],
            "name_fa": meta["fa"],
            "icon": icon_url(base),
            "price": _to_float(t.get("lastPrice")),
            "change_24h": _to_float(t.get("priceChangePercent")),
            "high_24h": _to_float(t.get("highPrice")),
            "low_24h": _to_float(t.get("lowPrice")),
            "volume_24h": _to_float(t.get("quoteVolume")),
            "volume_base": _to_float(t.get("volume")),
        }

    async def _binance_klines(self, symbol: str, interval: str, limit: int) -> list[dict]:
        r = await self._client.get(
            f"{self._binance_base}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": min(limit, 1000)},
        )
        r.raise_for_status()
        rows = []
        for k in r.json():
            rows.append(
                {
                    "time": int(k[0]) // 1000,
                    "open": _to_float(k[1]),
                    "high": _to_float(k[2]),
                    "low": _to_float(k[3]),
                    "close": _to_float(k[4]),
                    "volume": _to_float(k[5]),
                }
            )
        return rows

    async def _binance_markets(self) -> list[dict]:
        r = await self._client.get(f"{self._binance_base}/api/v3/ticker/24hr")
        r.raise_for_status()
        out = []
        for t in r.json():
            symbol = t.get("symbol") or ""
            if not symbol.endswith("USDT"):
                continue
            base = symbol[:-4]
            if not self._keep_base(base):
                continue
            meta = meta_for(base)
            out.append(
                {
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "name_en": meta["en"],
                    "name_fa": meta["fa"],
                    "icon": icon_url(base),
                    "price": _to_float(t.get("lastPrice")),
                    "change_24h": _to_float(t.get("priceChangePercent")),
                    "high_24h": _to_float(t.get("highPrice")),
                    "low_24h": _to_float(t.get("lowPrice")),
                    "volume_24h": _to_float(t.get("quoteVolume")),
                    "quote_volume": _to_float(t.get("quoteVolume")),
                    "market_cap": 0.0,
                    "circulating_supply": 0.0,
                }
            )
        return out

    # ── Bybit ────────────────────────────────────────────────
    _BYBIT_INTERVAL = {
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "1d": "D",
        "1w": "W",
    }

    async def _bybit_coins(self) -> list[dict]:
        r = await self._client.get(
            "https://api.bybit.com/v5/market/instruments-info",
            params={"category": "spot", "limit": 1000},
        )
        r.raise_for_status()
        out = []
        for s in r.json().get("result", {}).get("list", []):
            if s.get("quoteCoin") != "USDT" or s.get("status") != "Trading":
                continue
            base = s.get("baseCoin") or ""
            if not self._keep_base(base):
                continue
            out.append(self._pack_coin(base))
        return out

    async def _bybit_ticker(self, symbol: str) -> dict:
        r = await self._client.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot", "symbol": symbol},
        )
        r.raise_for_status()
        items = r.json().get("result", {}).get("list", [])
        if not items:
            raise RuntimeError("ticker not found")
        t = items[0]
        base = self._base_of(symbol)
        meta = meta_for(base)
        return {
            "symbol": symbol,
            "base": base,
            "quote": "USDT",
            "name_en": meta["en"],
            "name_fa": meta["fa"],
            "icon": icon_url(base),
            "price": _to_float(t.get("lastPrice")),
            "change_24h": _to_float(t.get("price24hPcnt")) * 100,
            "high_24h": _to_float(t.get("highPrice24h")),
            "low_24h": _to_float(t.get("lowPrice24h")),
            "volume_24h": _to_float(t.get("turnover24h")),
            "volume_base": _to_float(t.get("volume24h")),
        }

    async def _bybit_klines(self, symbol: str, interval: str, limit: int) -> list[dict]:
        iv = self._BYBIT_INTERVAL.get(interval, "60")
        r = await self._client.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "spot",
                "symbol": symbol,
                "interval": iv,
                "limit": min(limit, 1000),
            },
        )
        r.raise_for_status()
        items = r.json().get("result", {}).get("list", [])
        rows = []
        for k in reversed(items):
            rows.append(
                {
                    "time": int(k[0]) // 1000,
                    "open": _to_float(k[1]),
                    "high": _to_float(k[2]),
                    "low": _to_float(k[3]),
                    "close": _to_float(k[4]),
                    "volume": _to_float(k[5]),
                }
            )
        return rows

    async def _bybit_markets(self) -> list[dict]:
        r = await self._client.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot"},
        )
        r.raise_for_status()
        out = []
        for t in r.json().get("result", {}).get("list", []):
            symbol = t.get("symbol") or ""
            if not symbol.endswith("USDT"):
                continue
            base = symbol[:-4]
            if not self._keep_base(base):
                continue
            meta = meta_for(base)
            out.append(
                {
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "name_en": meta["en"],
                    "name_fa": meta["fa"],
                    "icon": icon_url(base),
                    "price": _to_float(t.get("lastPrice")),
                    "change_24h": _to_float(t.get("price24hPcnt")) * 100,
                    "high_24h": _to_float(t.get("highPrice24h")),
                    "low_24h": _to_float(t.get("lowPrice24h")),
                    "volume_24h": _to_float(t.get("turnover24h")),
                    "quote_volume": _to_float(t.get("turnover24h")),
                    "market_cap": 0.0,
                    "circulating_supply": 0.0,
                }
            )
        return out

    # ── OKX ──────────────────────────────────────────────────
    _OKX_BAR = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "1d": "1D",
        "1w": "1W",
    }

    def _okx_inst(self, symbol: str) -> str:
        base = self._base_of(symbol)
        return f"{base}-USDT"

    async def _okx_coins(self) -> list[dict]:
        r = await self._client.get(
            "https://www.okx.com/api/v5/public/instruments",
            params={"instType": "SPOT"},
        )
        r.raise_for_status()
        out = []
        for s in r.json().get("data", []):
            if s.get("quoteCcy") != "USDT" or s.get("state") != "live":
                continue
            base = s.get("baseCcy") or ""
            if not self._keep_base(base):
                continue
            out.append(self._pack_coin(base))
        return out

    async def _okx_ticker(self, symbol: str) -> dict:
        r = await self._client.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": self._okx_inst(symbol)},
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        if not items:
            raise RuntimeError("ticker not found")
        t = items[0]
        last = _to_float(t.get("last"))
        open24 = _to_float(t.get("open24h"))
        change = ((last - open24) / open24 * 100) if open24 else 0.0
        base = self._base_of(symbol)
        meta = meta_for(base)
        return {
            "symbol": symbol,
            "base": base,
            "quote": "USDT",
            "name_en": meta["en"],
            "name_fa": meta["fa"],
            "icon": icon_url(base),
            "price": last,
            "change_24h": change,
            "high_24h": _to_float(t.get("high24h")),
            "low_24h": _to_float(t.get("low24h")),
            "volume_24h": _to_float(t.get("volCcy24h")),
            "volume_base": _to_float(t.get("vol24h")),
        }

    async def _okx_klines(self, symbol: str, interval: str, limit: int) -> list[dict]:
        r = await self._client.get(
            "https://www.okx.com/api/v5/market/candles",
            params={
                "instId": self._okx_inst(symbol),
                "bar": self._OKX_BAR.get(interval, "1H"),
                "limit": str(min(limit, 300)),
            },
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        rows = []
        for k in reversed(items):
            rows.append(
                {
                    "time": int(k[0]) // 1000,
                    "open": _to_float(k[1]),
                    "high": _to_float(k[2]),
                    "low": _to_float(k[3]),
                    "close": _to_float(k[4]),
                    "volume": _to_float(k[5]),
                }
            )
        return rows

    async def _okx_markets(self) -> list[dict]:
        r = await self._client.get(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SPOT"},
        )
        r.raise_for_status()
        out = []
        for t in r.json().get("data", []):
            inst = t.get("instId") or ""
            if not inst.endswith("-USDT"):
                continue
            base = inst.split("-")[0]
            if not self._keep_base(base):
                continue
            last = _to_float(t.get("last"))
            open24 = _to_float(t.get("open24h"))
            change = ((last - open24) / open24 * 100) if open24 else 0.0
            meta = meta_for(base)
            vol = _to_float(t.get("volCcy24h"))
            out.append(
                {
                    "symbol": f"{base}USDT",
                    "base": base,
                    "quote": "USDT",
                    "name_en": meta["en"],
                    "name_fa": meta["fa"],
                    "icon": icon_url(base),
                    "price": last,
                    "change_24h": change,
                    "high_24h": _to_float(t.get("high24h")),
                    "low_24h": _to_float(t.get("low24h")),
                    "volume_24h": vol,
                    "quote_volume": vol,
                    "market_cap": 0.0,
                    "circulating_supply": 0.0,
                }
            )
        return out


market = MarketData()
