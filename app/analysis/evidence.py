"""Causal walk-forward test of the core signal. Confidence comes from this, not formulas."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.costs import cost_spec, one_way_frac
from app.analysis.indicators import add_indicators
from app.config import (
    ATR_STOP_MULT,
    HOLD_BARS,
    MAX_CALIBRATED_PROB,
    MIN_EXPECTANCY_R,
    MIN_OOS_TRADES,
    MIN_PROFIT_FACTOR,
    MIN_RR,
    TIMEFRAMES,
)

_CACHE: dict = {}

BARS_PER_YEAR = {
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "3h": 365 * 8,
    "1d": 252,
    "1w": 52,
}

STRATEGY_FA = {
    "trend_follow": "دنبال‌کردن روند",
    "mean_reversion": "بازگشت به میانگین",
    "breakout": "شکست فشردگی",
    "none": "بدون ستاپ معتبر",
}

REGIME_FA = {
    "strong_bull": "روند صعودی قوی",
    "strong_bear": "روند نزولی قوی",
    "weak_trend": "روند ضعیف",
    "range": "رنج",
    "compression": "فشردگی / آماده شکست",
    "mean_reversion": "محیط بازگشت به میانگین",
    "breakout": "محیط شکست",
    "high_vol": "نوسان بالا",
    "unknown": "نامشخص",
}


def evaluate(df: pd.DataFrame, interval: str, symbol: str = "BTCUSDT") -> dict:
    """Simulate the core rule on history. Last bar is not used as a completed trade."""
    if df is None or df.empty or len(df) < 100:
        return _empty_evidence(interval, symbol, "کندل تاریخی کافی نیست")
    last_t = df["time"].iloc[-1] if "time" in df.columns else None
    cache_key = (symbol, interval, len(df), str(last_t))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    work = df if "atr" in df.columns else add_indicators(df)
    trades = _simulate(work, interval, symbol)
    n = len(work)
    split = int(n * 0.60)
    is_trades = [t for t in trades if t["bar"] < split]
    oos_trades = [t for t in trades if t["bar"] >= split]
    folds = _walk_forward(trades, n, interval)
    is_stats = summarize(is_trades, split, interval)
    oos_stats = summarize(oos_trades, n - split, interval)
    all_stats = summarize(trades, n, interval)
    costs = cost_spec(symbol)
    strategy_oos = _strategy_stats(oos_trades, n - split, interval)
    strategy_is = _strategy_stats(is_trades, split, interval)
    last_i = n - 1
    core = core_at(work, last_i)
    strat = core.get("strategy") or "none"
    # Edge is judged on the strategy that would trade now (not the blended book).
    if strat != "none" and strat in strategy_oos:
        gate_oos = strategy_oos[strat]
        gate_is = strategy_is.get(strat) or _empty_stats()
        retired, has_edge, why = _verdict(gate_is, gate_oos, strategy=strat)
        oos_for_prob = [t for t in oos_trades if t.get("strategy") == strat] or oos_trades
        active_oos = gate_oos
    else:
        book_retired, book_edge, book_why = _verdict(is_stats, oos_stats)
        best = _best_strategy(strategy_oos)
        any_edge = any(bool(s.get("has_edge")) for s in strategy_oos.values())
        has_edge = bool(any_edge or book_edge)
        retired = not has_edge
        if best:
            note = "" if best.get("has_edge") else " — هنوز برای تأیید لبه نمونه کافی نیست"
            why = (
                f"الان ستاپ فعال نیست. نزدیک‌ترین نتیجه تاریخی: {STRATEGY_FA.get(best['strategy'], best['strategy'])} "
                f"(OOS EV {float(best.get('expectancy') or 0):+.2f}R، {int(best.get('trades') or 0)} معامله{note})"
            )
        else:
            why = book_why
        oos_for_prob = oos_trades
        active_oos = oos_stats
    p_buy, n_buy = calibrated_prob(oos_for_prob or trades, "buy")
    p_sell, n_sell = calibrated_prob(oos_for_prob or trades, "sell")
    side = core["side"]
    p_side = p_buy if side == "buy" else p_sell if side == "sell" else 0.5
    result = {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "costs": costs,
        "trades": trades[-24:],
        "trade_count": len(trades),
        "all": all_stats,
        "in_sample": is_stats,
        "out_of_sample": active_oos,
        "book_oos": oos_stats,
        "strategy_oos": strategy_oos,
        "walk_forward": folds,
        "has_edge": has_edge,
        "retired": retired,
        "verdict": why,
        "core": core,
        "p_buy": p_buy,
        "p_sell": p_sell,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "calibrated_p": p_side,
        "regime_breakdown": _regime_breakdown(oos_trades or trades),
        "best_strategy": _best_strategy(strategy_oos),
    }
    if len(_CACHE) > 80:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result


def core_at(df: pd.DataFrame, i: int) -> dict:
    """Causal setup at bar i. Returns side buy/sell/wait plus strategy and regime."""
    if i < 40 or i >= len(df):
        return {"side": "wait", "score": 0.0, "regime": "unknown", "family": "ranging", "strategy": "none", "extended": False}
    row = df.iloc[i]
    prev = df.iloc[i - 1] if i > 0 else row
    price = _f(row.get("close"))
    ema50 = _f(row.get("ema50"))
    rsi = _f(row.get("rsi"))
    macd_h = _f(row.get("macd_hist"))
    prev_macd = _f(prev.get("macd_hist"))
    adx = _f(row.get("adx"))
    prev_adx = _f(prev.get("adx"))
    plus_di = _f(row.get("plus_di"))
    minus_di = _f(row.get("minus_di"))
    bb_pct = _f(row.get("bb_pct"))
    bb_width = _f(row.get("bb_width"))
    vr = _f(row.get("volume_ratio"))
    atr = _f(row.get("atr"))
    widths = df["bb_width"].iloc[max(0, i - 80) : i + 1].dropna()
    bb_pctile = float((widths < bb_width).mean() * 100) if len(widths) > 10 and bb_width == bb_width else 50.0
    start = max(0, i - 20)
    prior_high = float(df["high"].iloc[start:i].max()) if i > start else price
    prior_low = float(df["low"].iloc[start:i].min()) if i > start else price
    rets = df["close"].iloc[max(0, i - 60) : i + 1].pct_change().dropna()
    ac = float(rets.autocorr(lag=1) or 0) if len(rets) > 12 else 0.0

    bull = plus_di == plus_di and minus_di == minus_di and plus_di > minus_di
    bear = plus_di == plus_di and minus_di == minus_di and minus_di > plus_di
    if adx == adx and adx >= 28 and bull:
        regime, family = "strong_bull", "trending"
    elif adx == adx and adx >= 28 and bear:
        regime, family = "strong_bear", "trending"
    elif adx == adx and adx >= 20:
        regime, family = "weak_trend", "trending"
    elif bb_pctile <= 22:
        regime, family = "compression", "compression"
    elif ac < -0.08:
        regime, family = "mean_reversion", "ranging"
    else:
        regime, family = "range", "ranging"

    side = "wait"
    strategy = "none"
    score = 0.0
    # Fresh trend entries only: pullback to EMA or MACD/ADX turn — not every bar in a trend.
    near_ema = ema50 == ema50 and atr == atr and atr > 0 and abs(price - ema50) <= atr * 1.35
    macd_turn_up = macd_h == macd_h and prev_macd == prev_macd and prev_macd <= 0 < macd_h
    macd_turn_dn = macd_h == macd_h and prev_macd == prev_macd and prev_macd >= 0 > macd_h
    adx_rising = adx == adx and prev_adx == prev_adx and adx >= 22 and adx >= prev_adx
    if family == "trending" and regime != "weak_trend":
        long_ok = (
            bull and macd_h == macd_h and macd_h > 0 and ema50 == ema50 and price > ema50
            and not (rsi == rsi and rsi >= 72)
            and (near_ema or macd_turn_up)
            and adx_rising
        )
        short_ok = (
            bear and macd_h == macd_h and macd_h < 0 and ema50 == ema50 and price < ema50
            and not (rsi == rsi and rsi <= 28)
            and (near_ema or macd_turn_dn)
            and adx_rising
        )
        if long_ok:
            side, strategy, score = "buy", "trend_follow", min(48.0, 20 + (adx - 20) * 0.85)
        elif short_ok:
            side, strategy, score = "sell", "trend_follow", min(48.0, 20 + (adx - 20) * 0.85)
    elif family == "ranging":
        if bb_pct == bb_pct and rsi == rsi and bb_pct <= 0.15 and rsi <= 32:
            side, strategy, score = "buy", "mean_reversion", 24 + (32 - rsi) * 0.45
        elif bb_pct == bb_pct and rsi == rsi and bb_pct >= 0.85 and rsi >= 68:
            side, strategy, score = "sell", "mean_reversion", 24 + (rsi - 68) * 0.45
    else:
        # Compression breakout: close beyond 20-bar range with volume confirmation.
        if vr == vr and vr >= 1.35 and price > prior_high and (macd_h == macd_h and macd_h > 0):
            side, strategy, score = "buy", "breakout", 26
            regime = "breakout"
        elif vr == vr and vr >= 1.35 and price < prior_low and (macd_h == macd_h and macd_h < 0):
            side, strategy, score = "sell", "breakout", 26
            regime = "breakout"

    extended = False
    if side == "buy" and strategy == "trend_follow" and ((bb_pct == bb_pct and bb_pct > 0.92) or (rsi == rsi and rsi > 78)):
        extended = True
    if side == "sell" and strategy == "trend_follow" and ((bb_pct == bb_pct and bb_pct < 0.08) or (rsi == rsi and rsi < 22)):
        extended = True
    if atr != atr or atr <= 0:
        side, strategy, score = "wait", "none", 0.0
    return {
        "side": side,
        "score": round(float(score if side == "buy" else -score if side == "sell" else 0.0), 2),
        "abs_score": round(float(score), 2),
        "regime": regime,
        "regime_fa": REGIME_FA.get(regime, regime),
        "family": family,
        "strategy": strategy,
        "strategy_fa": STRATEGY_FA.get(strategy, strategy),
        "extended": extended,
        "adx": None if adx != adx else round(adx, 1),
        "bb_width_percentile": round(bb_pctile, 1),
        "autocorr": round(ac, 3),
    }


def quality_tier(
    action: str,
    evidence: dict,
    agreement: float,
    news_level: str,
    extended: bool,
    layers_agree: bool,
) -> tuple[str, str]:
    """Return (tier, fa). Only high_conviction and strong should become live alerts."""
    if action not in {"buy", "sell"}:
        return "no_trade", "بدون معامله"
    oos = evidence.get("out_of_sample") or {}
    n = int(oos.get("trades") or 0)
    ev = float(oos.get("expectancy") or 0)
    pf = oos.get("profit_factor")
    p = float(evidence.get("calibrated_p") or 0.5)
    if news_level == "high":
        return "avoid", "اجتناب"
    if evidence.get("retired") or not evidence.get("has_edge"):
        return "avoid", "اجتناب"
    if extended:
        return "moderate", "متوسط / دیده‌بان"
    if n < MIN_OOS_TRADES or ev <= MIN_EXPECTANCY_R or (pf is not None and pf < MIN_PROFIT_FACTOR):
        return "avoid", "اجتناب"
    high = (
        ev >= 0.10
        and n >= 10
        and p >= 0.58
        and agreement >= 0.55
        and layers_agree
        and news_level != "medium"
    )
    strong = ev >= 0.03 and n >= MIN_OOS_TRADES and p >= 0.54 and agreement >= 0.40
    if high:
        return "high_conviction", "قانع‌کننده"
    if strong:
        return "strong", "قوی"
    return "moderate", "متوسط / دیده‌بان"


def calibrated_prob(trades: list[dict], side: str) -> tuple[float, int]:
    subset = [t for t in trades if t["side"] == side]
    if len(subset) < 5:
        subset = list(trades)
    n = len(subset)
    if n == 0:
        return 0.5, 0
    wins = sum(1 for t in subset if t["win"])
    raw = (wins + 1.0) / (n + 2.0)
    shrink = min(1.0, n / 16.0)
    p = 0.5 + (raw - 0.5) * shrink
    return float(min(MAX_CALIBRATED_PROB / 100.0, max(0.22, p))), n


def summarize(trades: list[dict], bars: int, interval: str) -> dict:
    if not trades:
        return _empty_stats()
    rs = np.array([t["pnl_r"] for t in trades], dtype=float)
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    equity = np.cumsum(rs)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = float(dd.max()) if len(dd) else 0.0
    gp = float(wins.sum()) if len(wins) else 0.0
    gl = float(np.abs(losses.sum())) if len(losses) else 0.0
    pf = round(gp / gl, 2) if gl > 1e-9 else (round(gp, 2) if gp else None)
    std = float(rs.std(ddof=1)) if len(rs) > 1 else 0.0
    down = losses if len(losses) else np.array([0.0])
    down_std = float(down.std(ddof=1)) if len(down) > 1 else float(abs(down.mean())) if len(down) else 0.0
    tpy = (len(trades) / max(bars, 1)) * BARS_PER_YEAR.get(interval, 252)
    sharpe = None
    sortino = None
    if std > 0.05 and len(rs) >= 5:
        sharpe = round(float(rs.mean()) / std * np.sqrt(max(tpy, 1.0)), 2)
    if down_std > 0.05 and len(losses) >= 3:
        sortino = round(float(rs.mean()) / down_std * np.sqrt(max(tpy, 1.0)), 2)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    held = sum(t.get("bars_held") or 1 for t in trades)
    streak = _max_loss_streak(trades)
    return {
        "trades": len(trades),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(100 * len(wins) / len(trades), 1),
        "loss_rate": round(100 * len(losses) / len(trades), 1),
        "profit_factor": pf,
        "expectancy": round(float(rs.mean()), 3),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "realized_rr": round(abs(avg_win / avg_loss), 2) if avg_loss < -1e-9 else None,
        "sum_r": round(float(rs.sum()), 2),
        "max_dd_r": round(max_dd, 2),
        "sharpe": None if sharpe is None else round(float(sharpe), 2),
        "sortino": None if sortino is None else round(float(sortino), 2),
        "recovery_factor": round(float(rs.sum()) / max_dd, 2) if max_dd > 1e-9 else None,
        "consecutive_losses": streak,
        "exposure_pct": round(100 * held / max(bars, 1), 1),
        "avg_r": round(float(rs.mean()), 3),
    }


def _simulate(work: pd.DataFrame, interval: str, symbol: str) -> list[dict]:
    hold = HOLD_BARS.get(interval, 8)
    cost = one_way_frac(symbol)
    n = len(work)
    trades: list[dict] = []
    i = 80
    while i < n - 2:
        core = core_at(work, i)
        side = core["side"]
        if side == "wait":
            i += 1
            continue
        row = work.iloc[i]
        nxt = work.iloc[i + 1]
        atr = _f(row.get("atr"))
        price = float(row["close"])
        if atr != atr or atr <= 0:
            i += 1
            continue
        raw_fill = float(nxt["open"])
        fill = raw_fill * (1 + cost) if side == "buy" else raw_fill * (1 - cost)
        sl_dist = max(atr * ATR_STOP_MULT, price * 0.0018)
        if side == "buy":
            sl, tp = fill - sl_dist, fill + sl_dist * MIN_RR
        else:
            sl, tp = fill + sl_dist, fill - sl_dist * MIN_RR
        exit_price = float(work.iloc[min(i + hold, n - 1)]["close"])
        result = "time"
        end = min(i + 1 + hold, n)
        bars_held = end - (i + 1)
        for j in range(i + 1, end):
            hi = float(work.iloc[j]["high"])
            lo = float(work.iloc[j]["low"])
            if side == "buy":
                hit_sl, hit_tp = lo <= sl, hi >= tp
            else:
                hit_sl, hit_tp = hi >= sl, lo <= tp
            if hit_sl and hit_tp:
                exit_price, result, bars_held = sl, "sl", j - i
                break
            if hit_sl:
                exit_price, result, bars_held = sl, "sl", j - i
                break
            if hit_tp:
                exit_price, result, bars_held = tp, "tp", j - i
                break
        if result == "time":
            exit_price = exit_price * (1 - cost) if side == "buy" else exit_price * (1 + cost)
        elif result == "tp":
            exit_price = tp * (1 - cost) if side == "buy" else tp * (1 + cost)
        else:
            exit_price = sl * (1 - cost) if side == "buy" else sl * (1 + cost)
        pnl = (exit_price - fill) if side == "buy" else (fill - exit_price)
        risk = abs(fill - sl) or price * 0.002
        rr = pnl / risk
        ts = row["time"]
        trades.append(
            {
                "bar": i,
                "time": int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts),
                "side": side,
                "side_fa": "خرید" if side == "buy" else "فروش",
                "strategy": core["strategy"],
                "regime": core["regime"],
                "entry": round(fill, 6),
                "sl": round(sl, 6),
                "tp": round(tp, 6),
                "exit": round(float(exit_price), 6),
                "result": result,
                "result_fa": {"tp": "هدف خورد", "sl": "حد ضرر", "time": "خروج زمانی"}[result],
                "pnl_r": round(float(rr), 3),
                "win": bool(rr > 0),
                "bars_held": int(max(1, bars_held)),
            }
        )
        i += max(1, bars_held)
    return trades


def _walk_forward(trades: list[dict], n: int, interval: str) -> list[dict]:
    folds = []
    cuts = [(0.40, 0.55), (0.55, 0.70), (0.70, 1.00)]
    for a, b in cuts:
        lo, hi = int(n * a), int(n * b)
        chunk = [t for t in trades if lo <= t["bar"] < hi]
        stats = summarize(chunk, max(hi - lo, 1), interval)
        folds.append({"from_pct": int(a * 100), "to_pct": int(b * 100), "expectancy": stats["expectancy"], "trades": stats["trades"], "win_rate": stats["win_rate"]})
    return folds


def _strategy_stats(trades: list[dict], bars: int, interval: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(t.get("strategy") or "none", []).append(t)
    out = {}
    for name, chunk in groups.items():
        stats = summarize(chunk, bars, interval)
        n = int(stats.get("trades") or 0)
        ev = float(stats.get("expectancy") or 0)
        pf = stats.get("profit_factor")
        has_edge = n >= MIN_OOS_TRADES and ev > MIN_EXPECTANCY_R and (pf is None or pf >= MIN_PROFIT_FACTOR)
        why = (
            f"{STRATEGY_FA.get(name, name)}: OOS EV {ev:+.2f}R · PF {pf} · {n} معامله"
            if n
            else f"{STRATEGY_FA.get(name, name)}: معامله‌ای نبود"
        )
        out[name] = {**stats, "strategy": name, "strategy_fa": STRATEGY_FA.get(name, name), "has_edge": has_edge, "verdict": why}
    return out


def _best_strategy(strategy_oos: dict[str, dict]) -> dict | None:
    if not strategy_oos:
        return None
    ranked = sorted(
        strategy_oos.values(),
        key=lambda s: (bool(s.get("has_edge")), float(s.get("expectancy") or -9), int(s.get("trades") or 0)),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _verdict(is_stats: dict, oos_stats: dict, strategy: str | None = None) -> tuple[bool, bool, str]:
    n_oos = int(oos_stats.get("trades") or 0)
    ev_oos = float(oos_stats.get("expectancy") or 0)
    ev_is = float(is_stats.get("expectancy") or 0)
    pf = oos_stats.get("profit_factor")
    label = STRATEGY_FA.get(strategy or "", strategy or "استراتژی")
    if n_oos < MIN_OOS_TRADES:
        return False, False, f"{label}: نمونه خارج از نمونه کافی نیست ({n_oos} معامله)"
    if ev_is >= 0.15 and ev_oos < 0:
        return True, False, f"{label}: داخل‌نمونه خوب و خارج‌نمونه ضعیف — احتمال برازش بیش‌ازحد"
    if ev_oos <= MIN_EXPECTANCY_R or (pf is not None and pf < MIN_PROFIT_FACTOR):
        return True, False, f"{label}: پس از هزینه امید ریاضی خارج از نمونه مثبت نیست (EV {ev_oos:+.2f}R)"
    if ev_oos > MIN_EXPECTANCY_R and (pf is None or pf >= MIN_PROFIT_FACTOR):
        return False, True, f"{label}: امید ریاضی خارج از نمونه پس از هزینه مثبت است (EV {ev_oos:+.2f}R)"
    return False, False, f"{label}: لبه آماری کافی دیده نشد"


def _regime_breakdown(trades: list[dict]) -> list[dict]:
    groups: dict[str, list[float]] = {}
    for t in trades:
        groups.setdefault(t.get("regime") or "unknown", []).append(t["pnl_r"])
    out = []
    for regime, rs in groups.items():
        arr = np.array(rs, dtype=float)
        out.append(
            {
                "regime": regime,
                "regime_fa": REGIME_FA.get(regime, regime),
                "trades": len(rs),
                "expectancy": round(float(arr.mean()), 3),
                "win_rate": round(100 * float((arr > 0).mean()), 1),
            }
        )
    out.sort(key=lambda x: x["trades"], reverse=True)
    return out


def _max_loss_streak(trades: list[dict]) -> int:
    best = cur = 0
    for t in trades:
        if not t["win"]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def holding_label(interval: str) -> str:
    hold = HOLD_BARS.get(interval, 8)
    seconds = next((tf["seconds"] for tf in TIMEFRAMES if tf["id"] == interval), 3600)
    hours = hold * seconds / 3600
    if hours >= 24:
        return f"حدود {hours / 24:.1f} روز"
    if hours >= 1:
        return f"حدود {hours:.0f} ساعت"
    return f"حدود {hold} کندل ({interval})"


def _empty_stats() -> dict:
    return {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "loss_rate": None,
        "profit_factor": None,
        "expectancy": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "realized_rr": None,
        "sum_r": 0.0,
        "max_dd_r": 0.0,
        "sharpe": None,
        "sortino": None,
        "recovery_factor": None,
        "consecutive_losses": 0,
        "exposure_pct": 0.0,
        "avg_r": 0.0,
    }


def _empty_evidence(interval: str, symbol: str, why: str) -> dict:
    return {
        "ok": False,
        "symbol": symbol,
        "interval": interval,
        "costs": cost_spec(symbol),
        "trades": [],
        "trade_count": 0,
        "all": _empty_stats(),
        "in_sample": _empty_stats(),
        "out_of_sample": _empty_stats(),
        "book_oos": _empty_stats(),
        "strategy_oos": {},
        "walk_forward": [],
        "has_edge": False,
        "retired": False,
        "verdict": why,
        "core": {"side": "wait", "score": 0.0, "regime": "unknown", "family": "ranging", "strategy": "none", "extended": False, "regime_fa": "نامشخص", "strategy_fa": STRATEGY_FA["none"]},
        "p_buy": 0.5,
        "p_sell": 0.5,
        "n_buy": 0,
        "n_sell": 0,
        "calibrated_p": 0.5,
        "regime_breakdown": [],
        "best_strategy": None,
    }


def _f(value) -> float:
    try:
        v = float(value)
        return v
    except (TypeError, ValueError):
        return float("nan")
