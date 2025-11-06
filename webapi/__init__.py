"""FastAPI application for CIP/ENIP orchestration."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from services.plc_manager import PLCManager

from .dependencies import configure_orchestrator
from .middleware import CIPLoggingMiddleware
from .orchestrator import SessionOrchestrator
from .routes import api_router

logger = logging.getLogger(__name__)


def create_app(plc_manager: PLCManager, *, title: str = "CIP/ENIP Web API") -> FastAPI:
    """Create and configure a FastAPI application bound to a :class:`PLCManager`."""
    app = FastAPI(title=title)

    orchestrator = SessionOrchestrator(plc_manager)
    configure_orchestrator(orchestrator)

    app.include_router(api_router)
    app.add_middleware(CIPLoggingMiddleware)

    logger.debug("Web API application created with PLCManager %s", plc_manager)

    return app


__all__ = ["create_app", "SessionOrchestrator"]
