"""
Production Database Client
SQLAlchemy database connection management with async support

DATA-CONVERGE-2: Engine and session factory ownership now lives in the
canonical ``ai_karen_engine.persistence.postgres.PostgresEngine`` singleton.
This module proxies to it, preserving the ``.engine`` / ``.async_engine`` /
``.SessionLocal`` / ``.AsyncSessionLocal`` attributes and all method
signatures for backward compatibility.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import contextmanager, asynccontextmanager
from typing import Generator, AsyncGenerator, Any, Optional
import time
import re
from datetime import datetime
from dataclasses import dataclass, field

from ai_karen_engine.database.models import Base
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.persistence.postgres import get_postgres_engine

# Canonical URL reference for error messages (no fallback needed — if canonical
# config fails, the engine initialization will also fail and report it)
from ai_karen_engine.config.database import get_database_settings
_canonical_database_url = get_database_settings().postgres.build_database_url()

try:
    from ai_karen_engine.utils.error_formatter import ErrorFormatter, log_config_error
except ImportError:
    ErrorFormatter = None
    log_config_error = None

logger = get_logger(__name__)


@dataclass
class ConnectionPoolMetrics:
    """Connection pool health metrics"""
    pool_size: int = 0
    checked_out: int = 0
    overflow: int = 0
    checked_in: int = 0
    total_connections: int = 0
    invalid_connections: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DatabaseHealthStatus:
    """Database health check result"""
    is_healthy: bool
    status: str
    message: str
    response_time_ms: float
    connection_pool_metrics: Optional[ConnectionPoolMetrics] = None
    last_check: datetime = field(default_factory=datetime.utcnow)
    error_details: Optional[str] = None


class DatabaseClient:
    """Production database client with connection pooling and async support.

    Proxies engine/session ownership to the canonical PostgresEngine singleton.
    """

    def __init__(self):
        self._engine_holder = get_postgres_engine()

    # --- Backward-compatible property access to canonical engine ---
    @property
    def engine(self):
        return self._engine_holder.engine

    @property
    def async_engine(self):
        return self._engine_holder.async_engine

    @property
    def SessionLocal(self):
        return self._engine_holder.session_factory

    @property
    def AsyncSessionLocal(self):
        return self._engine_holder.async_session_factory

    def _initialize_engine(self):
        """No-op. Engine is owned by PostgresEngine singleton."""
        pass

    def create_tables(self) -> None:
        """No-op in production. Table creation is owned by migrations."""
        logger.warning(
            "DatabaseClient.create_tables() is a no-op in production. "
            "Use migrations to manage schema."
        )

    async def cleanup(self):
        """Close database engines and free resources (async)."""
        await self._engine_holder.cleanup()

    def close(self):
        """Synchronous cleanup (best effort)."""
        self._engine_holder.close()

    def drop_tables(self):
        """Compatibility no-op. Destructive schema operations are deployment-owned."""
        logger.warning("DatabaseClient.drop_tables() is disabled; use controlled recovery tooling.")
        return None

    def get_session(self) -> Session:
        """Get a new database session"""
        return self._engine_holder.get_session()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations"""
        with self._engine_holder.session_scope() as session:
            yield session

    def health_check(self) -> bool:
        """Check database connectivity"""
        return self._engine_holder.health_check()

    def is_degraded(self) -> bool:
        """Return True if the database is not healthy."""
        return self._engine_holder.is_degraded()

    def comprehensive_health_check(self) -> DatabaseHealthStatus:
        """Perform comprehensive database health check with metrics"""
        return self._engine_holder.comprehensive_health_check()

    def startup_health_check(self) -> DatabaseHealthStatus:
        """Perform startup health check with detailed validation"""
        return self._engine_holder.startup_health_check()

    def _get_connection_pool_metrics(self) -> ConnectionPoolMetrics:
        """Get current connection pool metrics"""
        if not self.engine or not hasattr(self.engine, "pool"):
            return ConnectionPoolMetrics()
        pool = self.engine.pool
        try:
            return ConnectionPoolMetrics(
                pool_size=getattr(pool, "size", lambda: 0)(),
                checked_out=getattr(pool, "checkedout", lambda: 0)(),
                overflow=getattr(pool, "overflow", lambda: 0)(),
                checked_in=getattr(pool, "checkedin", lambda: 0)(),
                total_connections=getattr(pool, "size", lambda: 0)()
                + getattr(pool, "overflow", lambda: 0)(),
                invalid_connections=getattr(pool, "invalidated", lambda: 0)(),
            )
        except Exception:
            return ConnectionPoolMetrics()

    def _sanitize_database_url(self, url: str) -> str:
        """Sanitize database URL by removing credentials"""
        try:
            pattern = r"(postgresql://[^:]+:)[^@]+(@.+)"
            return re.sub(pattern, r"\1****\2", url)
        except Exception:
            return "postgresql://****:****@[host]/[database]"

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get async database session with automatic cleanup and commit."""
        async with self._engine_holder.get_async_session() as session:
            yield session

    async_session_scope = get_async_session
    _get_pool_metrics = _get_connection_pool_metrics

    def initialize(self) -> None:
        """No-op compatibility method. Engine is owned by PostgresEngine."""
        return None

    async def async_health_check(self) -> bool:
        """Check database connectivity asynchronously"""
        return await self._engine_holder.async_health_check()

    async def async_comprehensive_health_check(self) -> DatabaseHealthStatus:
        """Perform comprehensive async database health check with metrics"""
        return await self._engine_holder.async_comprehensive_health_check()

    def get_tenant_schema_name(self, tenant_id: str) -> str:
        """Get schema name for tenant (for multi-tenant support)"""
        return f"tenant_{tenant_id}"

    async def create_tables_async(self):
        """Compatibility no-op. Schema creation is owned by Supabase migrations."""
        logger.warning("DatabaseClient.create_tables_async() is disabled; apply Supabase migrations before startup.")
        return None


# Multi-tenant database client class
class MultiTenantPostgresClient(DatabaseClient):
    """Multi-tenant PostgreSQL client with async support and enhanced health monitoring.

    DATA-CONVERGE-2: The ``database_url`` override parameter is accepted for
    backward compatibility but ignored — the canonical PostgresEngine reads
    connection parameters from ``DatabaseSettings``.
    """

    def __init__(self, database_url: Optional[str] = None, **kwargs):
        super().__init__()

    def get_sync_session(self) -> Session:
        """Compatibility wrapper for callers expecting an explicit sync session accessor."""
        return self.get_session()

    def create_shared_tables(self) -> None:
        """No-op in production. Table creation is owned by migrations."""
        logger.warning(
            "DatabaseClient.create_shared_tables() is a no-op in production. "
            "Use migrations to manage schema."
        )

    def create_persona_tables(self) -> None:
        """Compatibility no-op. Persona tables are part of the Supabase baseline."""
        logger.warning("create_persona_tables() is disabled; persona schema is migration-owned.")
        return None

    def create_tenant_schema(self, tenant_id: Any) -> bool:
        """Compatibility no-op for deployments using shared-table tenant scoping."""
        if tenant_id is None:
            return False
        return True

    def drop_tenant_schema(self, tenant_id: Any) -> bool:
        """Compatibility no-op for deployments using shared-table tenant scoping."""
        if tenant_id is None:
            return False
        return True

    def tenant_schema_exists(self, tenant_id: Any) -> bool:
        """Compatibility no-op for deployments using shared-table tenant scoping."""
        return tenant_id is not None

    def health_check_with_tenant_support(self, tenant_id: Optional[str] = None) -> DatabaseHealthStatus:
        """Perform health check with optional tenant-specific validation"""
        start_time = time.time()

        try:
            basic_health = self.comprehensive_health_check()

            if not basic_health.is_healthy:
                return basic_health

            if tenant_id:
                schema_name = self.get_tenant_schema_name(tenant_id)

                with self.session_scope() as session:
                    try:
                        session.execute(
                            text(
                                f"SELECT 1 FROM information_schema.schemata "
                                f"WHERE schema_name = '{schema_name}'"
                            )
                        )
                        tenant_check = f"Tenant schema check for {tenant_id}: PASS"
                    except Exception as e:
                        tenant_check = f"Tenant schema check for {tenant_id}: WARNING - {str(e)}"

                response_time_ms = (time.time() - start_time) * 1000

                return DatabaseHealthStatus(
                    is_healthy=True,
                    status="healthy",
                    message=f"Multi-tenant database connection successful. {tenant_check}",
                    response_time_ms=response_time_ms,
                    connection_pool_metrics=basic_health.connection_pool_metrics,
                )

            return basic_health

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Multi-tenant database connection failed: {e}",
                response_time_ms=response_time_ms,
                error_details=str(e),
            )

    async def async_health_check_with_tenant_support(self, tenant_id: Optional[str] = None) -> DatabaseHealthStatus:
        """Perform async health check with optional tenant-specific validation"""
        start_time = time.time()

        try:
            basic_health = await self.async_comprehensive_health_check()

            if not basic_health.is_healthy:
                return basic_health

            if tenant_id:
                schema_name = self.get_tenant_schema_name(tenant_id)

                async with self.get_async_session() as session:
                    try:
                        await session.execute(
                            text(
                                f"SELECT 1 FROM information_schema.schemata "
                                f"WHERE schema_name = '{schema_name}'"
                            )
                        )
                        tenant_check = f"Tenant schema check for {tenant_id}: PASS"
                    except Exception as e:
                        tenant_check = f"Tenant schema check for {tenant_id}: WARNING - {str(e)}"

                response_time_ms = (time.time() - start_time) * 1000

                return DatabaseHealthStatus(
                    is_healthy=True,
                    status="healthy",
                    message=f"Async multi-tenant database connection successful. {tenant_check}",
                    response_time_ms=response_time_ms,
                    connection_pool_metrics=basic_health.connection_pool_metrics,
                )

            return basic_health

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Async multi-tenant database connection failed: {e}",
                response_time_ms=response_time_ms,
                error_details=str(e),
            )


# Global database client instance
db_client = DatabaseClient()


# Convenience functions
def get_db_session() -> Session:
    """Get a new database session"""
    return db_client.get_session()


@contextmanager
def get_db_session_context() -> Generator[Session, None, None]:
    """Get database session with automatic cleanup"""
    with db_client.session_scope() as session:
        yield session


def create_database_tables():
    """Create all database tables (development/test helper only)."""
    logger.warning(
        "create_database_tables() is a no-op in production. "
        "Use migrations to manage schema."
    )
    db_client.create_tables()


def drop_database_tables():
    """Drop all database tables (development/test helper only)."""
    logger.warning(
        "drop_database_tables() is a no-op in production. "
        "Use migrations to manage schema."
    )
    db_client.drop_tables()


def check_database_health() -> bool:
    """Check database health"""
    return db_client.health_check()


def comprehensive_database_health_check() -> DatabaseHealthStatus:
    """Perform comprehensive database health check with metrics"""
    return db_client.comprehensive_health_check()


def startup_database_health_check() -> DatabaseHealthStatus:
    """Perform startup database health check with detailed validation"""
    return db_client.startup_health_check()


async def async_comprehensive_database_health_check() -> DatabaseHealthStatus:
    """Perform comprehensive async database health check with metrics"""
    return await db_client.async_comprehensive_health_check()


def get_database_connection_pool_metrics() -> ConnectionPoolMetrics:
    """Get current database connection pool metrics"""
    return db_client._get_connection_pool_metrics()


# Backwards-compatible accessor expected by optimized startup
def get_database_client() -> DatabaseClient:
    """Return the global DatabaseClient instance.

    Some parts of the startup system import `get_database_client` from
    ai_karen_engine.database.client. Provide this thin accessor to
    maintain compatibility with those callers.
    """
    return db_client
