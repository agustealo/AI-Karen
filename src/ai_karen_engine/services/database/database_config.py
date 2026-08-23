# mypy: ignore-errors
"""
Database Configuration for FastAPI Server.
Handles database connection pool configuration, timeout settings, and graceful shutdown.
Enhanced with service-isolated connection pools to prevent LLM runtime caching interference.

DEPRECATED: Use ai_karen_engine.database.config.Settings instead.
This module remains for backwards compatibility during DATA-CONVERGE-1.
"""

import warnings
warnings.warn(
    "services.database.database_config is deprecated. "
    "Use ai_karen_engine.database.config.Settings instead.",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from enum import Enum

from ai_karen_engine.database.config import Settings

logger = logging.getLogger("kari.database")


class ServiceType(Enum):
    """Service types for connection pool isolation"""
    EXTENSION = "extension"
    LLM = "llm"
    AUTHENTICATION = "authentication"
    USAGE_TRACKING = "usage_tracking"
    BACKGROUND_TASKS = "background_tasks"
    DEFAULT = "default"


class DatabaseConfig:
    """Database configuration manager for FastAPI server with service isolation"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._database_manager = None
        self._database_health_monitor = None
        self._service_isolated_manager = None
        self._enhanced_health_monitor = None
        self._shutdown_event = asyncio.Event()
        self._graceful_shutdown_task: Optional[asyncio.Task] = None
        
        # Service-specific pool configurations to prevent LLM runtime interference
        self.service_pool_configs = {
            ServiceType.AUTHENTICATION: {
                "pool_size": 3,
                "max_overflow": 5,
                "pool_recycle": 900,  # 15 minutes - fastest recycle for auth
                "pool_pre_ping": True,
                "pool_timeout": 5,  # Fast timeout for auth
                "priority": "highest"
            },
            ServiceType.EXTENSION: {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 1800,  # 30 minutes
                "pool_pre_ping": True,
                "pool_timeout": 10,
                "priority": "high"
            },
            ServiceType.LLM: {
                "pool_size": 8,
                "max_overflow": 15,
                "pool_recycle": 3600,  # 1 hour - can handle longer operations
                "pool_pre_ping": True,
                "pool_timeout": 30,  # Longer timeout for LLM operations
                "priority": "medium"
            },
            ServiceType.USAGE_TRACKING: {
                "pool_size": 2,
                "max_overflow": 4,
                "pool_recycle": 1800,
                "pool_pre_ping": True,
                "pool_timeout": 15,
                "priority": "low"
            },
            ServiceType.BACKGROUND_TASKS: {
                "pool_size": 3,
                "max_overflow": 6,
                "pool_recycle": 2400,  # 40 minutes
                "pool_pre_ping": True,
                "pool_timeout": 20,
                "priority": "low"
            },
            ServiceType.DEFAULT: {
                "pool_size": self.settings.db_pool_size,
                "max_overflow": self.settings.db_max_overflow,
                "pool_recycle": self.settings.db_pool_recycle,
                "pool_pre_ping": self.settings.db_pool_pre_ping,
                "pool_timeout": 30,
                "priority": "medium"
            }
        }
        
    async def initialize_database(self) -> bool:
        """Initialize database connection with service-isolated configuration"""
        try:
            # Import here to avoid circular imports
            from ai_karen_engine.database.client import get_database_client
            from ai_karen_engine.services.database.health.monitor import (
                initialize_database_health_monitor,
                get_database_health_monitor,
            )

            # Quick connection test first - fail fast if DB is not available
            import asyncio
            try:
                test_result = await asyncio.wait_for(
                    self._test_db_availability(),
                    timeout=2.0  # Quick 2-second timeout
                )
                if not test_result:
                    logger.info("Database not available - skipping initialization (degraded mode)")
                    return False
            except asyncio.TimeoutError:
                logger.info("Database connection timeout - skipping initialization (degraded mode)")
                return False
            except Exception as e:
                logger.info(f"Database availability check failed: {e} - skipping initialization (degraded mode)")
                return False

            # Initialize service-isolated database manager first
            await self._initialize_service_isolated_manager()

            # Initialize canonical database client for backward compatibility
            self._database_manager = get_database_client()

            # Initialize database health monitor but DON'T start monitoring yet (lazy)
            self._database_health_monitor = await initialize_database_health_monitor(
                database_url=self.settings.database_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
                pool_recycle=self.settings.db_pool_recycle,
                pool_pre_ping=self.settings.db_pool_pre_ping,
                echo=self.settings.db_echo,
                health_check_interval=self.settings.db_health_check_interval,
                max_connection_failures=self.settings.db_max_connection_failures,
                connection_retry_delay=self.settings.db_connection_retry_delay,
                connection_timeout=self.settings.db_connection_timeout,
                query_timeout=self.settings.db_query_timeout,
                start_monitoring=False,  # Don't start monitoring at startup - lazy load
            )

            logger.info(
                "Database initialized (health monitoring deferred)",
                extra={
                    "service_pools": len(self.service_pool_configs),
                    "connection_timeout": self.settings.db_connection_timeout,
                }
            )

            # Ensure the default auth user and RBAC roles exist on every boot.
            # This is idempotent and keeps fresh databases from showing an empty
            # admin user table after startup.
            try:
                from ai_karen_engine.database.client import MultiTenantPostgresClient
                from ai_karen_engine.database.seed.auth_seed import seed_default_auth
                from ai_karen_engine.database.seed.rbac_seed import seed_default_roles

                seed_client = MultiTenantPostgresClient(
                    database_url=self.settings.database_url
                )
                with seed_client.session_scope() as session:
                    seed_default_auth(session)
                    seed_default_roles(session)
                logger.info("Default auth and RBAC seed data ensured")
            except Exception as e:
                logger.warning(f"Default auth seeding skipped or failed: {e}")

            return True

        except Exception as e:
            logger.warning(f"Database initialization failed (degraded mode): {e}")
            return False
    
    async def _test_db_availability(self) -> bool:
        """Quick test to check if database is available"""
        try:
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            def _sync_test():
                try:
                    from sqlalchemy import create_engine, text
                    from sqlalchemy.pool import NullPool

                    # Create a test engine with minimal configuration
                    engine = create_engine(
                        self.settings.database_url,
                        poolclass=NullPool,  # No pooling for test
                        connect_args={"connect_timeout": 1}
                    )

                    # Try a simple query
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))

                    engine.dispose()
                    return True
                except Exception:
                    return False

            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)
            result = await loop.run_in_executor(executor, _sync_test)
            executor.shutdown(wait=False)
            return result

        except Exception as e:
            logger.debug(f"Database availability test failed: {e}")
            return False

    async def _initialize_service_isolated_manager(self):
        """Initialize service-isolated database manager to prevent LLM runtime interference"""
        try:
            from .service_isolated_database import ServiceIsolatedDatabaseManager
            from .enhanced_database_health_monitor import initialize_enhanced_health_monitor

            self._service_isolated_manager = ServiceIsolatedDatabaseManager(
                database_url=self.settings.database_url,
                service_pool_configs=self.service_pool_configs
            )

            if not await self._service_isolated_manager.initialize():
                logger.info("Service-isolated database manager failed to initialize, falling back to shared pools")
                self._service_isolated_manager = None
            else:
                logger.info("Service-isolated database manager initialized")

                # Skip enhanced health monitor initialization at startup
                # It will be initialized lazily when needed

        except ImportError:
            logger.debug("Service-isolated database manager not available")
            self._service_isolated_manager = None
        except Exception as e:
            logger.info(f"Service-isolated database manager init failed: {e}")
            self._service_isolated_manager = None
    
    async def setup_graceful_shutdown(self):
        """Setup graceful shutdown handling for database connections"""
        if not self.settings.enable_graceful_shutdown:
            logger.info("Graceful shutdown disabled")
            return
            
        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            self._shutdown_event.set()
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        # Start graceful shutdown task
        self._graceful_shutdown_task = asyncio.create_task(
            self._graceful_shutdown_handler()
        )
        
        logger.info("Graceful shutdown handler configured")
    
    async def _graceful_shutdown_handler(self):
        """Handle graceful shutdown process"""
        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
            logger.info("Starting graceful shutdown process")
            
            # Give active connections time to complete
            await asyncio.sleep(2)
            
            # Close database connections
            if self._database_manager:
                logger.info("Closing database connections")
                await self._database_manager.close()
                
            logger.info("Graceful shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
    
    async def get_database_health(self) -> Dict[str, Any]:
        """Get comprehensive database health information including extension service isolation"""
        health_info = {
            "status": "not_initialized",
            "healthy": False,
            "error": "Database not initialized"
        }
        
        try:
            # Get health from service-isolated manager first (priority for extensions)
            if self._service_isolated_manager:
                try:
                    service_health = await self._service_isolated_manager.health_check_all()
                    health_info.update({
                        "service_isolation": {
                            "enabled": True,
                            "overall_health": service_health.get("overall_health", "unknown"),
                            "healthy_services": service_health.get("healthy_services", 0),
                            "total_services": service_health.get("total_services", 0),
                            "services": service_health.get("services", {}),
                        }
                    })
                    
                    # Check if extension service is healthy (critical for task requirements)
                    extension_health = service_health.get("services", {}).get("extension", {})
                    if extension_health.get("healthy", False):
                        health_info["status"] = "healthy"
                        health_info["healthy"] = True
                        health_info["extension_service_isolated"] = True
                    else:
                        health_info["status"] = "degraded"
                        health_info["healthy"] = False
                        health_info["extension_service_error"] = extension_health.get("error", "Unknown error")
                        
                except Exception as e:
                    logger.warning(f"Service-isolated health check failed: {e}")
                    health_info["service_isolation"] = {
                        "enabled": True,
                        "error": str(e)
                    }
            else:
                health_info["service_isolation"] = {
                    "enabled": False,
                    "reason": "Service-isolated manager not available"
                }
            
            # Get health from legacy database manager if available
            if self._database_manager:
                try:
                    manager_health = await self._database_manager._health_check()
                    health_info["legacy_manager"] = manager_health
                except Exception as e:
                    logger.warning(f"Database manager health check failed: {e}")
                    health_info["legacy_manager_error"] = str(e)
            
            # Get comprehensive health from database health monitor
            if self._database_health_monitor:
                try:
                    monitor_health = await self._database_health_monitor.check_health()
                    
                    health_info.update({
                        "monitor_status": monitor_health.status.value,
                        "monitor_connected": monitor_health.is_connected,
                        "response_time_ms": monitor_health.response_time,
                        "error_count": monitor_health.error_count,
                        "consecutive_failures": monitor_health.consecutive_failures,
                        "last_success": monitor_health.last_success.isoformat() if monitor_health.last_success else None,
                        "last_error": monitor_health.last_error,
                        "degraded_features": monitor_health.degraded_features,
                        "recovery_attempts": monitor_health.recovery_attempts,
                        "next_recovery_attempt": monitor_health.next_recovery_attempt.isoformat() if monitor_health.next_recovery_attempt else None,
                    })
                    
                    # Add pool information if available
                    if monitor_health.metrics:
                        health_info["pool_info"] = {
                            "pool_size": monitor_health.metrics.pool_size,
                            "active_connections": monitor_health.metrics.active_connections,
                            "idle_connections": monitor_health.metrics.idle_connections,
                            "checked_out": monitor_health.metrics.checked_out,
                            "overflow": monitor_health.metrics.overflow,
                            "invalidated": monitor_health.metrics.invalidated,
                            "pool_status": monitor_health.metrics.pool_status.value,
                            "query_success_rate": monitor_health.metrics.query_success_rate,
                        }
                    
                except Exception as e:
                    logger.warning(f"Database health monitor check failed: {e}")
                    health_info["monitor_error"] = str(e)
            
            # Add service-specific configuration information
            health_info["configuration"] = {
                "service_isolation_enabled": self._service_isolated_manager is not None,
                "service_pool_configs": {
                    service_type.value: config for service_type, config in self.service_pool_configs.items()
                },
                "legacy_pool_size": self.settings.db_pool_size,
                "legacy_max_overflow": self.settings.db_max_overflow,
                "connection_timeout": self.settings.db_connection_timeout,
                "query_timeout": self.settings.db_query_timeout,
                "pool_recycle": self.settings.db_pool_recycle,
                "pool_pre_ping": self.settings.db_pool_pre_ping,
                "health_check_interval": self.settings.db_health_check_interval,
                "max_connection_failures": self.settings.db_max_connection_failures,
                "connection_retry_delay": self.settings.db_connection_retry_delay,
            }
            
            return health_info
            
        except Exception as e:
            logger.error(f"Failed to get database health: {e}")
            return {
                "status": "error",
                "healthy": False,
                "error": str(e),
                "service_isolation": {
                    "enabled": self._service_isolated_manager is not None,
                    "error": "Health check failed"
                },
                "configuration": {
                    "service_isolation_enabled": False,
                    "pool_size": self.settings.db_pool_size,
                    "max_overflow": self.settings.db_max_overflow,
                    "connection_timeout": self.settings.db_connection_timeout,
                    "query_timeout": self.settings.db_query_timeout,
                }
            }
    
    async def test_database_connection(self) -> bool:
        """Test database connection with timeout"""
        if not self._database_manager:
            return False
            
        try:
            # Test connection with timeout
            return await asyncio.wait_for(
                self._database_manager.async_health_check(),
                timeout=self.settings.db_connection_timeout
            )
            
        except asyncio.TimeoutError:
            logger.error(f"Database connection test timed out after {self.settings.db_connection_timeout}s")
            return False
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def get_database_manager(self):
        """Get the database manager instance"""
        return self._database_manager
    
    def get_database_health_monitor(self):
        """Get the database health monitor instance"""
        return self._database_health_monitor
    
    def get_service_isolated_manager(self):
        """Get the service-isolated database manager instance"""
        return self._service_isolated_manager
    
    def get_enhanced_health_monitor(self):
        """Get the enhanced database health monitor instance"""
        return self._enhanced_health_monitor
    
    def get_service_connection_pool(self, service_type: ServiceType):
        """Get connection pool for specific service type"""
        if self._service_isolated_manager:
            return self._service_isolated_manager.get_service_engine(service_type)
        return None
    
    async def get_service_health(self, service_type: ServiceType) -> Dict[str, Any]:
        """Get health information for specific service"""
        if self._service_isolated_manager:
            return await self._service_isolated_manager.health_check(service_type)
        return {
            "service_type": service_type.value,
            "healthy": False,
            "error": "Service isolation not available"
        }
    
    async def get_extension_service_health_with_interference_detection(self) -> Dict[str, Any]:
        """Get comprehensive extension service health with LLM interference detection"""
        if self._enhanced_health_monitor:
            return await self._enhanced_health_monitor.get_current_health_with_extension_focus()
        return {
            "extension_service_isolated": False,
            "extension_service_healthy": False,
            "authentication_service_healthy": False,
            "overall_health": "unavailable",
            "error": "Enhanced health monitoring not available"
        }
    
    def optimize_connection_pools_for_extension_performance(self) -> Dict[str, Any]:
        """Optimize connection pool configurations specifically for extension API performance"""
        optimizations = []
        
        # Check current pool configurations
        extension_config = self.service_pool_configs.get(ServiceType.EXTENSION, {})
        auth_config = self.service_pool_configs.get(ServiceType.AUTHENTICATION, {})
        llm_config = self.service_pool_configs.get(ServiceType.LLM, {})
        
        # Optimization 1: Ensure extension pool has adequate size
        if extension_config.get("pool_size", 0) < 5:
            optimizations.append("Extension pool size should be at least 5 for adequate performance")
        
        # Optimization 2: Ensure auth pool has fast timeout
        if auth_config.get("pool_timeout", 30) > 10:
            optimizations.append("Authentication pool timeout should be ≤10 seconds for fast auth responses")
        
        # Optimization 3: Ensure auth pool has fast recycle
        if auth_config.get("pool_recycle", 3600) > 900:
            optimizations.append("Authentication pool recycle should be ≤15 minutes to prevent stale connections")
        
        # Optimization 4: Ensure LLM pool doesn't monopolize resources
        total_extension_auth_size = extension_config.get("pool_size", 0) + auth_config.get("pool_size", 0)
        llm_pool_size = llm_config.get("pool_size", 0)
        
        if llm_pool_size > total_extension_auth_size:
            optimizations.append("LLM pool size should not exceed combined extension+auth pool sizes")
        
        # Optimization 5: Check priority configuration
        if extension_config.get("priority") != "high":
            optimizations.append("Extension service should have 'high' priority")
        
        if auth_config.get("priority") != "highest":
            optimizations.append("Authentication service should have 'highest' priority")
        
        return {
            "optimizations_needed": len(optimizations) > 0,
            "optimization_count": len(optimizations),
            "optimizations": optimizations,
            "current_config": {
                "extension": extension_config,
                "authentication": auth_config,
                "llm": llm_config
            },
            "recommended_config": {
                "extension": {
                    "pool_size": max(5, extension_config.get("pool_size", 5)),
                    "max_overflow": max(10, extension_config.get("max_overflow", 10)),
                    "pool_timeout": 10,
                    "pool_recycle": 1800,
                    "priority": "high"
                },
                "authentication": {
                    "pool_size": max(3, auth_config.get("pool_size", 3)),
                    "max_overflow": max(5, auth_config.get("max_overflow", 5)),
                    "pool_timeout": 5,
                    "pool_recycle": 900,
                    "priority": "highest"
                },
                "llm": {
                    "pool_size": min(8, llm_config.get("pool_size", 8)),
                    "max_overflow": min(15, llm_config.get("max_overflow", 15)),
                    "pool_timeout": 30,
                    "pool_recycle": 3600,
                    "priority": "medium"
                }
            }
        }
    
    async def reset_connections(self):
        """Reset database connections for extension service recovery"""
        try:
            logger.info("Resetting database connections for extension service recovery")
            
            # Reset service-isolated connections if available
            if self._service_isolated_manager:
                await self._service_isolated_manager.reset_all_connections()
                logger.info("Service-isolated database connections reset")
            
            # Reset main database manager connections
            if self._database_manager:
                if hasattr(self._database_manager, 'reset_connections'):
                    await self._database_manager.reset_connections()
                    logger.info("Main database connections reset")
            
            # Reinitialize health monitoring
            if self._enhanced_health_monitor:
                # Stop and restart health monitoring
                await self._enhanced_health_monitor.stop_monitoring()
                await self._enhanced_health_monitor.start_monitoring()
                logger.info("Database health monitoring restarted")
            
            logger.info("Database connection reset completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to reset database connections: {e}")
            raise
    
    async def restart_extension_database_services(self):
        """Restart extension-specific database services for recovery"""
        try:
            logger.info("Restarting extension database services")
            
            # Reinitialize service-isolated manager
            if self._service_isolated_manager:
                await self._service_isolated_manager.close()
                
                # Recreate with fresh configuration
                from .service_isolated_database import ServiceIsolatedDatabaseManager
                self._service_isolated_manager = ServiceIsolatedDatabaseManager(
                    self.service_pool_configs
                )
                await self._service_isolated_manager.initialize()
                logger.info("Service-isolated database manager restarted")
            
            # Restart enhanced health monitoring with new manager
            if self._enhanced_health_monitor:
                await self._enhanced_health_monitor.stop_monitoring()
                
                from .enhanced_database_health_monitor import EnhancedDatabaseHealthMonitor
                self._enhanced_health_monitor = EnhancedDatabaseHealthMonitor(
                    self._service_isolated_manager
                )
                await self._enhanced_health_monitor.start_monitoring()
                logger.info("Enhanced database health monitoring restarted")
            
            logger.info("Extension database services restart completed")
            
        except Exception as e:
            logger.error(f"Failed to restart extension database services: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup database resources including service-isolated pools"""
        try:
            # Cancel graceful shutdown task
            if self._graceful_shutdown_task and not self._graceful_shutdown_task.done():
                self._graceful_shutdown_task.cancel()
                try:
                    await self._graceful_shutdown_task
                except asyncio.CancelledError:
                    pass
            
            # Shutdown enhanced health monitor first
            if self._enhanced_health_monitor:
                from .enhanced_database_health_monitor import shutdown_enhanced_health_monitor
                await shutdown_enhanced_health_monitor()
                self._enhanced_health_monitor = None
            
            # Close service-isolated manager
            if self._service_isolated_manager:
                await self._service_isolated_manager.close()
                self._service_isolated_manager = None
            
            # Close legacy database manager
            if self._database_manager:
                await self._database_manager.close()
            
            # Shutdown database health monitor
            if self._database_health_monitor:
                await self._database_health_monitor.cleanup()
                
            logger.info("Database configuration cleanup completed (including service isolation)")
            
        except Exception as e:
            logger.error(f"Error during database cleanup: {e}")


# Global database configuration instance
_database_config: Optional[DatabaseConfig] = None


def get_database_config(settings: Optional[Settings] = None) -> DatabaseConfig:
    """Get global database configuration instance"""
    global _database_config
    if _database_config is None:
        if settings is None:
            settings = Settings()
        _database_config = DatabaseConfig(settings)
    return _database_config


@asynccontextmanager
async def database_lifespan(settings: Settings):
    """Database lifespan context manager for FastAPI"""
    db_config = get_database_config(settings)
    
    try:
        # Initialize database
        logger.info("Initializing database configuration")
        await db_config.initialize_database()
        
        # Setup graceful shutdown
        await db_config.setup_graceful_shutdown()
        
        logger.info("Database configuration startup completed")
        yield db_config
        
    except Exception as e:
        logger.error(f"Database configuration startup failed: {e}")
        yield None
        
    finally:
        # Cleanup
        logger.info("Database configuration shutdown starting")
        await db_config.cleanup()
        logger.info("Database configuration shutdown completed")
