"""ASGI entrypoint for running the CIP/ENIP orchestration API."""
from __future__ import annotations

import os

from services.plc_manager import PLCManager

from . import create_app


def _build_manager() -> PLCManager:
    host = os.getenv("PLC_HOST", "127.0.0.1")
    port = int(os.getenv("PLC_PORT", "44818"))
    pool_size = int(os.getenv("PLC_POOL_SIZE", "2"))
    return PLCManager(host, plc_port=port, pool_size=pool_size)


plc_manager = _build_manager()
app = create_app(plc_manager)

__all__ = ["app"]
