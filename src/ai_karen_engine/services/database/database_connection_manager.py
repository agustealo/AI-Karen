"""
DEPRECATED: Database Connection Manager

Use ai_karen_engine.database.client.DatabaseClient or
MultiTenantPostgresClient instead. This shim remains for backwards
compatibility during DATA-CONVERGE-1.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, Optional

from ai_karen_engine.database.client import get_database_client

warnings.warn(
    "DatabaseConnectionManager is deprecated. "
    "Use ai_karen_engine.database.client.DatabaseClient or "
    "MultiTenantPostgresClient instead.",
    DeprecationWarning,
    stacklevel=2,
)


class DatabaseConnectionManager:
    """Deprecated compatibility wrapper around DatabaseClient."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._client = get_database_client()
        self.config = config or {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def get_database_manager(config: Optional[Dict[str, Any]] = None) -> DatabaseConnectionManager:
    """Return a cached database connection manager."""
    return DatabaseConnectionManager(config or {})


def initialize_database_manager(config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> DatabaseConnectionManager:
    """Explicitly initialize the database manager and return the instance."""
    return get_database_manager(config)


__all__ = [
    "DatabaseConnectionManager",
    "get_database_manager",
    "initialize_database_manager",
]
