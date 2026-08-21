"""
Database Health Monitor

Comprehensive database connection health monitoring with:
- Real-time connection pool monitoring
- Automatic connection recovery mechanisms
- Health metrics collection and reporting
- Integration with ConnectionHealthManager
- Circuit breaker pattern for failed connections
- Graceful degradation support

Requirements: 4.3, 5.1, 5.4
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool, Pool
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError, OperationalError, TimeoutError as SQLTimeoutError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.resilience.connection_health_manager import (
    get_connection_health_manager,
    ConnectionType,
    ServiceStatus,
    RetryConfig,
)

logger = get_logger(__name__)


class DatabaseHealthStatus(str, Enum):
    """Database health status enumeration"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    MAINTENANCE = "maintenance"


class ConnectionPoolStatus(str, Enum):
    """Connection pool status enumeration"""
    OPTIMAL = "optimal"
    HIGH_USAGE = "high_usage"
    EXHAUSTED = "exhausted"
    ERROR = "error"


@dataclass
class DatabaseMetrics:
    """Database health metrics"""
    timestamp: datetime
    connection_count: int
    active_connections: int
    idle_connections: int
    pool_size: int
    max_overflow: int
    checked_out: int
    checked_in: int
    overflow: int
    invalidated: int
    response_time_ms: float
    query_success_rate: float
    error_count: int
    last_error: Optional[str] = None
    pool_status: ConnectionPoolStatus = ConnectionPoolStatus.OPTIMAL


@dataclass
class DatabaseHealth:
    """Comprehensive database health information"""
    is_connected: bool
    status: DatabaseHealthStatus
    response_time: float
    last_check: datetime
    error_count: int
    consecutive_failures: int
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    metrics: Optional[DatabaseMetrics] = None
    recovery_attempts: int = 0
    next_recovery_attempt: Optional[datetime] = None
    degraded_features: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DatabaseHealthMonitor:
    """
    Comprehensive database health monitoring system.
    
    Provides:
    - Real-time connection pool monitoring
    - Automatic connection recovery
    - Health metrics collection
    - Circuit breaker pattern
    - Graceful degradation
    """

    def __init__(
        self,
        database_url: str,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo: bool = False,
        health_check_interval: int = 30,
        max_connection_failures: int = 5,
        connection_retry_delay: int = 5,
        connection_timeout: int = 45,
        query_timeout: int = 30,
    ):
        self.database_url = database_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo
        self.health_check_interval = health_check_interval
        self.max_connection_failures = max_connection_failures
        self.connection_retry_delay = connection_retry_delay
        self.connection_timeout = connection_timeout
        self.query_timeout = query_timeout

        # Database engines and sessions
        self.engine = None
        self.async_engine = None
        self.SessionLocal = None
        self.AsyncSessionLocal = None

        # Health monitoring state
        self._health_status = DatabaseHealth(
            is_connected=False,
            status=DatabaseHealthStatus.UNAVAILABLE,
            response_time=0.0,
            last_check=datetime.utcnow(),
            error_count=0,
            consecutive_failures=0,
        )

        # Monitoring control
        self._monitoring_task: Optional[asyncio.Task] = None
        self._recovery_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._health_callbacks: List[Callable[[DatabaseHealth], None]] = []
        
        # Thread pool for sync operations
        self._thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db_health")
        
        # Metrics collection
        self._metrics_history: List[DatabaseMetrics] = []
        self._max_metrics_history = 100
        
        # Connection health manager integration
        self._connection_health_manager = get_connection_health_manager()
        
        # Recovery configuration
        self._retry_config = RetryConfig(
            max_retries=self.max_connection_failures,
            base_delay=float(self.connection_retry_delay),
            max_delay=300.0,  # 5 minutes max delay
            exponential_base=2.0,
            jitter=True,
            circuit_breaker_threshold=self.max_connection_failures,
            circuit_breaker_timeout=600.0,  # 10 minutes
        )

    async def initialize(self) -> bool:
        """Initialize database health monitor"""
        try:
            # Create database engines
            await self._create_engines()
            
            # Create session factories
            await self._create_session_factories()
            
            # Setup connection pool event listeners
            self._setup_pool_listeners()
            
            # Perform initial health check
            health = await self._perform_health_check()
            
            if health.is_connected:
                logger.info("Database health monitor initialized successfully")
                
                # Register with connection health manager
                self._connection_health_manager.register_service(
                    service_name="database_health_monitor",
                    connection_type=ConnectionType.DATABASE,
                    health_check_func=self._health_check_for_manager,
                    degraded_mode_callback=self._on_degraded_mode,
                    recovery_callback=self._on_recovery,
                )
                
                return True
            else:
                logger.info("Database health monitor initialized but database is not available")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize database health monitor: {e}")
            self._health_status.status = DatabaseHealthStatus.UNAVAILABLE
            self._health_status.last_error = str(e)
            return False

    async def _create_engines(self):
        """Create SQLAlchemy engines with health monitoring configuration"""
        try:
            # Create synchronous engine
            self.engine = create_engine(
                self.database_url,
                poolclass=QueuePool,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_pre_ping=self.pool_pre_ping,
                pool_recycle=self.pool_recycle,
                echo=self.echo,
                connect_args={
                    "connect_timeout": self.connection_timeout,
                    "command_timeout": self.query_timeout,
                }
            )

            # Create async engine
            async_url = self.database_url.replace('postgresql://', 'postgresql+asyncpg://')
            self.async_engine = create_async_engine(
                async_url,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_pre_ping=self.pool_pre_ping,
                pool_recycle=self.pool_recycle,
                echo=self.echo,
                connect_args={
                    "server_settings": {
                        "statement_timeout": str(self.query_timeout * 1000),  # milliseconds
                    }
                }
            )

            logger.debug("Database engines created for health monitoring")

        except Exception as e:
            logger.error(f"Failed to create database engines: {e}")
            raise

    async def _create_session_factories(self):
        """Create session factories"""
        if not self.engine or not self.async_engine:
            raise RuntimeError("Database engines not initialized")

        try:
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )

            self.AsyncSessionLocal = async_sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.async_engine,
                class_=AsyncSession
            )

            logger.debug("Database session factories created for health monitoring")

        except Exception as e:
            logger.error(f"Failed to create session factories: {e}")
            raise

    def _setup_pool_listeners(self):
        """Setup SQLAlchemy pool event listeners for monitoring"""
        if not self.engine:
            return

        @event.listens_for(self.engine, "connect")
        def on_connect(dbapi_connection, connection_record):
            """Handle new database connections"""
            logger.debug("New database connection established")

        @event.listens_for(self.engine, "checkout")
        def on_checkout(dbapi_connection, connection_record, connection_proxy):
            """Handle connection checkout from pool"""
            logger.debug("Database connection checked out from pool")

        @event.listens_for(self.engine, "checkin")
        def on_checkin(dbapi_connection, connection_record):
            """Handle connection checkin to pool"""
            logger.debug("Database connection checked in to pool")

        @event.listens_for(self.engine, "invalidate")
        def on_invalidate(dbapi_connection, connection_record, exception):
            """Handle connection invalidation"""
            logger.warning(f"Database connection invalidated: {exception}")
            self._health_status.error_count += 1

    async def start_monitoring(self) -> None:
        """Start background health monitoring"""
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("Database health monitoring already running")
            return

        self._shutdown_event.clear()
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Database health monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop background health monitoring"""
        self._shutdown_event.set()
        
        # Cancel monitoring task
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        # Cancel recovery task
        if self._recovery_task:
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass

        logger.info("Database health monitoring stopped")

    def on_health_change(self, callback: Callable[[DatabaseHealth], None]) -> None:
        """Register callback for health status changes"""
        self._health_callbacks.append(callback)

    async def check_health(self) -> DatabaseHealth:
        """Perform immediate health check"""
        return await self._perform_health_check()

    async def _perform_health_check(self) -> DatabaseHealth:
        """Perform comprehensive database health check"""
        start_time = time.time()
        
        try:
            # Test sync connection
            sync_success = await self._test_sync_connection()
            
            # Test async connection
            async_success = await self._test_async_connection()
            
            # Collect pool metrics
            metrics = await self._collect_metrics()
            
            response_time = (time.time() - start_time) * 1000  # milliseconds
            
            # Determine overall health
            is_connected = sync_success and async_success
            
            if is_connected:
                status = DatabaseHealthStatus.HEALTHY
                self._health_status.consecutive_failures = 0
                self._health_status.last_success = datetime.utcnow()
                self._health_status.last_error = None
            else:
                self._health_status.consecutive_failures += 1
                if self._health_status.consecutive_failures >= self.max_connection_failures:
                    status = DatabaseHealthStatus.UNAVAILABLE
                else:
                    status = DatabaseHealthStatus.DEGRADED

            # Update health status
            self._health_status = DatabaseHealth(
                is_connected=is_connected,
                status=status,
                response_time=response_time,
                last_check=datetime.utcnow(),
                error_count=self._health_status.error_count,
                consecutive_failures=self._health_status.consecutive_failures,
                last_success=self._health_status.last_success,
                last_error=self._health_status.last_error,
                metrics=metrics,
                recovery_attempts=self._health_status.recovery_attempts,
                next_recovery_attempt=self._health_status.next_recovery_attempt,
                degraded_features=self._get_degraded_features(status),
                metadata={
                    "sync_connection": sync_success,
                    "async_connection": async_success,
                    "pool_size": self.pool_size,
                    "max_overflow": self.max_overflow,
                }
            )

            # Store metrics
            if metrics:
                self._metrics_history.append(metrics)
                if len(self._metrics_history) > self._max_metrics_history:
                    self._metrics_history.pop(0)

            # Notify callbacks of health changes
            await self._notify_health_callbacks()

            return self._health_status

        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            self._health_status.error_count += 1
            self._health_status.consecutive_failures += 1
            self._health_status.last_error = error_msg
            self._health_status.response_time = response_time
            self._health_status.last_check = datetime.utcnow()
            self._health_status.status = DatabaseHealthStatus.UNAVAILABLE
            self._health_status.degraded_features = self._get_degraded_features(DatabaseHealthStatus.UNAVAILABLE)

            logger.error(f"Database health check failed: {error_msg}")
            await self._notify_health_callbacks()
            
            return self._health_status

    async def _test_sync_connection(self) -> bool:
        """Test synchronous database connection"""
        try:
            def sync_test():
                with self.SessionLocal() as session:
                    result = session.execute(text("SELECT 1 as test"))
                    return result.scalar() == 1

            # Run sync operation in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(self._thread_pool, sync_test)
            return result

        except Exception as e:
            logger.debug(f"Sync connection test failed: {e}")
            return False

    async def _test_async_connection(self) -> bool:
        """Test asynchronous database connection"""
        try:
            async with self.AsyncSessionLocal() as session:
                result = await session.execute(text("SELECT 1 as test"))
                return result.scalar() == 1

        except Exception as e:
            logger.debug(f"Async connection test failed: {e}")
            return False

    async def _collect_metrics(self) -> Optional[DatabaseMetrics]:
        """Collect database connection pool metrics"""
        try:
            if not self.engine or not hasattr(self.engine, 'pool'):
                return None

            pool = self.engine.pool
            
            # Get pool statistics
            pool_size = getattr(pool, 'size', lambda: 0)()
            checked_out = getattr(pool, 'checkedout', lambda: 0)()
            overflow = getattr(pool, 'overflow', lambda: 0)()
            checked_in = getattr(pool, 'checkedin', lambda: 0)()
            invalidated = getattr(pool, 'invalidated', lambda: 0)()

            # Calculate derived metrics
            active_connections = checked_out
            idle_connections = checked_in
            total_connections = active_connections + idle_connections

            # Determine pool status
            pool_usage_ratio = checked_out / (pool_size + self.max_overflow) if (pool_size + self.max_overflow) > 0 else 0
            
            if pool_usage_ratio >= 0.9:
                pool_status = ConnectionPoolStatus.EXHAUSTED
            elif pool_usage_ratio >= 0.7:
                pool_status = ConnectionPoolStatus.HIGH_USAGE
            else:
                pool_status = ConnectionPoolStatus.OPTIMAL

            # Calculate success rate (simplified)
            total_checks = len(self._metrics_history) + 1
            successful_checks = sum(1 for m in self._metrics_history if m.query_success_rate > 0.9) + (1 if self._health_status.is_connected else 0)
            query_success_rate = successful_checks / total_checks if total_checks > 0 else 0.0

            return DatabaseMetrics(
                timestamp=datetime.utcnow(),
                connection_count=total_connections,
                active_connections=active_connections,
                idle_connections=idle_connections,
                pool_size=pool_size,
                max_overflow=self.max_overflow,
                checked_out=checked_out,
                checked_in=checked_in,
                overflow=overflow,
                invalidated=invalidated,
                response_time_ms=self._health_status.response_time,
                query_success_rate=query_success_rate,
                error_count=self._health_status.error_count,
                last_error=self._health_status.last_error,
                pool_status=pool_status,
            )

        except Exception as e:
            logger.debug(f"Failed to collect database metrics: {e}")
            return None

    def _get_degraded_features(self, status: DatabaseHealthStatus) -> List[str]:
        """Get list of features that should be disabled based on health status"""
        if status == DatabaseHealthStatus.HEALTHY:
            return []
        elif status == DatabaseHealthStatus.DEGRADED:
            return [
                "complex_queries",
                "batch_operations",
                "reporting",
            ]
        else:  # UNAVAILABLE
            return [
                "data_persistence",
                "user_management",
                "audit_logging",
                "session_storage",
                "memory_metadata",
                "complex_queries",
                "batch_operations",
                "reporting",
            ]

    async def _notify_health_callbacks(self):
        """Notify registered callbacks of health status changes"""
        for callback in self._health_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._health_status)
                else:
                    callback(self._health_status)
            except Exception as e:
                logger.error(f"Error executing health callback: {e}")

    async def _monitoring_loop(self):
        """Background monitoring loop"""
        while not self._shutdown_event.is_set():
            try:
                # Perform health check
                await self._perform_health_check()
                
                # Start recovery if needed
                if (self._health_status.status in [DatabaseHealthStatus.DEGRADED, DatabaseHealthStatus.UNAVAILABLE] 
                    and not self._recovery_task):
                    self._recovery_task = asyncio.create_task(self._recovery_loop())

                # Wait for next check
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), 
                        timeout=self.health_check_interval
                    )
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue monitoring

            except Exception as e:
                logger.error(f"Error in database health monitoring loop: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying

    async def _recovery_loop(self):
        """Automatic connection recovery loop"""
        recovery_attempt = 0
        
        while (not self._shutdown_event.is_set() 
               and self._health_status.status != DatabaseHealthStatus.HEALTHY):
            try:
                recovery_attempt += 1
                self._health_status.recovery_attempts = recovery_attempt
                
                logger.info(f"Attempting database recovery (attempt {recovery_attempt})")
                
                # Calculate delay with exponential backoff
                delay = min(
                    self._retry_config.base_delay * (self._retry_config.exponential_base ** (recovery_attempt - 1)),
                    self._retry_config.max_delay
                )
                
                # Add jitter
                if self._retry_config.jitter:
                    import random
                    jitter = random.uniform(0.1, 0.3) * delay
                    delay += jitter
                
                self._health_status.next_recovery_attempt = datetime.utcnow() + timedelta(seconds=delay)
                
                # Wait before recovery attempt
                await asyncio.sleep(delay)
                
                # Attempt recovery
                if await self._attempt_recovery():
                    logger.info(f"Database recovery successful after {recovery_attempt} attempts")
                    break
                else:
                    logger.warning(f"Database recovery attempt {recovery_attempt} failed")
                    
                    # Check if we've exceeded max attempts
                    if recovery_attempt >= self._retry_config.max_retries:
                        logger.error(f"Database recovery failed after {recovery_attempt} attempts")
                        break

            except Exception as e:
                logger.error(f"Error in database recovery loop: {e}")
                await asyncio.sleep(5)

        # Clear recovery task
        self._recovery_task = None

    async def _attempt_recovery(self) -> bool:
        """Attempt to recover database connection"""
        try:
            # Close existing connections
            await self._close_connections()
            
            # Recreate engines and sessions
            await self._create_engines()
            await self._create_session_factories()
            self._setup_pool_listeners()
            
            # Test connections
            health = await self._perform_health_check()
            
            return health.is_connected

        except Exception as e:
            logger.error(f"Database recovery attempt failed: {e}")
            return False

    async def _close_connections(self):
        """Close all database connections"""
        try:
            if self.async_engine:
                await self.async_engine.dispose()
                self.async_engine = None

            if self.engine:
                await asyncio.get_event_loop().run_in_executor(
                    self._thread_pool, 
                    self.engine.dispose
                )
                self.engine = None

            self.SessionLocal = None
            self.AsyncSessionLocal = None

        except Exception as e:
            logger.warning(f"Error closing database connections: {e}")

    async def _health_check_for_manager(self) -> Dict[str, Any]:
        """Health check function for connection health manager"""
        health = await self._perform_health_check()
        
        return {
            "healthy": health.is_connected,
            "status": health.status.value,
            "response_time_ms": health.response_time,
            "error_count": health.error_count,
            "consecutive_failures": health.consecutive_failures,
            "degraded_features": health.degraded_features,
            "pool_metrics": health.metrics.__dict__ if health.metrics else {},
            "metadata": health.metadata,
        }

    async def _on_degraded_mode(self, service_name: str):
        """Callback when service enters degraded mode"""
        logger.warning(f"Database health monitor entering degraded mode: {service_name}")
        self._health_status.status = DatabaseHealthStatus.DEGRADED

    async def _on_recovery(self, service_name: str):
        """Callback when service recovers"""
        logger.info(f"Database health monitor recovered: {service_name}")
        self._health_status.status = DatabaseHealthStatus.HEALTHY

    def get_current_health(self) -> DatabaseHealth:
        """Get current health status"""
        return self._health_status

    def get_metrics_history(self) -> List[DatabaseMetrics]:
        """Get historical metrics"""
        return list(self._metrics_history)

    def get_pool_status(self) -> Dict[str, Any]:
        """Get current connection pool status"""
        if not self._health_status.metrics:
            return {"status": "unknown"}
        
        metrics = self._health_status.metrics
        return {
            "status": metrics.pool_status.value,
            "pool_size": metrics.pool_size,
            "active_connections": metrics.active_connections,
            "idle_connections": metrics.idle_connections,
            "checked_out": metrics.checked_out,
            "overflow": metrics.overflow,
            "invalidated": metrics.invalidated,
            "usage_ratio": metrics.checked_out / (metrics.pool_size + self.max_overflow) if (metrics.pool_size + self.max_overflow) > 0 else 0,
        }

    async def cleanup(self):
        """Cleanup resources"""
        try:
            # Stop monitoring
            await self.stop_monitoring()
            
            # Close connections
            await self._close_connections()
            
            # Shutdown thread pool
            self._thread_pool.shutdown(wait=True)
            
            logger.info("Database health monitor cleanup completed")

        except Exception as e:
            logger.error(f"Error during database health monitor cleanup: {e}")


# Global instance
_database_health_monitor: Optional[DatabaseHealthMonitor] = None


def get_database_health_monitor() -> Optional[DatabaseHealthMonitor]:
    """Get global database health monitor instance"""
    return _database_health_monitor


async def initialize_database_health_monitor(
    database_url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 3600,
    pool_pre_ping: bool = True,
    echo: bool = False,
    health_check_interval: int = 30,
    max_connection_failures: int = 5,
    connection_retry_delay: int = 5,
    connection_timeout: int = 45,
    query_timeout: int = 30,
    start_monitoring: bool = True,
) -> DatabaseHealthMonitor:
    """Initialize and start the global database health monitor"""
    global _database_health_monitor
    
    _database_health_monitor = DatabaseHealthMonitor(
        database_url=database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
        health_check_interval=health_check_interval,
        max_connection_failures=max_connection_failures,
        connection_retry_delay=connection_retry_delay,
        connection_timeout=connection_timeout,
        query_timeout=query_timeout,
    )
    
    # Initialize the monitor
    await _database_health_monitor.initialize()
    
    # Start monitoring if requested
    if start_monitoring:
        await _database_health_monitor.start_monitoring()
    
    return _database_health_monitor


async def shutdown_database_health_monitor():
    """Shutdown the global database health monitor"""
    global _database_health_monitor
    if _database_health_monitor:
        await _database_health_monitor.cleanup()
        _database_health_monitor = None
