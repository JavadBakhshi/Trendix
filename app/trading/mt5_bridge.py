"""Optional MetaTrader 5 bridge. Requires a local MT5 terminal (Windows; Wine on Linux).

Credentials are never hardcoded — load from local secret store or env vars.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("trendix.mt5")

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover - optional dependency / non-Windows
    mt5 = None  # type: ignore


# Trendix symbol → common Alpari / MT5 names (tried in order).
SYMBOL_CANDIDATES: dict[str, list[str]] = {
    "XAUUSD": ["XAUUSD", "GOLD", "XAUUSDm"],
    "EURUSD": ["EURUSD", "EURUSDm"],
    "GBPUSD": ["GBPUSD", "GBPUSDm"],
    "USDJPY": ["USDJPY", "USDJPYm"],
    "AUDUSD": ["AUDUSD", "AUDUSDm"],
    "USDCAD": ["USDCAD", "USDCADm"],
    "USDCHF": ["USDCHF", "USDCHFm"],
    "NZDUSD": ["NZDUSD", "NZDUSDm"],
    "EURJPY": ["EURJPY", "EURJPYm"],
    "GBPJPY": ["GBPJPY", "GBPJPm", "GBPJPYm"],
    "EURGBP": ["EURGBP", "EURGBPm"],
    "DXY": ["USDX", "DXY", "DX"],
    "BTCUSDT": ["BTCUSD", "BTCUSDT", "BTCUSDm"],
    "ETHUSDT": ["ETHUSD", "ETHUSDT", "ETHUSDm"],
    "BNBUSDT": ["BNBUSD", "BNBUSDT"],
    "SOLUSDT": ["SOLUSD", "SOLUSDT"],
    "XRPUSDT": ["XRPUSD", "XRPUSDT", "XRPUSDm"],
    "ADAUSDT": ["ADAUSD", "ADAUSDT"],
    "DOGEUSDT": ["DOGEUSD", "DOGEUSDT"],
}


def available() -> bool:
    return mt5 is not None


def initialize(login: int | None = None, password: str | None = None, server: str | None = None, path: str | None = None) -> dict:
    if mt5 is None:
        return {
            "ok": False,
            "error": (
                "پکیج MetaTrader5 نصب نیست یا این سیستم ویندوز نیست. "
                "معامله خودکار فقط روی سیستمی که ترمینال MT5 نصب دارد کار می‌کند "
                "(معمولاً ویندوز؛ لینوکس با Wine)."
            ),
        }
    kwargs: dict[str, Any] = {}
    if path:
        kwargs["path"] = path
    if not mt5.initialize(**kwargs):
        return {"ok": False, "error": f"MT5 initialize failed: {mt5.last_error()}"}
    if login and password and server:
        if not mt5.login(int(login), password=password, server=server):
            err = mt5.last_error()
            mt5.shutdown()
            return {"ok": False, "error": f"ورود ناموفق: {err}. سرور دموی آلپاری را درست وارد کن (مثلاً Alpari-MT5-Demo)."}
    info = mt5.account_info()
    if info is None:
        return {"ok": False, "error": f"account_info خالی است: {mt5.last_error()}"}
    return {
        "ok": True,
        "account": _account_dict(info),
        "terminal": _terminal_dict(),
    }


def shutdown() -> None:
    if mt5 is not None:
        try:
            mt5.shutdown()
        except Exception:
            pass


def account_snapshot() -> dict | None:
    if mt5 is None:
        return None
    info = mt5.account_info()
    return _account_dict(info) if info else None


def resolve_symbol(trendix_symbol: str) -> str | None:
    if mt5 is None:
        return None
    key = (trendix_symbol or "").upper()
    for name in SYMBOL_CANDIDATES.get(key, [key]):
        if mt5.symbol_select(name, True):
            return name
        info = mt5.symbol_info(name)
        if info is not None:
            mt5.symbol_select(name, True)
            return name
    # fuzzy: contains base
    base = key.replace("USDT", "").replace("USD", "")
    for s in mt5.symbols_get() or []:
        name = s.name
        if base and base in name.upper() and ("USD" in name.upper() or "USDT" in name.upper()):
            if mt5.symbol_select(name, True):
                return name
    return None


def symbol_cost_info(mt_symbol: str) -> dict:
    """Spread + estimated round-trip cost from broker ticks (demo may still show spread)."""
    info = mt5.symbol_info(mt_symbol) if mt5 else None
    if info is None:
        return {"spread_points": None, "spread_price": None, "trade_contract_size": None}
    point = float(info.point or 0)
    spread_points = float(info.spread or 0)
    return {
        "spread_points": spread_points,
        "spread_price": spread_points * point,
        "trade_contract_size": float(info.trade_contract_size or 0),
        "volume_min": float(info.volume_min or 0.01),
        "volume_step": float(info.volume_step or 0.01),
        "volume_max": float(info.volume_max or 100),
        "digits": int(info.digits or 5),
        "trade_mode": int(getattr(info, "trade_mode", -1)),
        "swap_long": float(getattr(info, "swap_long", 0) or 0),
        "swap_short": float(getattr(info, "swap_short", 0) or 0),
    }


def calc_lot(mt_symbol: str, risk_percent: float, stop_distance_price: float) -> float:
    """Risk-based lot size from account equity and SL distance."""
    if mt5 is None or stop_distance_price <= 0:
        return 0.0
    acc = mt5.account_info()
    info = mt5.symbol_info(mt_symbol)
    if not acc or not info:
        return 0.0
    risk_money = float(acc.equity) * max(0.1, min(5.0, risk_percent)) / 100.0
    tick_size = float(info.trade_tick_size or info.point or 0)
    tick_value = float(info.trade_tick_value or 0)
    if tick_size <= 0 or tick_value <= 0:
        lot = risk_money / (stop_distance_price * float(info.trade_contract_size or 100000) / max(float(acc.equity), 1))
    else:
        ticks = stop_distance_price / tick_size
        loss_per_lot = ticks * tick_value
        lot = risk_money / loss_per_lot if loss_per_lot > 0 else 0.0
    step = float(info.volume_step or 0.01)
    vmin = float(info.volume_min or 0.01)
    vmax = float(info.volume_max or 100)
    if step <= 0:
        step = 0.01
    lot = max(vmin, min(vmax, round(lot / step) * step))
    return float(round(lot, 2))


def place_market(
    mt_symbol: str,
    side: str,
    volume: float,
    sl: float | None = None,
    tp: float | None = None,
    comment: str = "Trendix",
    magic: int = 260918,
) -> dict:
    if mt5 is None:
        return {"ok": False, "error": "MetaTrader5 unavailable"}
    info = mt5.symbol_info(mt_symbol)
    if info is None:
        return {"ok": False, "error": f"نماد {mt_symbol} پیدا نشد"}
    if not info.visible:
        mt5.symbol_select(mt_symbol, True)
    tick = mt5.symbol_info_tick(mt_symbol)
    if tick is None:
        return {"ok": False, "error": "قیمت نماد در دسترس نیست"}
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = float(tick.ask if side == "buy" else tick.bid)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": mt_symbol,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "sl": float(sl or 0),
        "tp": float(tp or 0),
        "deviation": 30,
        "magic": magic,
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(info),
    }
    check = mt5.order_check(request)
    if check is None:
        return {"ok": False, "error": f"order_check failed: {mt5.last_error()}", "request": request}
    if check.retcode not in (0, mt5.TRADE_RETCODE_DONE, 10009, 10008):  # allow proceed; some demos differ
        # 0 sometimes means OK for check; continue if comment suggests ok
        if int(check.retcode) >= 10000 and int(check.retcode) not in {
            mt5.TRADE_RETCODE_DONE,
            getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1),
            getattr(mt5, "TRADE_RETCODE_PLACED", -1),
        }:
            # Still try send — demos vary; capture check info
            pass
    result = mt5.order_send(request)
    if result is None:
        return {"ok": False, "error": f"order_send failed: {mt5.last_error()}", "check": _asdict(check), "request": request}
    ok = result.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "ok": ok,
        "retcode": int(result.retcode),
        "order": int(result.order),
        "deal": int(result.deal),
        "volume": float(result.volume),
        "price": float(result.price),
        "comment": result.comment,
        "request": request,
        "check": _asdict(check),
        "cost": symbol_cost_info(mt_symbol),
        "error": None if ok else f"retcode={result.retcode} {result.comment}",
    }


def open_positions(magic: int | None = 260918) -> list[dict]:
    if mt5 is None:
        return []
    positions = mt5.positions_get() or []
    out = []
    for p in positions:
        if magic is not None and int(p.magic) != int(magic):
            continue
        out.append(
            {
                "ticket": int(p.ticket),
                "symbol": p.symbol,
                "type": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "swap": float(p.swap),
                "commission": float(getattr(p, "commission", 0) or 0),
                "comment": p.comment,
                "magic": int(p.magic),
            }
        )
    return out


def recent_deals(limit: int = 40, magic: int | None = 260918) -> list[dict]:
    if mt5 is None:
        return []
    from datetime import datetime, timedelta

    to = datetime.now()
    frm = to - timedelta(days=14)
    deals = mt5.history_deals_get(frm, to) or []
    rows = []
    for d in reversed(list(deals)):
        if magic is not None and int(getattr(d, "magic", 0) or 0) != int(magic):
            continue
        if int(d.entry) not in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
            continue
        rows.append(
            {
                "ticket": int(d.ticket),
                "order": int(d.order),
                "symbol": d.symbol,
                "type": "buy" if d.type == mt5.DEAL_TYPE_BUY else "sell" if d.type == mt5.DEAL_TYPE_SELL else str(d.type),
                "entry": int(d.entry),
                "volume": float(d.volume),
                "price": float(d.price),
                "profit": float(d.profit),
                "commission": float(d.commission),
                "swap": float(d.swap),
                "fee": float(getattr(d, "fee", 0) or 0),
                "time": int(d.time),
                "comment": d.comment,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _filling_mode(info) -> int:
    # Prefer IOC/FOK/RETURN depending on symbol
    filling = int(getattr(info, "filling_mode", 0) or 0)
    if filling & 1:
        return mt5.ORDER_FILLING_FOK
    if filling & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def _account_dict(info) -> dict:
    return {
        "login": int(info.login),
        "name": info.name,
        "server": info.server,
        "currency": info.currency,
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "margin_free": float(info.margin_free),
        "profit": float(info.profit),
        "leverage": int(info.leverage),
        "trade_mode": int(info.trade_mode),
        "trade_allowed": bool(info.trade_allowed),
        "trade_expert": bool(info.trade_expert),
        "company": info.company,
    }


def _terminal_dict() -> dict:
    t = mt5.terminal_info()
    if not t:
        return {}
    return {
        "connected": bool(t.connected),
        "trade_allowed": bool(t.trade_allowed),
        "name": t.name,
        "company": t.company,
        "path": t.path,
    }


def _asdict(obj) -> dict:
    if obj is None:
        return {}
    try:
        return obj._asdict()  # type: ignore
    except Exception:
        return {"repr": str(obj)}
