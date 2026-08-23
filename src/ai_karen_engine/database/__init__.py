# mypy: ignore-errors
"""
Database package for AI-Karen multi-tenant architecture.

Provides production-ready database services:
- Multi-tenant database client with connection pooling
- Migration management
- Conversation, memory, and tenant managers
- Factory for centralized initialization

NOTE: Multi-database support (MySQL, MongoDB, Firestore) has been retired.
Supabase/PostgreSQL is the canonical relational data spine.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.migrations import MigrationManager
from ai_karen_engine.database.models import (
    AuditLog,
    AuthUser,
    Base,
    Tenant,
    TenantConversation,
    TenantMemoryItem,
    TenantMemoryEntry,
)

# Import factory for centralized database initialization
from ai_karen_engine.database.factory import (
    DatabaseServiceConfig,
    DatabaseServiceFactory,
    get_database_service_factory,
    get_database_client,
    get_conversation_manager,
    get_memory_manager,
    get_tenant_manager,
    initialize_database_for_production,
)

# Import dependencies for FastAPI dependency injection
from ai_karen_engine.database.dependencies import (
    get_database_client_dependency,
    get_conversation_manager_dependency,
    get_memory_manager_dependency,
    get_tenant_manager_dependency,
    get_db_session,
    get_async_db_session_dependency,
    get_database_health_check,
    get_current_tenant_id,
    DatabaseTransaction,
    get_database_transaction,
)

_default_client: Optional[MultiTenantPostgresClient] = None
_import_error: Optional[Exception] = None


def _get_default_client() -> MultiTenantPostgresClient:
    """Lazily initialize and return the default database client."""
    global _default_client, _import_error

    if _default_client is None:
        try:
            _default_client = MultiTenantPostgresClient()
        except Exception as exc:  # pragma: no cover - optional dependency issues
            _import_error = exc
            raise

    return _default_client


@asynccontextmanager
async def get_postgres_session() -> AsyncGenerator:
    """Yield an asynchronous Postgres session from the default client."""
    try:
        client = _get_default_client()
    except Exception as exc:
        raise ImportError(
            "Postgres session cannot be created due to missing dependencies"
        ) from exc

    async with client.get_async_session() as session:
        yield session


__all__ = [
    # Models
    "Base",
    "Tenant",
    "AuthUser",
    "TenantConversation",
    "TenantMemoryItem",
    "TenantMemoryEntry",
    "AuditLog",
    # Clients
    "MultiTenantPostgresClient",
    "MigrationManager",
    "get_postgres_session",
    # Factory
    "DatabaseServiceConfig",
    "DatabaseServiceFactory",
    "get_database_service_factory",
    # Factory convenience functions
    "get_database_client",
    "get_conversation_manager",
    "get_memory_manager",
    "get_tenant_manager",
    "initialize_database_for_production",
    # Dependencies (FastAPI)
    "get_database_client_dependency",
    "get_conversation_manager_dependency",
    "get_memory_manager_dependency",
    "get_tenant_manager_dependency",
    "get_db_session",
    "get_async_db_session_dependency",
    "get_database_health_check",
    "get_current_tenant_id",
    "DatabaseTransaction",
    "get_database_transaction",
    # Canonical persistence config
    "DatabaseSettings",
    "SupabaseSettings",
    "PostgresSettings",
    "get_database_settings",
    "refresh_database_settings",
]
