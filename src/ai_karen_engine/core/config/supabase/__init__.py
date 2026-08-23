"""Supabase config package marker.

DEPRECATED: Prefer ``ai_karen_engine.config.database``.
This shim remains for backward compatibility during DATA-CONVERGE-2.
"""

from ai_karen_engine.core.config.supabase.keys import SupabaseKeyConfig, load_supabase_key_config

# --- Canonical config re-exports (DATA-CONVERGE-2) ---
from ai_karen_engine.config.database import (  # noqa: F401
    SupabaseSettings,
    PostgresSettings,
    PoolSettings,
    DatabaseSettings,
    get_database_settings,
    refresh_database_settings,
)

__all__ = [
    "SupabaseKeyConfig",
    "load_supabase_key_config",
    "SupabaseSettings",
    "PostgresSettings",
    "PoolSettings",
    "DatabaseSettings",
    "get_database_settings",
    "refresh_database_settings",
]
