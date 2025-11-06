"""Dependency wiring for the web API layer."""
from __future__ import annotations

from typing import Optional

from .orchestrator import SessionOrchestrator

__all__ = ["configure_orchestrator", "get_orchestrator"]

_ORCHESTRATOR: Optional[SessionOrchestrator] = None


def configure_orchestrator(orchestrator: SessionOrchestrator) -> None:
    """Register the orchestrator instance used by the FastAPI dependency graph."""
    global _ORCHESTRATOR
    _ORCHESTRATOR = orchestrator


def get_orchestrator() -> SessionOrchestrator:
    """Retrieve the configured orchestrator instance."""
    if _ORCHESTRATOR is None:
        raise RuntimeError("Session orchestrator has not been configured")
    return _ORCHESTRATOR
