"""Canonical PostgreSQL engine and session management.

Single source of truth for SQLAlchemy engine creation, connection pooling,
and session lifecycle. All database consumers converge through this module.

Replaces the duplicated engine creation previously scattered across
18+ MultiTenantPostgresClient instantiation sites.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from ai_karen_engine.config.database import get_database_settings

logger = logging.getLogger(__name__)


@dataclass
class ConnectionPoolMetrics:
    pool_size: int = 0
    checked_out: int = 0
    overflow: int = 0
    checked_in: int = 0
    total_connections: int = 0
    invalid_connections: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DatabaseHealthStatus:
    is_healthy: bool
    status: str
    message: str
    response_time_ms: float
    connection_pool_metrics: Optional[ConnectionPoolMetrics] = None
    last_check: datetime = field(default_factory=datetime.utcnow)
    error_details: Optional[str] = None


class PostgresEngine:
    """Canonical PostgreSQL engine singleton.

    Creates and owns exactly one sync and one async SQLAlchemy engine.
    All session factories derive from these engines.
    """

    def __init__(self) -> None:
        self._settings = get_database_settings()
        self._postgres = self._settings.postgres
        self._pool = self._settings.pool

        self._engine = None
        self._async_engine = None
        self._session_factory = None
        self._async_session_factory = None

    def initialize(self) -> None:
        """Create engines and session factories. Idempotent."""
        if self._engine is not None:
            return

        database_url = self._postgres.build_database_url()
        async_url = self._postgres.build_async_database_url()

        sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

        echo = self._pool.echo_sql
        pool_pre_ping = self._pool.pool_pre_ping

        self._engine = create_engine(
            sync_url,
            poolclass=QueuePool,
            pool_size=self._pool.pool_size,
            max_overflow=self._pool.max_overflow,
            pool_timeout=self._pool.pool_timeout,
            pool_recycle=self._pool.pool_recycle,
            pool_pre_ping=pool_pre_ping,
            echo=echo,
        )

        self._async_engine = create_async_engine(
            async_url,
            pool_size=self._pool.pool_size,
            max_overflow=self._pool.max_overflow,
            pool_timeout=self._pool.pool_timeout,
            pool_recycle=self._pool.pool_recycle,
            pool_pre_ping=pool_pre_ping,
            echo=echo,
        )

        self._session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine,
        )

        self._async_session_factory = async_sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self._async_engine,
            class_=AsyncSession,
        )

        logger.info("Canonical PostgresEngine initialized")

    @property
    def engine(self):
        if self._engine is None:
            self.initialize()
        return self._engine

    @property
    def async_engine(self):
        if self._async_engine is None:
            self.initialize()
        return self._async_engine

    @property
    def session_factory(self):
        if self._session_factory is None:
            self.initialize()
        return self._session_factory

    @property
    def async_session_factory(self):
        if self._async_session_factory is None:
            self.initialize()
        return self._async_session_factory

    def get_session(self) -> Session:
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.async_session_factory() as session:
            yield session
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async_session_scope = get_async_session

    def health_check(self) -> bool:
        try:
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return False

    def is_degraded(self) -> bool:
        return not self.health_check()

    def comprehensive_health_check(self) -> DatabaseHealthStatus:
        start = time.time()
        try:
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            elapsed = (time.time() - start) * 1000
            pool = self._get_pool_metrics()
            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message="Database connection successful",
                response_time_ms=elapsed,
                connection_pool_metrics=pool,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Database connection failed: {e}",
                response_time_ms=elapsed,
                error_details=str(e),
            )

    async def async_health_check(self) -> bool:
        try:
            async with self.get_async_session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Async health check failed: %s", e)
            return False

    async def async_comprehensive_health_check(self) -> DatabaseHealthStatus:
        start = time.time()
        try:
            async with self.get_async_session() as session:
                await session.execute(text("SELECT 1"))
            elapsed = (time.time() - start) * 1000
            pool = self._get_pool_metrics()
            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message="Async database connection successful",
                response_time_ms=elapsed,
                connection_pool_metrics=pool,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Async database connection failed: {e}",
                response_time_ms=elapsed,
                error_details=str(e),
            )

    def startup_health_check(self) -> DatabaseHealthStatus:
        logger.info("Performing database startup health check...")
        start = time.time()
        checks = []
        try:
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            checks.append("Basic connectivity: PASS")

            with self.session_scope() as session:
                result = session.execute(text("SELECT version()")).fetchone()
                version = result[0] if result else "Unknown"
                checks.append(f"Database version check: PASS ({version[:50]}...)")

            pool = self._get_pool_metrics()
            checks.append(
                f"Connection pool: PASS (size: {pool.pool_size}, "
                f"active: {pool.checked_out})"
            )

            with self.session_scope() as session:
                session.execute(text("BEGIN"))
                session.execute(text("SELECT 1"))
                session.execute(text("COMMIT"))
            checks.append("Transaction test: PASS")

            elapsed = (time.time() - start) * 1000
            logger.info("Database startup health check completed successfully")
            for check in checks:
                logger.info("  - %s", check)

            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message=f"All startup checks passed ({len(checks)} checks)",
                response_time_ms=elapsed,
                connection_pool_metrics=pool,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error("Database startup health check failed: %s", e)
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Startup health check failed: {e}",
                response_time_ms=elapsed,
                error_details=str(e),
            )

    def _get_pool_metrics(self) -> ConnectionPoolMetrics:
        eng = self._engine
        if eng is None or not hasattr(eng, "pool"):
            return ConnectionPoolMetrics()
        pool = eng.pool
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
        except Exception as e:
            logger.warning("Could not retrieve pool metrics: %s", e)
            return ConnectionPoolMetrics()

    async def cleanup(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        if self._async_engine is not None:
            try:
                await self._async_engine.dispose()
            except Exception as e:
                logger.warning("Error during async engine disposal: %s", e)
            self._async_engine = None
        self._session_factory = None
        self._async_session_factory = None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        if self._async_engine is not None:
            logger.warning(
                "Synchronous close() called. Use 'await cleanup()' for full disposal."
            )

    @staticmethod
    def get_tenant_schema_name(tenant_id: str) -> str:
        return f"tenant_{tenant_id}"


_engine_instance: Optional[PostgresEngine] = None


def get_postgres_engine() -> PostgresEngine:
    """Return the canonical PostgresEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PostgresEngine()
    return _engine_instance


def refresh_postgres_engine() -> PostgresEngine:
    """Dispose and recreate the canonical PostgresEngine."""
    global _engine_instance
    if _engine_instance is not None:
        _engine_instance.close()
    _engine_instance = PostgresEngine()
    return _engine_instance


__all__ = [
    "PostgresEngine",
    "ConnectionPoolMetrics",
    "DatabaseHealthStatus",
    "get_postgres_engine",
    "refresh_postgres_engine",
]
