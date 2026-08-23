"""
Database Health Checker

Comprehensive health checker that validates PostgreSQL and Redis connections.
Integrates with all database validation services to provide a unified health status.

Requirements: 2.1
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.client import get_database_client
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager
from ai_karen_engine.services.database_consistency_validator import (
    get_database_consistency_validator,
    ValidationStatus,
    DatabaseType,
)
from ai_karen_engine.services.migration_validator import (
    get_migration_validator,
    MigrationStatus,
)

logger = get_logger(__name__)


class OverallHealthStatus(str, Enum):
    """Overall health status enumeration"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    OFFLINE = "offline"


@dataclass
class DatabaseConnectionStatus:
    """Individual database connection status"""

    database: DatabaseType
    is_connected: bool
    response_time_ms: float
    status: ValidationStatus
    version: Optional[str] = None
    connection_count: Optional[int] = None
    error_message: Optional[str] = None
    degraded_mode: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """Complete health check result"""

    timestamp: datetime
    overall_status: OverallHealthStatus
    database_connections: List[DatabaseConnectionStatus]
    migration_status: MigrationStatus
    consistency_issues: int
    critical_issues: int
    warning_issues: int
    recommendations: List[str]
    performance_metrics: Dict[str, Any]
    uptime_seconds: float
    errors: List[str] = field(default_factory=list)


class DatabaseHealthChecker:
    """
    Comprehensive database health checker.

    Provides:
    - Connection health monitoring for all databases
    - Migration status validation
    - Consistency checking
    - Performance metrics
    - Unified health reporting
    """

    def __init__(self):
        # Database managers
        self.db_client = get_database_client()
        self.redis_manager = get_redis_manager()

        # Validation services
        self.consistency_validator = get_database_consistency_validator()
        self.migration_validator = get_migration_validator()

        # Health check state
        self._start_time = time.time()
        self._last_health_check: Optional[HealthCheckResult] = None

    async def initialize(self) -> bool:
        """Initialize health checker and perform initial check"""
        logger.info("Initializing Database Health Checker")
        try:
            await self.check_health()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database health checker: {e}")
            return False

    async def check_health(
        self, include_detailed_validation: bool = False
    ) -> HealthCheckResult:
        """
        Perform comprehensive database health check.

        Args:
            include_detailed_validation: Whether to include detailed consistency validation

        Returns:
            HealthCheckResult: Complete health check result
        """
        logger.info("Starting comprehensive database health check")
        start_time = time.time()

        errors = []
        recommendations = []

        try:
            # Check individual database connections
            db_connections = await self._check_database_connections()

            # Check migration status
            migration_status = await self._check_migration_status()

            # Perform consistency validation if requested
            consistency_issues = 0
            critical_issues = 0
            warning_issues = 0

            if include_detailed_validation:
                consistency_report = await self.consistency_validator.validate_all()
                consistency_issues = len(consistency_report.validation_issues)
                critical_issues = len(
                    [
                        i
                        for i in consistency_report.validation_issues
                        if i.severity == ValidationStatus.CRITICAL
                    ]
                )
                warning_issues = len(
                    [
                        i
                        for i in consistency_report.validation_issues
                        if i.severity == ValidationStatus.WARNING
                    ]
                )
                recommendations.extend(consistency_report.cleanup_recommendations)

            # Collect performance metrics
            performance_metrics = await self._collect_performance_metrics()

            # Determine overall health status
            overall_status = self._determine_overall_status(
                db_connections, migration_status, critical_issues
            )

            # Generate recommendations
            recommendations.extend(
                self._generate_health_recommendations(
                    db_connections, migration_status, critical_issues, warning_issues
                )
            )

            # Calculate uptime
            uptime_seconds = time.time() - self._start_time

            result = HealthCheckResult(
                timestamp=datetime.utcnow(),
                overall_status=overall_status,
                database_connections=db_connections,
                migration_status=migration_status,
                consistency_issues=consistency_issues,
                critical_issues=critical_issues,
                warning_issues=warning_issues,
                recommendations=recommendations,
                performance_metrics=performance_metrics,
                uptime_seconds=uptime_seconds,
                errors=errors,
            )

            self._last_health_check = result

            check_duration = (time.time() - start_time) * 1000
            logger.info(
                f"Health check completed in {check_duration:.2f}ms with status: {overall_status}"
            )

            return result

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            errors.append(str(e))

            return HealthCheckResult(
                timestamp=datetime.utcnow(),
                overall_status=OverallHealthStatus.CRITICAL,
                database_connections=[],
                migration_status=MigrationStatus.FAILED,
                consistency_issues=0,
                critical_issues=1,
                warning_issues=0,
                recommendations=["Fix health check system error"],
                performance_metrics={},
                uptime_seconds=time.time() - self._start_time,
                errors=errors,
            )

    async def _check_database_connections(self) -> List[DatabaseConnectionStatus]:
        """Check health of all database connections"""
        connections = []

        # PostgreSQL health check
        pg_status = await self._check_postgresql_connection()
        connections.append(pg_status)

        # Redis health check
        redis_status = await self._check_redis_connection()
        connections.append(redis_status)

        return connections

    async def _check_postgresql_connection(self) -> DatabaseConnectionStatus:
        """Check PostgreSQL connection health"""
        start_time = time.time()

        try:
            async with self.db_client.async_session_scope() as session:
                # Test basic connectivity
                result = await session.execute(text("SELECT version()"))
                version = result.scalar()

                # Get connection count
                result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity")
                )
                connection_count = result.scalar()

                # Check for long-running queries
                result = await session.execute(
                    text("""
                        SELECT count(*) FROM pg_stat_activity 
                        WHERE state = 'active' 
                        AND query_start < NOW() - INTERVAL '5 minutes'
                    """)
                )
                long_queries = result.scalar()

            response_time = (time.time() - start_time) * 1000

            # Determine status
            status = ValidationStatus.HEALTHY
            if response_time > 1000:  # > 1 second
                status = ValidationStatus.WARNING
            if long_queries > 0:
                status = ValidationStatus.WARNING
            if self.db_client.is_degraded():
                status = ValidationStatus.CRITICAL

            return DatabaseConnectionStatus(
                database=DatabaseType.POSTGRESQL,
                is_connected=True,
                response_time_ms=response_time,
                status=status,
                version=version,
                connection_count=connection_count,
                degraded_mode=self.db_client.is_degraded(),
                metadata={
                    "long_running_queries": long_queries,
                    "pool_metrics": self.db_client._get_pool_metrics(),
                },
            )

        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            return DatabaseConnectionStatus(
                database=DatabaseType.POSTGRESQL,
                is_connected=False,
                response_time_ms=0,
                status=ValidationStatus.CRITICAL,
                error_message=str(e),
                degraded_mode=True,
            )

    async def _check_redis_connection(self) -> DatabaseConnectionStatus:
        """Check Redis connection health"""
        start_time = time.time()

        try:
            # Test basic connectivity
            await self.redis_manager.set("health_check", "test", ex=10)
            result = await self.redis_manager.get("health_check")
            await self.redis_manager.delete("health_check")

            response_time = (time.time() - start_time) * 1000

            # Get connection info
            connection_info = self.redis_manager.get_connection_info()

            # Determine status
            status = ValidationStatus.HEALTHY
            if response_time > 500:  # > 500ms
                status = ValidationStatus.WARNING
            if self.redis_manager.is_degraded():
                status = ValidationStatus.WARNING

            return DatabaseConnectionStatus(
                database=DatabaseType.REDIS,
                is_connected=True,
                response_time_ms=response_time,
                status=status,
                degraded_mode=self.redis_manager.is_degraded(),
                metadata={
                    "connection_info": connection_info,
                    "memory_cache_size": connection_info.get("memory_cache_size", 0),
                    "connection_failures": connection_info.get(
                        "connection_failures", 0
                    ),
                },
            )

        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return DatabaseConnectionStatus(
                database=DatabaseType.REDIS,
                is_connected=False,
                response_time_ms=0,
                status=ValidationStatus.CRITICAL,
                error_message=str(e),
                degraded_mode=True,
            )

    async def _check_migration_status(self) -> MigrationStatus:
        """Check database migration status"""
        try:
            migration_report = await self.migration_validator.validate_migrations()
            return migration_report.overall_status
        except Exception as e:
            logger.error(f"Migration status check failed: {e}")
            return MigrationStatus.FAILED

    async def _collect_performance_metrics(self) -> Dict[str, Any]:
        """Collect performance metrics from all databases"""
        metrics = {}

        try:
            # PostgreSQL metrics
            if self.db_client and not self.db_client.is_degraded():
                async with self.db_client.async_session_scope() as session:
                    # Database size
                    result = await session.execute(
                        text("SELECT pg_database_size(current_database())")
                    )
                    db_size = result.scalar()

                    # Active connections
                    result = await session.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
                        )
                    )
                    active_connections = result.scalar()

                    metrics["postgresql"] = {
                        "database_size_bytes": db_size,
                        "active_connections": active_connections,
                    "pool_metrics": self.db_client._get_pool_metrics(),
                    }

            # Redis metrics
            redis_info = self.redis_manager.get_connection_info()
            metrics["redis"] = {
                "degraded_mode": redis_info.get("degraded_mode", False),
                "memory_cache_size": redis_info.get("memory_cache_size", 0),
                "connection_failures": redis_info.get("connection_failures", 0),
            }

        except Exception as e:
            logger.error(f"Performance metrics collection failed: {e}")
            metrics["error"] = str(e)

        return metrics

    def _determine_overall_status(
        self,
        db_connections: List[DatabaseConnectionStatus],
        migration_status: MigrationStatus,
        critical_issues: int,
    ) -> OverallHealthStatus:
        """Determine overall health status"""

        # Check if any database is offline
        offline_dbs = [conn for conn in db_connections if not conn.is_connected]
        if offline_dbs:
            return OverallHealthStatus.OFFLINE

        # Check for critical issues
        critical_dbs = [
            conn for conn in db_connections if conn.status == ValidationStatus.CRITICAL
        ]
        if critical_dbs or critical_issues > 0:
            return OverallHealthStatus.CRITICAL

        # Check migration status
        if migration_status in [MigrationStatus.FAILED, MigrationStatus.PENDING]:
            return OverallHealthStatus.CRITICAL

        # Check for degraded databases
        degraded_dbs = [
            conn
            for conn in db_connections
            if conn.degraded_mode or conn.status == ValidationStatus.WARNING
        ]
        if degraded_dbs:
            return OverallHealthStatus.DEGRADED

        # Everything looks good
        return OverallHealthStatus.HEALTHY

    def _generate_health_recommendations(
        self,
        db_connections: List[DatabaseConnectionStatus],
        migration_status: MigrationStatus,
        critical_issues: int,
        warning_issues: int,
    ) -> List[str]:
        """Generate health recommendations"""
        recommendations = []

        # Database connection recommendations
        for conn in db_connections:
            if not conn.is_connected:
                recommendations.append(
                    f"Restore {conn.database.value} connection - service is offline"
                )
            elif conn.status == ValidationStatus.CRITICAL:
                recommendations.append(
                    f"Fix critical issues with {conn.database.value} database"
                )
            elif conn.degraded_mode:
                recommendations.append(
                    f"Resolve {conn.database.value} degraded mode operation"
                )
            elif conn.response_time_ms > 1000:
                recommendations.append(
                    f"Optimize {conn.database.value} performance - high response time ({conn.response_time_ms:.0f}ms)"
                )

        # Migration recommendations
        if migration_status == MigrationStatus.PENDING:
            recommendations.append("Apply pending database migrations")
        elif migration_status == MigrationStatus.FAILED:
            recommendations.append("Fix database migration issues")
        elif migration_status == MigrationStatus.UNKNOWN:
            recommendations.append("Initialize database migration tracking")

        # Issue-based recommendations
        if critical_issues > 0:
            recommendations.append(
                f"Address {critical_issues} critical database issues"
            )
        if warning_issues > 0:
            recommendations.append(f"Review {warning_issues} database warnings")

        # General recommendations
        if not recommendations:
            recommendations.append("All database systems are healthy")

        return recommendations

    async def get_quick_status(self) -> Dict[str, Any]:
        """
        Get quick health status without detailed validation.

        Returns:
            Dict containing basic health information
        """
        try:
            # Quick connection tests
            pg_connected = not self.db_client.is_degraded()
            redis_connected = not self.redis_manager.is_degraded()

            # Determine overall status
            if not pg_connected:
                overall_status = "critical"
            elif not redis_connected:
                overall_status = "degraded"
            else:
                overall_status = "healthy"

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "overall_status": overall_status,
                "databases": {
                    "postgresql": "connected" if pg_connected else "disconnected",
                    "redis": "connected" if redis_connected else "degraded",
                },
                "uptime_seconds": time.time() - self._start_time,
            }

        except Exception as e:
            logger.error(f"Quick status check failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "overall_status": "error",
                "error": str(e),
                "uptime_seconds": time.time() - self._start_time,
            }

    def get_last_health_check(self) -> Optional[HealthCheckResult]:
        """Get the last health check result"""
        return self._last_health_check

    async def wait_for_healthy(
        self, timeout_seconds: int = 60, check_interval: int = 5
    ) -> bool:
        """
        Wait for all databases to become healthy.

        Args:
            timeout_seconds: Maximum time to wait
            check_interval: Seconds between health checks

        Returns:
            bool: True if healthy within timeout, False otherwise
        """
        logger.info(
            f"Waiting for databases to become healthy (timeout: {timeout_seconds}s)"
        )

        start_time = time.time()

        while (time.time() - start_time) < timeout_seconds:
            try:
                health_result = await self.check_health(
                    include_detailed_validation=False
                )

                if health_result.overall_status == OverallHealthStatus.HEALTHY:
                    logger.info("All databases are healthy")
                    return True

                logger.info(
                    f"Databases not yet healthy: {health_result.overall_status}"
                )
                await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"Health check during wait failed: {e}")
                await asyncio.sleep(check_interval)

        logger.warning(
            f"Databases did not become healthy within {timeout_seconds} seconds"
        )
        return False


# Global instance
_database_health_checker: Optional[DatabaseHealthChecker] = None


def get_database_health_checker() -> DatabaseHealthChecker:
    """Get global database health checker instance"""
    global _database_health_checker
    if _database_health_checker is None:
        _database_health_checker = DatabaseHealthChecker()
    return _database_health_checker


async def check_database_health(
    include_detailed_validation: bool = False,
) -> HealthCheckResult:
    """
    Convenience function to check database health.

    Args:
        include_detailed_validation: Whether to include detailed consistency validation

    Returns:
        HealthCheckResult: Complete health check result
    """
    checker = get_database_health_checker()
    return await checker.check_health(
        include_detailed_validation=include_detailed_validation
    )
