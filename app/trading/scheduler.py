"""In-app autotrade loop — no separate worker process required."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.trading.executor import run_once
from app.trading.secrets import load

_task: asyncio.Task | None = None
_lock = asyncio.Lock()
_last: dict[str, Any] = {"at": 0, "result": None, "running": False, "error": None}


def loop_status() -> dict:
    return {
        "loop_alive": _task is not None and not _task.done(),
        "running": bool(_last.get("running")),
        "last_at": _last.get("at") or 0,
        "last_error": _last.get("error"),
        "last_placed": len(((_last.get("result") or {}).get("placed") or [])),
        "last_headline": ((_last.get("result") or {}).get("alerts_headline")),
    }


def _interval_sec(mode: str) -> int:
    if mode == "scalping":
        return 35
    if mode == "swing":
        return 180
    return 75


async def _loop() -> None:
    while True:
        cfg = load()
        if not cfg.get("enabled"):
            _last.update({"running": False, "error": None})
            await asyncio.sleep(8)
            continue
        _last["running"] = True
        try:
            result = await run_once()
            _last.update({"at": int(time.time()), "result": result, "error": result.get("error")})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _last.update({"at": int(time.time()), "error": str(exc), "result": None})
        mode = (load().get("mode") or "scalping")
        await asyncio.sleep(_interval_sec(mode))


async def ensure_started() -> None:
    global _task
    async with _lock:
        if _task is None or _task.done():
            _task = asyncio.create_task(_loop(), name="trendix-autotrade")


async def stop_loop() -> None:
    global _task
    async with _lock:
        if _task and not _task.done():
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
        _task = None
        _last["running"] = False
