#!/usr/bin/env python3
"""Start CryptoAnalyzer. Local: python run.py   Cloud: PORT is set by the host."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    reload = os.environ.get("RELOAD", "1" if host.startswith("127.") else "0") == "1"
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
