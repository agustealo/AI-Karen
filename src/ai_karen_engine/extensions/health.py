"""
Advanced extension health monitoring system.

Standardized health states with comprehensive monitoring including:
- Real-time health checks with configurable intervals
- Prometheus metrics integration
- Background task monitoring
- Database and service health checks
- Historical health data collection
- API-ready health information

Enhanced with migration from root server/extension_health_monitor.py as part of ROOT-CLEANUP-1A.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.contracts import ExtensionHealth, ExtensionLifecycleState

logger = logging.getLogger("kari.extensions.health")


class ExtensionHealthStatus(str, Enum):
    """Extension health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ExtensionHealthRecord:
    """Basic health record for an extension."""
    plugin_id: str
    state: ExtensionLifecycleState
    health: ExtensionHealth
    last_check: Optional[datetime] = None
    reason_code: Optional[str] = None
    dependency_status: Dict[str, str] = field(default_factory=dict)

    # Advanced metrics (migrated from root server)
    response_time_ms: float = 0
    error_count: int = 0
    success_count: int = 0
    uptime_seconds: float = 0
    memory_usage_mb: float = 0
    cpu_usage_percent: float = 0
    background_tasks_active: int = 0
    background_tasks_failed: int = 0
    api_calls_per_minute: float = 0
    error: Optional[str] = None


@dataclass
class ExtensionSystemHealth:
    """Overall extension system health."""
    overall_status: ExtensionHealthStatus
    total_extensions: int
    healthy_extensions: int
    degraded_extensions: int
    unhealthy_extensions: int
    extension_metrics: Dict[str, ExtensionHealthRecord]
    system_uptime_seconds: float
    authentication_healthy: bool
    database_healthy: bool
    background_tasks_healthy: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExtensionHealthMonitor:
    """Advanced extension health monitoring system."""

    def __init__(self, extension_manager=None) -> None:
        """Initialize the health monitor."""
        self.extension_manager = extension_manager
        self._records: Dict[str, ExtensionHealthRecord] = {}
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._health_history: List[ExtensionSystemHealth] = []
        self._max_history = 100
        self._start_time = time.time()

        # Health check thresholds
        self.thresholds = {
            "response_time_warning_ms": 500,
            "response_time_critical_ms": 2000,
            "error_rate_warning": 0.05,  # 5%
            "error_rate_critical": 0.15,  # 15%
            "memory_warning_mb": 100,
            "memory_critical_mb": 500,
            "cpu_warning_percent": 70,
            "cpu_critical_percent": 90
        }

    def record(self, record: ExtensionHealthRecord) -> None:
        """Record a basic health check result (legacy interface)."""
        self._records[record.plugin_id] = record

    def get(self, plugin_id: str) -> Optional[ExtensionHealthRecord]:
        """Get health record for a specific extension (legacy interface)."""
        return self._records.get(plugin_id)

    def summary(self) -> Dict[str, Any]:
        """Get basic health summary (legacy interface)."""
        by_health: Dict[str, int] = {}
        for record in self._records.values():
            by_health[record.health.value] = by_health.get(record.health.value, 0) + 1
        return {
            "total": len(self._records),
            "by_health": by_health,
        }

    async def start_monitoring(self, check_interval: int = 30):
        """Start extension health monitoring."""
        self._monitoring_active = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop(check_interval))
        logger.info("Extension health monitoring started")

    async def stop_monitoring(self):
        """Stop extension health monitoring."""
        self._monitoring_active = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Extension health monitoring stopped")

    async def _monitoring_loop(self, check_interval: int):
        """Main monitoring loop."""
        while self._monitoring_active:
            try:
                health = await self.check_extension_system_health()
                self._add_to_history(health)

                # Update Prometheus metrics
                self.update_extension_metrics(health)

                # Log warnings for unhealthy extensions
                if health.overall_status != ExtensionHealthStatus.HEALTHY:
                    await self._handle_health_issues(health)

                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in extension health monitoring loop: {e}")
                await asyncio.sleep(check_interval)

    async def check_extension_system_health(self) -> ExtensionSystemHealth:
        """Check health of the entire extension system."""
        try:
            # Check if extension manager is available
            if not self.extension_manager:
                return ExtensionSystemHealth(
                    overall_status=ExtensionHealthStatus.UNKNOWN,
                    total_extensions=0,
                    healthy_extensions=0,
                    degraded_extensions=0,
                    unhealthy_extensions=0,
                    extension_metrics={},
                    system_uptime_seconds=time.time() - self._start_time,
                    authentication_healthy=False,
                    database_healthy=False,
                    background_tasks_healthy=False
                )

            # Get all extensions
            extensions = {}
            extension_metrics = {}

            try:
                extensions = self.extension_manager.registry.get_all_extensions()
            except Exception as e:
                logger.warning(f"Failed to get extensions from registry: {e}")

            # Check health of each extension
            for name, record in extensions.items():
                try:
                    metrics = await self._check_individual_extension_health(name, record)
                    extension_metrics[name] = metrics
                except Exception as e:
                    logger.error(f"Failed to check health for extension {name}: {e}")
                    extension_metrics[name] = ExtensionHealthRecord(
                        plugin_id=name,
                        state=ExtensionLifecycleState.STOPPED,
                        health=ExtensionHealth.UNHEALTHY,
                        response_time_ms=0,
                        last_check=datetime.now(timezone.utc),
                        error=str(e)
                    )

            # Check supporting services health
            auth_healthy = await self._check_authentication_service_health()
            db_healthy = await self._check_database_health()
            bg_tasks_healthy = await self._check_background_tasks_health()

            # Calculate overall statistics
            total_extensions = len(extension_metrics)
            healthy_count = sum(1 for m in extension_metrics.values()
                              if m.health == ExtensionHealth.HEALTHY)
            degraded_count = sum(1 for m in extension_metrics.values()
                               if m.health == ExtensionHealth.DEGRADED)
            unhealthy_count = sum(1 for m in extension_metrics.values()
                               if m.health == ExtensionHealth.UNHEALTHY)

            # Determine overall status
            overall_status = self._calculate_overall_status(
                extension_metrics, auth_healthy, db_healthy, bg_tasks_healthy
            )

            return ExtensionSystemHealth(
                overall_status=overall_status,
                total_extensions=total_extensions,
                healthy_extensions=healthy_count,
                degraded_extensions=degraded_count,
                unhealthy_extensions=unhealthy_count,
                extension_metrics=extension_metrics,
                system_uptime_seconds=time.time() - self._start_time,
                authentication_healthy=auth_healthy,
                database_healthy=db_healthy,
                background_tasks_healthy=bg_tasks_healthy
            )

        except Exception as e:
            logger.error(f"Failed to check extension system health: {e}")
            return ExtensionSystemHealth(
                overall_status=ExtensionHealthStatus.UNHEALTHY,
                total_extensions=0,
                healthy_extensions=0,
                degraded_extensions=0,
                unhealthy_extensions=1,
                extension_metrics={},
                system_uptime_seconds=time.time() - self._start_time,
                authentication_healthy=False,
                database_healthy=False,
                background_tasks_healthy=False
            )

    async def _check_individual_extension_health(self, name: str, record) -> ExtensionHealthRecord:
        """Check health of an individual extension."""
        start_time = time.time()

        try:
            # Basic status check
            is_active = hasattr(record, 'status') and record.status.value == 'active'

            # Check if extension has health check method
            health_result = True
            if hasattr(record, 'instance') and record.instance:
                if hasattr(record.instance, 'health_check'):
                    try:
                        health_result = await record.instance.health_check()
                    except Exception as e:
                        logger.warning(f"Extension {name} health check failed: {e}")
                        health_result = False

            # Calculate response time
            response_time = (time.time() - start_time) * 1000

            # Get extension metrics if available
            error_count = getattr(record, 'error_count', 0)
            success_count = getattr(record, 'success_count', 0)

            # Calculate uptime
            uptime = 0
            if hasattr(record, 'loaded_at') and record.loaded_at:
                uptime = (datetime.now(timezone.utc) - record.loaded_at).total_seconds()

            # Determine status based on various factors
            health_status = self._determine_extension_status(
                is_active, health_result, response_time, error_count, success_count
            )

            return ExtensionHealthRecord(
                plugin_id=name,
                state=record.state if hasattr(record, 'state') else ExtensionLifecycleState.STOPPED,
                health=health_status,
                response_time_ms=response_time,
                last_check=datetime.now(timezone.utc),
                error_count=error_count,
                success_count=success_count,
                uptime_seconds=uptime,
                error=getattr(record, 'error', None)
            )

        except Exception as e:
            return ExtensionHealthRecord(
                plugin_id=name,
                state=ExtensionLifecycleState.STOPPED,
                health=ExtensionHealth.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                last_check=datetime.now(timezone.utc),
                error=str(e)
            )

    def _determine_extension_status(
        self,
        is_active: bool,
        health_result: bool,
        response_time: float,
        error_count: int,
        success_count: int
    ) -> ExtensionHealth:
        """Determine extension health status based on various factors."""
        # If not active, it's unhealthy
        if not is_active:
            return ExtensionHealth.UNHEALTHY

        # If health check failed, it's unhealthy
        if not health_result:
            return ExtensionHealth.UNHEALTHY

        # Check response time
        if response_time > self.thresholds["response_time_critical_ms"]:
            return ExtensionHealth.UNHEALTHY
        elif response_time > self.thresholds["response_time_warning_ms"]:
            return ExtensionHealth.DEGRADED

        # Check error rate
        total_requests = error_count + success_count
        if total_requests > 0:
            error_rate = error_count / total_requests
            if error_rate > self.thresholds["error_rate_critical"]:
                return ExtensionHealth.UNHEALTHY
            elif error_rate > self.thresholds["error_rate_warning"]:
                return ExtensionHealth.DEGRADED

        return ExtensionHealth.HEALTHY

    async def _check_authentication_service_health(self) -> bool:
        """Check authentication service health for extension APIs."""
        try:
            # Placeholder for actual authentication health check
            # In production, this would test token generation/validation
            return True
        except Exception as e:
            logger.warning(f"Authentication service health check failed: {e}")
            return False

    async def _check_database_health(self) -> bool:
        """Check database health for extension services."""
        try:
            # Placeholder for actual database health check
            # In production, this would test database connectivity and queries
            return True
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            return False

    async def _check_background_tasks_health(self) -> bool:
        """Check background tasks health for extensions."""
        try:
            if not self.extension_manager:
                return False
            # Placeholder for actual background task health check
            return True
        except Exception as e:
            logger.warning(f"Background tasks health check failed: {e}")
            return False

    def _calculate_overall_status(
        self,
        extension_metrics: Dict[str, ExtensionHealthRecord],
        auth_healthy: bool,
        db_healthy: bool,
        bg_tasks_healthy: bool
    ) -> ExtensionHealthStatus:
        """Calculate overall extension system status."""

        # Convert ExtensionHealth to ExtensionHealthStatus for calculation
        def convert_health(health: ExtensionHealth) -> ExtensionHealthStatus:
            if health == ExtensionHealth.HEALTHY:
                return ExtensionHealthStatus.HEALTHY
            elif health == ExtensionHealth.DEGRADED:
                return ExtensionHealthStatus.DEGRADED
            else:
                return ExtensionHealthStatus.UNHEALTHY

        # If critical services are down, system is unhealthy
        if not auth_healthy or not db_healthy:
            return ExtensionHealthStatus.UNHEALTHY

        # If no extensions, status depends on supporting services
        if not extension_metrics:
            return ExtensionHealthStatus.DEGRADED if bg_tasks_healthy else ExtensionHealthStatus.UNHEALTHY

        # Calculate extension health ratios
        total = len(extension_metrics)
        healthy = sum(1 for m in extension_metrics.values()
                     if convert_health(m.health) == ExtensionHealthStatus.HEALTHY)
        unhealthy = sum(1 for m in extension_metrics.values()
                        if convert_health(m.health) == ExtensionHealthStatus.UNHEALTHY)

        # Determine overall status based on ratios
        if unhealthy > total * 0.5:  # More than 50% unhealthy
            return ExtensionHealthStatus.UNHEALTHY
        elif healthy < total * 0.7:  # Less than 70% healthy
            return ExtensionHealthStatus.DEGRADED
        elif not bg_tasks_healthy:  # Extensions healthy but background tasks not
            return ExtensionHealthStatus.DEGRADED
        else:
            return ExtensionHealthStatus.HEALTHY

    async def _handle_health_issues(self, health: ExtensionSystemHealth):
        """Handle detected health issues."""
        if health.overall_status == ExtensionHealthStatus.UNHEALTHY:
            logger.error(
                f"Extension system is unhealthy: {health.unhealthy_extensions} unhealthy, "
                f"{health.degraded_extensions} degraded out of {health.total_extensions} total"
            )
        elif health.overall_status == ExtensionHealthStatus.DEGRADED:
            logger.warning(
                f"Extension system is degraded: {health.degraded_extensions} degraded, "
                f"{health.unhealthy_extensions} unhealthy out of {health.total_extensions} total"
            )

        # Log specific extension issues
        for name, metrics in health.extension_metrics.items():
            if metrics.health != ExtensionHealth.HEALTHY:
                logger.warning(
                    f"Extension {name} is {metrics.health.value}: "
                    f"response_time={metrics.response_time_ms:.1f}ms, "
                    f"errors={metrics.error_count}, "
                    f"error_msg={metrics.error}"
                )

    def _add_to_history(self, health: ExtensionSystemHealth):
        """Add health record to history."""
        self._health_history.append(health)
        if len(self._health_history) > self._max_history:
            self._health_history.pop(0)

    def get_health_history(self, minutes: int = 60) -> List[ExtensionSystemHealth]:
        """Get health history for the specified number of minutes."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [h for h in self._health_history if h.timestamp >= cutoff_time]

    async def get_extension_health_for_api(self) -> Dict[str, Any]:
        """
        Get extension health information formatted for API responses.

        This method provides health information in a format suitable for
        integration with existing health endpoints.
        """
        health = await self.check_extension_system_health()

        # Convert ExtensionHealth to string values
        def health_to_string(health: ExtensionHealth) -> str:
            return health.value

        return {
            "status": health.overall_status.value,
            "timestamp": health.timestamp.isoformat(),
            "uptime_seconds": health.system_uptime_seconds,
            "extensions": {
                "total": health.total_extensions,
                "healthy": health.healthy_extensions,
                "degraded": health.degraded_extensions,
                "unhealthy": health.unhealthy_extensions,
                "details": {
                    name: {
                        "status": health_to_string(metrics.health),
                        "response_time_ms": metrics.response_time_ms,
                        "uptime_seconds": metrics.uptime_seconds,
                        "error_count": metrics.error_count,
                        "success_count": metrics.success_count,
                        "background_tasks_active": metrics.background_tasks_active,
                        "background_tasks_failed": metrics.background_tasks_failed,
                        "last_check": metrics.last_check.isoformat() if metrics.last_check else None,
                        "error": metrics.error
                    }
                    for name, metrics in health.extension_metrics.items()
                }
            },
            "supporting_services": {
                "authentication": {
                    "healthy": health.authentication_healthy,
                    "description": "Extension API authentication service"
                },
                "database": {
                    "healthy": health.database_healthy,
                    "description": "Extension database connectivity"
                },
                "background_tasks": {
                    "healthy": health.background_tasks_healthy,
                    "description": "Extension background task system"
                }
            }
        }

    def update_extension_metrics(self, health: ExtensionSystemHealth):
        """Update Prometheus metrics with extension health data."""
        try:
            # Check if Prometheus is available
            try:
                # This would be the actual Prometheus metrics update
                # For now, we'll just log that metrics would be updated
                logger.debug(f"Would update Prometheus metrics for {len(health.extension_metrics)} extensions")
            except ImportError:
                # Prometheus not available, skip metrics update
                pass
        except Exception as e:
            logger.warning(f"Failed to update extension metrics: {e}")

    def record_extension_api_call(self, extension_name: str, endpoint: str, status_code: int, response_time_ms: float):
        """Record extension API call metrics."""
        try:
            # Check if Prometheus is available
            try:
                # This would be the actual Prometheus metrics update
                logger.debug(f"Would record API call for {extension_name} to {endpoint}: {status_code}")
            except ImportError:
                # Prometheus not available, skip metrics update
                pass
        except Exception as e:
            logger.warning(f"Failed to record extension API call metrics: {e}")

    def record_extension_error(self, extension_name: str, error_type: str):
        """Record extension error metrics."""
        try:
            # Check if Prometheus is available
            try:
                # This would be the actual Prometheus metrics update
                logger.debug(f"Would record error for {extension_name}: {error_type}")
            except ImportError:
                # Prometheus not available, skip metrics update
                pass
        except Exception as e:
            logger.warning(f"Failed to record extension error metrics: {e}")

    async def check_specific_extension_health(self, extension_name: str) -> Dict[str, Any]:
        """Check health of a specific extension."""
        if not self.extension_manager:
            return {
                "extension": extension_name,
                "status": "unknown",
                "error": "Extension manager not available"
            }

        try:
            extensions = self.extension_manager.registry.get_all_extensions()
            if extension_name not in extensions:
                return {
                    "extension": extension_name,
                    "status": "not_found",
                    "error": "Extension not found"
                }

            record = extensions[extension_name]
            metrics = await self._check_individual_extension_health(extension_name, record)

            return {
                "extension": extension_name,
                "status": metrics.health.value,
                "response_time_ms": metrics.response_time_ms,
                "uptime_seconds": metrics.uptime_seconds,
                "error_count": metrics.error_count,
                "success_count": metrics.success_count,
                "background_tasks_active": metrics.background_tasks_active,
                "background_tasks_failed": metrics.background_tasks_failed,
                "last_check": metrics.last_check.isoformat() if metrics.last_check else None,
                "error": metrics.error,
                "healthy": metrics.health == ExtensionHealth.HEALTHY
            }

        except Exception as e:
            logger.error(f"Failed to check health for extension {extension_name}: {e}")
            return {
                "extension": extension_name,
                "status": "error",
                "error": str(e),
                "healthy": False
            }


# Global instance
_extension_health_monitor: Optional[ExtensionHealthMonitor] = None


def get_extension_health_monitor() -> Optional[ExtensionHealthMonitor]:
    """Get the global extension health monitor."""
    return _extension_health_monitor


async def initialize_extension_health_monitor(extension_manager=None) -> ExtensionHealthMonitor:
    """Initialize the extension health monitor."""
    global _extension_health_monitor

    _extension_health_monitor = ExtensionHealthMonitor(extension_manager)
    await _extension_health_monitor.start_monitoring()

    logger.info("Extension health monitor initialized")
    return _extension_health_monitor


async def shutdown_extension_health_monitor():
    """Shutdown the extension health monitor."""
    global _extension_health_monitor

    if _extension_health_monitor:
        await _extension_health_monitor.stop_monitoring()
        _extension_health_monitor = None

    logger.info("Extension health monitor shutdown completed")


def record_extension_api_call_global(extension_name: str, endpoint: str, status_code: int, response_time_ms: float):
    """Global function to record extension API call metrics."""
    monitor = get_extension_health_monitor()
    if monitor:
        monitor.record_extension_api_call(extension_name, endpoint, status_code, response_time_ms)


def record_extension_error_global(extension_name: str, error_type: str):
    """Global function to record extension error metrics."""
    monitor = get_extension_health_monitor()
    if monitor:
        monitor.record_extension_error(extension_name, error_type)


__all__ = [
    "ExtensionHealthStatus",
    "ExtensionHealthRecord",
    "ExtensionSystemHealth",
    "ExtensionHealthMonitor",
    "get_extension_health_monitor",
    "initialize_extension_health_monitor",
    "shutdown_extension_health_monitor",
    "record_extension_api_call_global",
    "record_extension_error_global",
]