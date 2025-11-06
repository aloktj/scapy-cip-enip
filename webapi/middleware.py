"""Middleware utilities for the web API."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from services.plc_manager import PLCManagerError

logger = logging.getLogger(__name__)


class CIPLoggingMiddleware(BaseHTTPMiddleware):
    """Log CIP status codes and ENIP errors propagated through the request state."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        try:
            response = await call_next(request)
        except PLCManagerError as exc:
            logger.exception(
                "PLC manager error during %s %s: %s", request.method, request.url.path, exc
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "Unhandled error during %s %s: %s", request.method, request.url.path, exc
            )
            raise

        status = getattr(request.state, "cip_status", None)
        if status is not None:
            logger.info(
                "CIP status %s for %s %s -> %s",
                getattr(status, "code", None),
                request.method,
                request.url.path,
                getattr(status, "message", None),
            )

        enip_error = getattr(request.state, "enip_error", None)
        if enip_error:
            logger.error(
                "ENIP error for %s %s -> %s", request.method, request.url.path, enip_error
            )

        return response


__all__ = ["CIPLoggingMiddleware"]
