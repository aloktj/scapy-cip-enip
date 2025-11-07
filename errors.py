"""Shared exception hierarchy for PLC communication modules."""
from __future__ import annotations


class PLCManagerError(Exception):
    """Base class for all PLC management errors."""


class PLCConnectionError(PLCManagerError):
    """Raised when a socket level or session level connection fails."""


__all__ = [
    "PLCConnectionError",
    "PLCManagerError",
]
