"""Local secret store for MT5 demo credentials. Never commit this file."""

from __future__ import annotations

import json
import os
from pathlib import Path

STORE_PATH = Path(os.environ.get("TRENDIX_MT5_STORE", Path.home() / ".trendix" / "mt5_local.json"))

DEFAULTS = {
    "enabled": False,
    "login": "",
    "password": "",
    "server": "Alpari-MT5-Demo",
    "terminal_path": "",
    "mode": "intraday",  # scalping | intraday | swing
    "risk_percent": 0.5,
    "max_positions": 3,
    "min_odds": 50,
    "cooldown_sec": 180,
    "magic": 260918,
    "only_alert_tiers": ["high_conviction", "strong", "moderate"],
}


def load() -> dict:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        data = dict(DEFAULTS)
        save(data)
        return data
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in raw.items() if k in DEFAULTS or k in {"login", "password", "server", "terminal_path"}})
    return out


def save(data: dict) -> dict:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = dict(DEFAULTS)
    if STORE_PATH.exists():
        try:
            current.update(json.loads(STORE_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    for k, v in data.items():
        if k == "password" and (v is None or v == "" or v == "********"):
            continue
        current[k] = v
    STORE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(STORE_PATH, 0o600)
    except Exception:
        pass
    return public_view(current)


def public_view(data: dict | None = None) -> dict:
    d = dict(data or load())
    has_pw = bool(d.get("password"))
    d["password"] = "********" if has_pw else ""
    d["has_password"] = has_pw
    d["store_path"] = str(STORE_PATH)
    return d
