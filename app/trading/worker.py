#!/usr/bin/env python3
"""Local MT5 auto-trader worker. Run on the PC where Alpari MT5 is open.

  source .venv/bin/activate   # or Windows venv
  pip install MetaTrader5
  python -m app.trading.worker
"""

from __future__ import annotations

import asyncio
import time

from app.trading.executor import run_once
from app.trading.secrets import load


async def main() -> None:
    print("Trendix MT5 worker started. Ctrl+C to stop.")
    while True:
        cfg = load()
        if not cfg.get("enabled"):
            print(time.strftime("%H:%M:%S"), "disabled — waiting")
            await asyncio.sleep(15)
            continue
        try:
            result = await run_once()
            placed = result.get("placed") or []
            print(
                time.strftime("%H:%M:%S"),
                "ok" if result.get("ok") else result.get("error") or result.get("reason"),
                f"placed={len(placed)}",
                (result.get("account") or {}).get("equity"),
            )
        except Exception as exc:
            print(time.strftime("%H:%M:%S"), "error", exc)
        mode = (load().get("mode") or "intraday")
        sleep_s = 45 if mode == "scalping" else 90 if mode == "intraday" else 180
        await asyncio.sleep(sleep_s)


if __name__ == "__main__":
    asyncio.run(main())
