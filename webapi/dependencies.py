"""Dependency wiring for the web API layer."""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .orchestrator import SessionOrchestrator

__all__ = [
    "TokenAuthenticator",
    "configure_authenticator",
    "configure_orchestrator",
    "get_orchestrator",
    "require_token",
]


class TokenAuthenticator:
    """Simple bearer token authenticator used by the API layer."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("Authentication token must be a non-empty string")
        self._token = token

    def verify(self, candidate: str) -> bool:
        """Return ``True`` when *candidate* matches the configured token."""

        return secrets.compare_digest(self._token, candidate)


_SECURITY_SCHEME = HTTPBearer(auto_error=False)
_ORCHESTRATOR: Optional[SessionOrchestrator] = None
_AUTHENTICATOR: Optional[TokenAuthenticator] = None


def configure_orchestrator(orchestrator: SessionOrchestrator) -> None:
    """Register the orchestrator instance used by the FastAPI dependency graph."""
    global _ORCHESTRATOR
    _ORCHESTRATOR = orchestrator


def configure_authenticator(token: Optional[str]) -> None:
    """Configure the optional bearer token authenticator."""

    global _AUTHENTICATOR
    if token:
        _AUTHENTICATOR = TokenAuthenticator(token)
    else:
        _AUTHENTICATOR = None


def get_orchestrator() -> SessionOrchestrator:
    """Retrieve the configured orchestrator instance."""
    if _ORCHESTRATOR is None:
        raise RuntimeError("Session orchestrator has not been configured")
    return _ORCHESTRATOR


def require_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_SECURITY_SCHEME),
) -> None:
    """Validate the Authorization header when authentication is enabled."""

    if _AUTHENTICATOR is None:
        return

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _AUTHENTICATOR.verify(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
