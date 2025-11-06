"""Dependency wiring for the web API layer."""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.config_store import ConfigurationStore

from .orchestrator import SessionOrchestrator

__all__ = [
    "TokenAuthenticator",
    "configure_authenticator",
    "configure_config_store",
    "configure_orchestrator",
    "get_config_store",
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
_CONFIG_STORE: Optional[ConfigurationStore] = None


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


def configure_config_store(store: ConfigurationStore) -> None:
    """Register the configuration store used by the API dependencies."""

    global _CONFIG_STORE
    _CONFIG_STORE = store


def get_orchestrator() -> SessionOrchestrator:
    """Retrieve the configured orchestrator instance."""
    if _ORCHESTRATOR is None:
        raise RuntimeError("Session orchestrator has not been configured")
    return _ORCHESTRATOR


def get_config_store() -> ConfigurationStore:
    """Retrieve the configured :class:`ConfigurationStore`."""

    if _CONFIG_STORE is None:
        raise RuntimeError("Configuration store has not been configured")
    return _CONFIG_STORE


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
