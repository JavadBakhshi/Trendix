"""Walk-forward test of the core signal with costs, IS/OOS split, and full metrics."""

from __future__ import annotations

from app.analysis.evidence import evaluate
from app.config import HORIZON_FA


def run_backtest(df, interval: str, symbol: str = "BTCUSDT") -> dict:
    ev = evaluate(df, interval, symbol)
    if not ev.get("ok"):
        return {"ok": False, "error": ev.get("verdict") or "کندل تاریخی کافی نیست"}
    oos = ev["out_of_sample"]
    ins = ev["in_sample"]
    all_s = ev["all"]
    costs = ev["costs"]
    return {
        "ok": True,
        "interval": interval,
        "symbol": symbol,
        "horizon": HORIZON_FA.get(interval, interval),
        "has_edge": ev["has_edge"],
        "retired": ev["retired"],
        "verdict": ev["verdict"],
        "costs": costs,
        "stats": all_s,
        "in_sample": ins,
        "out_of_sample": oos,
        "walk_forward": ev["walk_forward"],
        "regime_breakdown": ev["regime_breakdown"],
        "equity": _equity_from_trades(ev["trades"]),
        "trades": ev["trades"],
        "disclaimer": (
            f"هزینه یک‌طرفه حدود {costs.get('one_way_bps', 0):.1f}bps "
            f"(اسپرد+کمیسیون+لغزش) روی {costs.get('class')} اعمال شده. "
            "لبه فقط وقتی اعلام می‌شود که خارج از نمونه پس از هزینه مثبت باشد. سود آینده تضمین نیست."
        ),
    }


def _equity_from_trades(trades: list[dict]) -> list[float]:
    total = 0.0
    out = []
    for t in trades:
        total += float(t.get("pnl_r") or 0)
        out.append(round(total, 2))
    return out
