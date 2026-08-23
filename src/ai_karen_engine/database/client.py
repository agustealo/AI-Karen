"""
Production Database Client
SQLAlchemy database connection management with async support
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager, asynccontextmanager
from typing import Generator, AsyncGenerator, Any, Optional
import time
from datetime import datetime
from dataclasses import dataclass, field

import os
from ai_karen_engine.core.memory.chat_memory_config import settings
from ai_karen_engine.database.models import Base
from ai_karen_engine.core.logging import get_logger

try:
    from ai_karen_engine.utils.error_formatter import ErrorFormatter, log_config_error
except ImportError:
    # Fallback if error formatter is not available
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
    """Production database client with connection pooling and async support"""
    
    def __init__(self):
        self.engine = None
        self.async_engine = None
        self.SessionLocal = None
        self.AsyncSessionLocal = None
        self._initialize_engine()
    
    def _initialize_engine(self):
        """Initialize SQLAlchemy engine with production settings"""
        
        try:
            # SQL echo controllable via env to avoid noisy logs in dev
            sql_echo_env = os.getenv("SQL_ECHO") or os.getenv("KAREN_SQL_ECHO")
            try:
                sql_echo = (
                    str(sql_echo_env).lower() in ("1", "true", "yes")
                ) if sql_echo_env is not None else False
            except Exception:
                sql_echo = False

            # Create synchronous engine with connection pooling
            # Ensure sync URL uses psycopg2 driver, not asyncpg
            sync_url = settings.database_url.replace('postgresql+asyncpg://', 'postgresql://')
            self.engine = create_engine(
                sync_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600,  # Recycle connections every hour
                echo=sql_echo,  # Controlled by env to avoid noise
            )

            # Create async engine
            async_url = settings.database_url if 'asyncpg' in settings.database_url else settings.database_url.replace('postgresql://', 'postgresql+asyncpg://')
            self.async_engine = create_async_engine(
                async_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=sql_echo,
            )
            
            # Create session factories
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            self.AsyncSessionLocal = async_sessionmaker(
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
                bind=self.async_engine,
                class_=AsyncSession
            )
            
            logger.info("Database engine initialized successfully")
            
        except Exception as e:
            # Use enhanced error formatting if available
            if ErrorFormatter and log_config_error:
                log_config_error(logger, e, ".env")
            else:
                # Enhanced fallback error message
                error_msg = f"❌ Database Engine Initialization Failed: {e}"
                
                if "Could not parse SQLAlchemy URL" in str(e):
                    error_msg += (
                        "\n\n🔧 SOLUTION: Fix your database configuration:\n"
                        "   1. Check your .env file for DATABASE_URL\n"
                        "   2. Ensure PostgreSQL is running:\n"
                        "      $ docker compose up -d postgres\n"
                        "   3. Verify the URL format:\n"
                        "      DATABASE_URL=postgresql://user:pass@host:port/dbname\n"
                        "\n"
                        f"ℹ️  Current DATABASE_URL: {getattr(settings, 'database_url', 'NOT SET')}"
                    )
                elif "Connection refused" in str(e):
                    error_msg += (
                        "\n\n🔧 SOLUTION: Start the database service:\n"
                        "   $ docker compose up -d postgres\n"
                        "   $ docker ps  # Check if postgres is running\n"
                        "\n"
                        "ℹ️  Make sure PostgreSQL is accessible on the configured port."
                    )
                else:
                    error_msg += (
                        "\n\n🔧 POSSIBLE SOLUTIONS:\n"
                        "   1. Check database configuration in .env\n"
                        "   2. Start database service: docker compose up -d postgres\n"
                        "   3. Verify database credentials and connectivity\n"
                    )
                
                logger.error(error_msg)
            raise
    
    def create_tables(self):
        """Create all database tables"""
        
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise

    async def cleanup(self):
        """Close database engines and free resources (async)."""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            
        if self.async_engine:
            try:
                # SQLAlchemy 2.0 async engine dispose is awaitable
                await self.async_engine.dispose()
                self.async_engine = None
            except Exception as e:
                logger.warning(f"Error during async engine disposal: {e}")

    def close(self):
        """Synchronous cleanup (best effort)."""
        if self.engine:
            self.engine.dispose()
            self.engine = None
        
        # We can't easily await here, so we log it
        if self.async_engine:
             logger.warning("Synchronous close() called on async database client. Use await cleanup() for full disposal.")
    
    def drop_tables(self):
        """Drop all database tables (use with caution!)"""
        
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.warning("All database tables dropped")
            
        except Exception as e:
            logger.error(f"Failed to drop database tables: {e}")
            raise
    
    def get_session(self) -> Session:
        """Get a new database session"""
        
        if not self.SessionLocal:
            raise RuntimeError("Database not initialized")
        
        return self.SessionLocal()
    
    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations"""
        
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def health_check(self) -> bool:
        """Check database connectivity"""
        
        try:
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            return True
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    def is_degraded(self) -> bool:
        """Return True if the database is not healthy."""
        return not self.health_check()
    
    def comprehensive_health_check(self) -> DatabaseHealthStatus:
        """Perform comprehensive database health check with metrics"""
        start_time = time.time()
        
        try:
            # Test basic connectivity
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Get connection pool metrics
            pool_metrics = self._get_connection_pool_metrics()
            
            # Log success without exposing credentials
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.info(f"Database health check passed - URL: {sanitized_url}, Response time: {response_time_ms:.2f}ms")
            
            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message="Database connection successful",
                response_time_ms=response_time_ms,
                connection_pool_metrics=pool_metrics
            )
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            # Log failure without exposing credentials
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.error(f"Database health check failed - URL: {sanitized_url}, Error: {error_msg}")
            
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Database connection failed: {error_msg}",
                response_time_ms=response_time_ms,
                error_details=error_msg
            )
    
    def startup_health_check(self) -> DatabaseHealthStatus:
        """Perform startup health check with detailed validation"""
        logger.info("Performing database startup health check...")
        
        start_time = time.time()
        checks = []
        
        try:
            # Check 1: Basic connectivity
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            checks.append("Basic connectivity: PASS")
            
            # Check 2: Database version and info
            with self.session_scope() as session:
                result = session.execute(text("SELECT version()")).fetchone()
                db_version = result[0] if result else "Unknown"
                checks.append(f"Database version check: PASS ({db_version[:50]}...)")
            
            # Check 3: Connection pool status
            pool_metrics = self._get_connection_pool_metrics()
            checks.append(f"Connection pool: PASS (size: {pool_metrics.pool_size}, active: {pool_metrics.checked_out})")
            
            # Check 4: Transaction test
            with self.session_scope() as session:
                session.execute(text("BEGIN"))
                session.execute(text("SELECT 1"))
                session.execute(text("COMMIT"))
            checks.append("Transaction test: PASS")
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Log detailed startup results
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.info("Database startup health check completed successfully:")
            logger.info(f"  - Database URL: {sanitized_url}")
            logger.info(f"  - Response time: {response_time_ms:.2f}ms")
            for check in checks:
                logger.info(f"  - {check}")
            
            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message=f"All startup checks passed ({len(checks)} checks)",
                response_time_ms=response_time_ms,
                connection_pool_metrics=pool_metrics
            )
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            # Log detailed failure information
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.error("Database startup health check failed:")
            logger.error(f"  - Database URL: {sanitized_url}")
            logger.error(f"  - Error: {error_msg}")
            logger.error(f"  - Response time: {response_time_ms:.2f}ms")
            for check in checks:
                logger.info(f"  - {check}")
            
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Startup health check failed: {error_msg}",
                response_time_ms=response_time_ms,
                error_details=error_msg
            )
    
    def _get_connection_pool_metrics(self) -> ConnectionPoolMetrics:
        """Get current connection pool metrics"""
        if not self.engine or not hasattr(self.engine, 'pool'):
            return ConnectionPoolMetrics()
        
        pool = self.engine.pool
        
        try:
            return ConnectionPoolMetrics(
                pool_size=getattr(pool, 'size', lambda: 0)(),
                checked_out=getattr(pool, 'checkedout', lambda: 0)(),
                overflow=getattr(pool, 'overflow', lambda: 0)(),
                checked_in=getattr(pool, 'checkedin', lambda: 0)(),
                total_connections=getattr(pool, 'size', lambda: 0)() + getattr(pool, 'overflow', lambda: 0)(),
                invalid_connections=getattr(pool, 'invalidated', lambda: 0)()
            )
        except Exception as e:
            logger.warning(f"Could not retrieve connection pool metrics: {e}")
            return ConnectionPoolMetrics()
    
    def _sanitize_database_url(self, url: str) -> str:
        """Sanitize database URL by removing credentials"""
        try:
            # Replace password with asterisks
            import re
            # Pattern to match postgresql://user:password@host:port/database
            pattern = r'(postgresql://[^:]+:)[^@]+(@.+)'
            sanitized = re.sub(pattern, r'\1****\2', url)
            return sanitized
        except Exception:
            # Fallback: just show the protocol and host info
            return "postgresql://****:****@[host]/[database]"
    
    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get async database session with automatic cleanup and commit."""
        if not self.AsyncSessionLocal:
            raise RuntimeError("Async database not initialized")
        
        async with self.AsyncSessionLocal() as session:
            yield session
            # The async_sessionmaker's context manager handles rollback/close on exception.
            # We only need to commit if everything succeeded.
            try:
                logger.debug("DatabaseClient: Attempting to commit async session")
                await session.commit()
                logger.debug("DatabaseClient: Async session committed successfully")
            except Exception as e:
                logger.error(f"DatabaseClient: Error committing async session: {e}", exc_info=True)
                await session.rollback()
                raise
    
    async_session_scope = get_async_session
    _get_pool_metrics = _get_connection_pool_metrics

    def initialize(self) -> None:
        """No-op compatibility method. DatabaseClient auto-initializes on instantiation."""
        return None
    
    async def async_health_check(self) -> bool:
        """Check database connectivity asynchronously"""
        
        try:
            async with self.get_async_session() as session:
                await session.execute(text("SELECT 1"))
            return True
            
        except Exception as e:
            logger.error(f"Async database health check failed: {e}")
            return False
    
    async def async_comprehensive_health_check(self) -> DatabaseHealthStatus:
        """Perform comprehensive async database health check with metrics"""
        start_time = time.time()
        
        try:
            # Test basic connectivity
            async with self.get_async_session() as session:
                await session.execute(text("SELECT 1"))
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Get connection pool metrics
            pool_metrics = self._get_connection_pool_metrics()
            
            # Log success without exposing credentials
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.info(f"Async database health check passed - URL: {sanitized_url}, Response time: {response_time_ms:.2f}ms")
            
            return DatabaseHealthStatus(
                is_healthy=True,
                status="healthy",
                message="Async database connection successful",
                response_time_ms=response_time_ms,
                connection_pool_metrics=pool_metrics
            )
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            # Log failure without exposing credentials
            sanitized_url = self._sanitize_database_url(settings.database_url)
            logger.error(f"Async database health check failed - URL: {sanitized_url}, Error: {error_msg}")
            
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Async database connection failed: {error_msg}",
                response_time_ms=response_time_ms,
                error_details=error_msg
            )
    
    def get_tenant_schema_name(self, tenant_id: str) -> str:
        """Get schema name for tenant (for multi-tenant support)"""
        return f"tenant_{tenant_id}"
    
    async def create_tables_async(self):
        """Create all database tables asynchronously"""
        
        try:
            async with self.async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully (async)")
            
        except Exception as e:
            logger.error(f"Failed to create database tables (async): {e}")
            raise


# Multi-tenant database client class
class MultiTenantPostgresClient(DatabaseClient):
    """Multi-tenant PostgreSQL client with async support and enhanced health monitoring"""
    
    def __init__(self, database_url: Optional[str] = None, **kwargs):
        """Initialize multi-tenant client with optional custom database URL"""
        # Store original settings database_url
        self._original_database_url = settings.database_url
        
        # Temporarily override settings if custom URL provided
        if database_url:
            settings.database_url = database_url
        
        try:
            super().__init__()
        finally:
            # Restore original settings
            if database_url:
                settings.database_url = self._original_database_url

    def get_sync_session(self) -> Session:
        """Compatibility wrapper for callers expecting an explicit sync session accessor."""
        return self.get_session()

    def create_shared_tables(self) -> None:
        """Create all shared application tables and persona persistence tables."""
        self.create_tables()
        self.create_persona_tables()

    def create_persona_tables(self) -> None:
        """Create persona-related persistence tables used by the chat personalization flow."""
        statements = [
            text(
                """
                CREATE TABLE IF NOT EXISTS custom_personas (
                    id VARCHAR(64) PRIMARY KEY,
                    tenant_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    system_prompt TEXT NOT NULL,
                    default_tone VARCHAR(32) NOT NULL,
                    default_verbosity VARCHAR(32) NOT NULL,
                    default_language VARCHAR(32) NOT NULL,
                    memory_weight VARCHAR(32) NOT NULL DEFAULT 'medium',
                    context_window_size INTEGER NOT NULL DEFAULT 10,
                    domain_knowledge TEXT NOT NULL DEFAULT '[]',
                    specialized_instructions TEXT,
                    use_emoji BOOLEAN NOT NULL DEFAULT FALSE,
                    formality_level FLOAT NOT NULL DEFAULT 0.5,
                    creativity_level FLOAT NOT NULL DEFAULT 0.5,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ),
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_personas_user_name
                ON custom_personas (tenant_id, user_id, lower(name))
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_custom_personas_user_lookup
                ON custom_personas (tenant_id, user_id, is_active)
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS user_persona_preferences (
                    tenant_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    active_persona_id VARCHAR(64),
                    default_tone VARCHAR(32) NOT NULL DEFAULT 'friendly',
                    default_verbosity VARCHAR(32) NOT NULL DEFAULT 'balanced',
                    default_language VARCHAR(32) NOT NULL DEFAULT 'en-US',
                    enable_style_adaptation BOOLEAN NOT NULL DEFAULT TRUE,
                    adaptation_sensitivity FLOAT NOT NULL DEFAULT 0.7,
                    enable_persona_memory_filtering BOOLEAN NOT NULL DEFAULT TRUE,
                    cross_persona_memory_sharing BOOLEAN NOT NULL DEFAULT FALSE,
                    show_persona_selector BOOLEAN NOT NULL DEFAULT TRUE,
                    show_style_controls BOOLEAN NOT NULL DEFAULT TRUE,
                    enable_quick_style_adjustments BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, user_id)
                )
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS persona_memory_entries (
                    id VARCHAR(64) PRIMARY KEY,
                    tenant_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    conversation_id VARCHAR(255),
                    persona_id VARCHAR(64),
                    persona_name VARCHAR(100),
                    tone_used VARCHAR(32),
                    verbosity_used VARCHAR(32),
                    content TEXT NOT NULL,
                    memory_type VARCHAR(64) NOT NULL DEFAULT 'chat_interaction',
                    importance_score FLOAT NOT NULL DEFAULT 0.5,
                    embedding_id VARCHAR(64),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP
                )
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_persona_memory_entries_user_lookup
                ON persona_memory_entries (tenant_id, user_id, created_at DESC)
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_persona_memory_entries_persona_lookup
                ON persona_memory_entries (tenant_id, persona_id, created_at DESC)
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_user_persona_preferences_active_persona
                ON user_persona_preferences (active_persona_id)
                """
            ),
        ]

        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'fk_user_persona_preferences_active_persona'
                        ) THEN
                            ALTER TABLE user_persona_preferences
                            ADD CONSTRAINT fk_user_persona_preferences_active_persona
                            FOREIGN KEY (active_persona_id)
                            REFERENCES custom_personas (id)
                            ON DELETE SET NULL;
                        END IF;
                    END
                    $$;
                    """
                )
            )
        logger.info("Shared persona tables created successfully")

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
            # Basic health check first
            basic_health = self.comprehensive_health_check()
            
            if not basic_health.is_healthy:
                return basic_health
            
            # If tenant_id provided, test tenant-specific operations
            if tenant_id:
                schema_name = self.get_tenant_schema_name(tenant_id)
                
                with self.session_scope() as session:
                    # Test tenant schema access (if it exists)
                    try:
                        session.execute(text(f"SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema_name}'"))
                        tenant_check = f"Tenant schema check for {tenant_id}: PASS"
                    except Exception as e:
                        tenant_check = f"Tenant schema check for {tenant_id}: WARNING - {str(e)}"
                
                response_time_ms = (time.time() - start_time) * 1000
                
                logger.info(f"Multi-tenant health check completed - {tenant_check}")
                
                return DatabaseHealthStatus(
                    is_healthy=True,
                    status="healthy",
                    message=f"Multi-tenant database connection successful. {tenant_check}",
                    response_time_ms=response_time_ms,
                    connection_pool_metrics=basic_health.connection_pool_metrics
                )
            
            return basic_health
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            logger.error(f"Multi-tenant health check failed: {error_msg}")
            
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Multi-tenant database connection failed: {error_msg}",
                response_time_ms=response_time_ms,
                error_details=error_msg
            )
    
    async def async_health_check_with_tenant_support(self, tenant_id: Optional[str] = None) -> DatabaseHealthStatus:
        """Perform async health check with optional tenant-specific validation"""
        start_time = time.time()
        
        try:
            # Basic async health check first
            basic_health = await self.async_comprehensive_health_check()
            
            if not basic_health.is_healthy:
                return basic_health
            
            # If tenant_id provided, test tenant-specific operations
            if tenant_id:
                schema_name = self.get_tenant_schema_name(tenant_id)
                
                async with self.get_async_session() as session:
                    # Test tenant schema access (if it exists)
                    try:
                        await session.execute(text(f"SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema_name}'"))
                        tenant_check = f"Tenant schema check for {tenant_id}: PASS"
                    except Exception as e:
                        tenant_check = f"Tenant schema check for {tenant_id}: WARNING - {str(e)}"
                
                response_time_ms = (time.time() - start_time) * 1000
                
                logger.info(f"Async multi-tenant health check completed - {tenant_check}")
                
                return DatabaseHealthStatus(
                    is_healthy=True,
                    status="healthy",
                    message=f"Async multi-tenant database connection successful. {tenant_check}",
                    response_time_ms=response_time_ms,
                    connection_pool_metrics=basic_health.connection_pool_metrics
                )
            
            return basic_health
            
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            logger.error(f"Async multi-tenant health check failed: {error_msg}")
            
            return DatabaseHealthStatus(
                is_healthy=False,
                status="unhealthy",
                message=f"Async multi-tenant database connection failed: {error_msg}",
                response_time_ms=response_time_ms,
                error_details=error_msg
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
    """Create all database tables"""
    db_client.create_tables()


def drop_database_tables():
    """Drop all database tables"""
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
