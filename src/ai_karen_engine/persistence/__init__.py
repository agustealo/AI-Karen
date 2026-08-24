"""Persistence layer.

Package layout:
    persistence/
    ├── postgres/          # Canonical SQLAlchemy engine + sessions
    │   ├── engine.py
    │   └── transactions.py
    ├── supabase/          # Supabase API client (PostgREST, Storage, Realtime)
    ├── repositories/      # Data-access seam (Conversation, Memory, Tenant, Audit)
    └── __init__.py
"""

from ai_karen_engine.persistence.postgres import (
    ConnectionPoolMetrics,
    DatabaseHealthStatus,
    PostgresEngine,
    get_postgres_engine,
    refresh_postgres_engine,
)

__all__ = [
    "PostgresEngine",
    "ConnectionPoolMetrics",
    "DatabaseHealthStatus",
    "get_postgres_engine",
    "refresh_postgres_engine",
]
