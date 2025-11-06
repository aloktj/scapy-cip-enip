"""FastAPI application for CIP/ENIP orchestration."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from services.plc_manager import PLCManager

from .dependencies import configure_authenticator, configure_orchestrator
from .middleware import CIPLoggingMiddleware
from .orchestrator import SessionOrchestrator
from .routes import api_router

logger = logging.getLogger(__name__)


def create_app(
    plc_manager: PLCManager,
    *,
    title: str = "CIP/ENIP Web API",
    auth_token: str | None = None,
) -> FastAPI:
    """Create and configure a FastAPI application bound to a :class:`PLCManager`."""
    app = FastAPI(title=title)

    orchestrator = SessionOrchestrator(plc_manager)
    configure_orchestrator(orchestrator)
    configure_authenticator(auth_token or os.getenv("PLC_API_TOKEN"))

    app.include_router(api_router)
    app.add_middleware(CIPLoggingMiddleware)

    static_root = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if static_root.exists():
        app.mount("/ui", StaticFiles(directory=str(static_root), html=True), name="ui")

    logger.debug("Web API application created with PLCManager %s", plc_manager)

    return app


__all__ = ["create_app", "SessionOrchestrator"]
