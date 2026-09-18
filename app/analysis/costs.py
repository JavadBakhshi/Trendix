"""Realistic trading-cost assumptions by asset class. Conservative on purpose."""

from __future__ import annotations

from app.config import COST_BPS


def asset_class(symbol: str) -> str:
    s = (symbol or "").upper()
    if s in {"XAUUSD", "XAUUSDT", "XAU", "GOLD"}:
        return "gold"
    if s in {"DXY", "DXYUSD", "USDX"}:
        return "index"
    if s in {
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
        "EURJPY", "GBPJPY", "EURGBP", "EURCHF", "AUDJPY", "CADJPY",
    }:
        return "fx"
    if s.endswith("USDT") or s.endswith("USDC"):
        return "crypto"
    if len(s) == 6 and s.isalpha():
        return "fx"
    return "crypto"


def market_name(symbol: str) -> str:
    cls = asset_class(symbol)
    return {
        "crypto": "Cryptocurrency",
        "fx": "Forex",
        "gold": "Metals",
        "index": "Index",
    }[cls]


def cost_spec(symbol: str) -> dict:
    spec = dict(COST_BPS[asset_class(symbol)])
    spec["class"] = asset_class(symbol)
    spec["one_way_bps"] = spec["spread_bps"] / 2 + spec["commission_bps"] + spec["slippage_bps"]
    spec["round_trip_bps"] = spec["one_way_bps"] * 2
    return spec


def one_way_frac(symbol: str, stress: float = 1.0) -> float:
    """One-way cost as fraction of price. Optional stress > 1 for conservative edge tests."""
    return cost_spec(symbol)["one_way_bps"] / 10_000.0 * max(1.0, float(stress or 1.0))
