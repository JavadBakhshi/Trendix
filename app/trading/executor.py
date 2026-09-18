"""Execute Trendix alerts on a local MetaTrader 5 demo/live terminal."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.analysis.alerts import scan_alerts
from app.trading import mt5_bridge
from app.trading.secrets import load as load_secrets
from app.trading.secrets import public_view

LOG_PATH = Path.home() / ".trendix" / "trade_log.jsonl"
STATE_PATH = Path.home() / ".trendix" / "executor_state.json"

MODE_INTERVALS = {
    "scalping": {"prefer": ["5m", "15m"], "min_hold_hint": "۱۵–۶۰ دقیقه"},
    "intraday": {"prefer": ["15m", "1h"], "min_hold_hint": "۱–۸ ساعت"},
    "swing": {"prefer": ["1h", "1d"], "min_hold_hint": "۱–۵ روز"},
}


def _append_log(row: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_trade_at": {}, "last_run": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_trade_at": {}, "last_run": 0}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def read_trade_log(limit: int = 50) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    rows = []
    for line in reversed(lines[-limit:]):
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def connect_from_secrets() -> dict:
    cfg = load_secrets()
    login = str(cfg.get("login") or "").strip()
    password = str(cfg.get("password") or "")
    server = str(cfg.get("server") or "").strip()
    path = str(cfg.get("terminal_path") or "").strip() or None
    if not login or not password or not server:
        return {"ok": False, "error": "یوزر، رمز و سرور را در تنظیمات معامله خودکار کامل کن."}
    try:
        login_i = int(login)
    except ValueError:
        return {"ok": False, "error": "شماره اکانت باید عدد باشد."}
    return mt5_bridge.initialize(login_i, password, server, path)


async def run_once() -> dict:
    cfg = load_secrets()
    if not cfg.get("enabled"):
        return {"ok": False, "skipped": True, "reason": "معامله خودکار خاموش است"}
    if not mt5_bridge.available():
        return {
            "ok": False,
            "error": "MetaTrader5 روی این سیستم در دسترس نیست. ترمینال MT5 را روی ویندوز نصب و باز کن، بعد worker را آنجا اجرا کن.",
        }

    conn = connect_from_secrets()
    if not conn.get("ok"):
        return conn

    mode = cfg.get("mode") or "intraday"
    prefer = MODE_INTERVALS.get(mode, MODE_INTERVALS["intraday"])["prefer"]
    min_odds = int(cfg.get("min_odds") or 50)
    risk = float(cfg.get("risk_percent") or 0.5)
    max_pos = int(cfg.get("max_positions") or 3)
    cooldown = int(cfg.get("cooldown_sec") or 180)
    magic = int(cfg.get("magic") or 260918)

    alerts = await scan_alerts([], min_odds=min_odds)
    ideas = list(alerts.get("buys") or []) + list(alerts.get("sells") or [])
    # Prefer mode intervals
    ideas.sort(
        key=lambda a: (
            0 if a.get("interval") in prefer else 1,
            0 if a.get("quality") in {"high_conviction", "strong"} else 1,
            -int(a.get("success_pct") or 0),
        )
    )

    open_pos = mt5_bridge.open_positions(magic=magic)
    open_symbols = {p["symbol"] for p in open_pos}
    state = _load_state()
    last_map = state.setdefault("last_trade_at", {})
    now = time.time()
    placed = []
    skipped = []

    for idea in ideas:
        if len(open_pos) + len(placed) >= max_pos:
            skipped.append({"symbol": idea.get("symbol"), "reason": "سقف پوزیشن"})
            break
        side = idea.get("action")
        if side not in {"buy", "sell"}:
            continue
        tx = idea.get("symbol")
        mt_sym = mt5_bridge.resolve_symbol(tx)
        if not mt_sym:
            skipped.append({"symbol": tx, "reason": "نماد در بروکر پیدا نشد"})
            continue
        if mt_sym in open_symbols:
            skipped.append({"symbol": mt_sym, "reason": "پوزیشن باز دارد"})
            continue
        last_t = float(last_map.get(mt_sym) or 0)
        if now - last_t < cooldown:
            skipped.append({"symbol": mt_sym, "reason": "cooldown"})
            continue

        entry = idea.get("entry") or idea.get("buy_at") or idea.get("sell_at")
        sl = idea.get("stop_loss") or idea.get("buy_sl") or idea.get("sell_sl")
        tp = idea.get("tp1") or idea.get("buy_tp") or idea.get("sell_tp")
        # Fallback SL/TP from current price if missing (near-entry soft alerts)
        tick_info = mt5_bridge.symbol_cost_info(mt_sym)
        if not sl or not entry:
            # skip if we can't size risk safely
            if not sl or not tp:
                skipped.append({"symbol": mt_sym, "reason": "SL/TP ناقص — فقط سیگنال نزدیک ورود"})
                continue
        try:
            entry_f = float(entry)
            sl_f = float(sl)
            tp_f = float(tp) if tp else 0.0
        except (TypeError, ValueError):
            skipped.append({"symbol": mt_sym, "reason": "اعداد ورود نامعتبر"})
            continue
        stop_dist = abs(entry_f - sl_f)
        if stop_dist <= 0:
            skipped.append({"symbol": mt_sym, "reason": "فاصله حد ضرر صفر"})
            continue
        lot = mt5_bridge.calc_lot(mt_sym, risk, stop_dist)
        if lot <= 0:
            skipped.append({"symbol": mt_sym, "reason": "حجم محاسبه‌شده صفر"})
            continue

        result = mt5_bridge.place_market(
            mt_sym,
            side,
            lot,
            sl=sl_f,
            tp=tp_f or None,
            comment=f"TX {idea.get('interval')}",
            magic=magic,
        )
        row = {
            "ts": int(now),
            "trendix": tx,
            "mt_symbol": mt_sym,
            "side": side,
            "lot": lot,
            "success_pct": idea.get("success_pct"),
            "quality": idea.get("quality"),
            "interval": idea.get("interval"),
            "mode": mode,
            "spread": (result.get("cost") or {}).get("spread_price"),
            "result": result,
        }
        _append_log(row)
        if result.get("ok"):
            placed.append(row)
            last_map[mt_sym] = now
            open_symbols.add(mt_sym)
        else:
            skipped.append({"symbol": mt_sym, "reason": result.get("error") or "ارسال ناموفق"})

    state["last_run"] = int(now)
    _save_state(state)
    snap = mt5_bridge.account_snapshot()
    deals = mt5_bridge.recent_deals(limit=30, magic=magic)
    mt5_bridge.shutdown()
    return {
        "ok": True,
        "mode": mode,
        "mode_hint": MODE_INTERVALS.get(mode, {}).get("min_hold_hint"),
        "placed": placed,
        "skipped": skipped[:20],
        "open_positions": open_pos,
        "account": snap,
        "deals": deals,
        "alerts_headline": alerts.get("headline"),
        "config": public_view(cfg),
    }


async def status_bundle() -> dict:
    cfg = public_view()
    out = {
        "mt5_library": mt5_bridge.available(),
        "config": cfg,
        "log": read_trade_log(40),
        "note": (
            "معامله خودکار روی سرور ابری Render معمولاً کار نمی‌کند؛ "
            "باید Trendix را روی همان سیستمی که MT5 آلپاری باز است اجرا کنی."
        ),
    }
    if not cfg.get("enabled") or not cfg.get("has_password"):
        return out
    if not mt5_bridge.available():
        return out
    conn = connect_from_secrets()
    out["connection"] = {k: v for k, v in conn.items() if k != "error"} if conn.get("ok") else conn
    if conn.get("ok"):
        magic = int(load_secrets().get("magic") or 260918)
        out["open_positions"] = mt5_bridge.open_positions(magic=magic)
        out["deals"] = mt5_bridge.recent_deals(limit=30, magic=magic)
        out["account"] = mt5_bridge.account_snapshot()
        mt5_bridge.shutdown()
    return out
