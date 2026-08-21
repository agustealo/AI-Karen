from __future__ import annotations

from functools import lru_cache
from typing import Any

from ai_karen_engine.services.database.database_connection_manager import (
    DatabaseConfig,
    DatabaseConnectionManager,
)


def get_database_manager(config: Any | None = None) -> DatabaseConnectionManager:
    """Get a database connection manager instance."""
    if config is None:
        config = {}
    if hasattr(config, "model_dump"):
        config = config.model_dump()
    elif hasattr(config, "__dict__") and not isinstance(config, dict):
        config = dict(config.__dict__)
    return DatabaseConnectionManager(config)


async def initialize_database_manager(config: Any | None = None, **kwargs) -> DatabaseConnectionManager:
    """Explicitly initialize the database manager and return the instance."""
    # Cache clearing not needed without lru_cache
    
    # Merge kwargs into config if provided
    final_config = dict(config or {})
    final_config.update(kwargs)
    
    return get_database_manager(final_config)


__all__ = [
    "DatabaseConfig",
    "DatabaseConnectionManager",
    "get_database_manager",
    "initialize_database_manager",
]
