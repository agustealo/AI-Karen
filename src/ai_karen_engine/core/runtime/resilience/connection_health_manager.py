"""
Connection Health Manager

Provides graceful connection handling for Redis and database connections with:
- Exponential backoff for connection retries
- Degraded mode operation when services are unavailable
- Connection pool management with proper cleanup
- Health status monitoring and reporting
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union, Coroutine
import random
import json

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class ServiceStatus(str, Enum):
    """Service health status enumeration"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"


class ConnectionType(str, Enum):
    """Connection type enumeration"""
    DATABASE = "database"
    REDIS = "redis"


@dataclass
class HealthStatus:
    """Health status for a service"""
    service: str
    connection_type: ConnectionType
    status: ServiceStatus
    last_check: datetime
    last_success: Optional[datetime] = None
    error_message: Optional[str] = None
    degraded_features: List[str] = field(default_factory=list)
    retry_count: int = 0
    next_retry: Optional[datetime] = None
    response_time_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_retries: int = 5
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    circuit_breaker_threshold: int = 10  # consecutive failures before circuit opens
    circuit_breaker_timeout: float = 300.0  # seconds to wait before trying again


class ConnectionHealthManager:
    """
    Manages connection health for Redis, database, and other services.
    Provides graceful degradation and automatic recovery.
    """

    def __init__(self, retry_config: Optional[RetryConfig] = None):
        self.retry_config = retry_config or RetryConfig()
        self.health_status: Dict[str, HealthStatus] = {}
        self.degraded_mode_callbacks: Dict[str, List[Callable]] = {}
        self.recovery_callbacks: Dict[str, List[Callable]] = {}
        self.circuit_breakers: Dict[str, Dict[str, Any]] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start_monitoring(self, check_interval: float = 30.0):
        """Start background health monitoring"""
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("Health monitoring already running")
            return

        self._shutdown_event.clear()
        self._monitoring_task = asyncio.create_task(
            self._monitoring_loop(check_interval)
        )
        logger.info("Connection health monitoring started")

    async def stop_monitoring(self):
        """Stop background health monitoring"""
        self._shutdown_event.set()
        if self._monitoring_task:
            try:
                await asyncio.wait_for(self._monitoring_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
        logger.info("Connection health monitoring stopped")

    def register_service(
        self,
        service_name: str,
        connection_type: ConnectionType,
        health_check_func: Callable[[], Union[bool, Dict[str, Any], Coroutine[Any, Any, Union[bool, Dict[str, Any]]]]],
        degraded_mode_callback: Optional[Callable] = None,
        recovery_callback: Optional[Callable] = None,
    ):
        """Register a service for health monitoring"""
        self.health_status[service_name] = HealthStatus(
            service=service_name,
            connection_type=connection_type,
            status=ServiceStatus.UNAVAILABLE,
            last_check=datetime.utcnow(),
        )

        # Store health check function
        if not hasattr(self, '_health_check_funcs'):
            self._health_check_funcs = {}
        self._health_check_funcs[service_name] = health_check_func

        # Register callbacks
        if degraded_mode_callback:
            self.register_degraded_mode_callback(service_name, degraded_mode_callback)
        if recovery_callback:
            self.register_recovery_callback(service_name, recovery_callback)

        logger.info(f"Registered service {service_name} for health monitoring")

    def register_degraded_mode_callback(self, service_name: str, callback: Callable):
        """Register callback to execute when service enters degraded mode"""
        if service_name not in self.degraded_mode_callbacks:
            self.degraded_mode_callbacks[service_name] = []
        self.degraded_mode_callbacks[service_name].append(callback)

    def register_recovery_callback(self, service_name: str, callback: Callable):
        """Register callback to execute when service recovers"""
        if service_name not in self.recovery_callbacks:
            self.recovery_callbacks[service_name] = []
        self.recovery_callbacks[service_name].append(callback)

    async def check_service_health(self, service_name: str) -> HealthStatus:
        """Check health of a specific service"""
        if service_name not in self.health_status:
            raise ValueError(f"Service {service_name} not registered")

        health_check_func = getattr(self, '_health_check_funcs', {}).get(service_name)
        if not health_check_func:
            raise ValueError(f"No health check function for service {service_name}")

        start_time = time.time()
        current_status = self.health_status[service_name]
        
        try:
            # Check if circuit breaker is open
            if self._is_circuit_breaker_open(service_name):
                logger.debug(f"Circuit breaker open for {service_name}, skipping check")
                return current_status

            # Perform health check
            if asyncio.iscoroutinefunction(health_check_func):
                result = await health_check_func()
            else:
                result = health_check_func()

            response_time_ms = (time.time() - start_time) * 1000

            # Process result
            if isinstance(result, bool):
                is_healthy = result
                metadata = {}
            elif isinstance(result, dict):
                is_healthy = result.get('healthy', False)
                metadata = {k: v for k, v in result.items() if k != 'healthy'}
            else:
                is_healthy = bool(result)
                metadata = {}

            # Update status
            previous_status = current_status.status
            new_status = ServiceStatus.HEALTHY if is_healthy else ServiceStatus.UNAVAILABLE

            self.health_status[service_name] = HealthStatus(
                service=service_name,
                connection_type=current_status.connection_type,
                status=new_status,
                last_check=datetime.utcnow(),
                last_success=datetime.utcnow() if is_healthy else current_status.last_success,
                error_message=None,
                degraded_features=current_status.degraded_features if not is_healthy else [],
                retry_count=0 if is_healthy else current_status.retry_count,
                next_retry=None if is_healthy else current_status.next_retry,
                response_time_ms=response_time_ms,
                metadata=metadata,
            )

            # Handle status changes
            if previous_status != new_status:
                await self._handle_status_change(service_name, previous_status, new_status)

            # Reset circuit breaker on success
            if is_healthy:
                self._reset_circuit_breaker(service_name)

            return self.health_status[service_name]

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            # Update failure count for circuit breaker
            self._record_failure(service_name)

            # Calculate next retry time
            next_retry = self._calculate_next_retry(current_status.retry_count + 1)

            previous_status = current_status.status
            new_status = ServiceStatus.UNAVAILABLE

            self.health_status[service_name] = HealthStatus(
                service=service_name,
                connection_type=current_status.connection_type,
                status=new_status,
                last_check=datetime.utcnow(),
                last_success=current_status.last_success,
                error_message=error_msg,
                degraded_features=self._get_degraded_features(service_name),
                retry_count=current_status.retry_count + 1,
                next_retry=next_retry,
                response_time_ms=response_time_ms,
                metadata={},
            )

            # Handle status changes
            if previous_status != new_status:
                await self._handle_status_change(service_name, previous_status, new_status)

            logger.warning(f"Health check failed for {service_name}: {error_msg}")
            return self.health_status[service_name]

    async def retry_connection(self, service_name: str, max_retries: Optional[int] = None) -> bool:
        """Retry connection to a service with exponential backoff"""
        if service_name not in self.health_status:
            raise ValueError(f"Service {service_name} not registered")

        max_retries = max_retries or self.retry_config.max_retries
        current_status = self.health_status[service_name]

        for attempt in range(max_retries):
            if attempt > 0:
                delay = self._calculate_retry_delay(attempt)
                logger.info(f"Retrying {service_name} connection in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)

            try:
                health_status = await self.check_service_health(service_name)
                if health_status.status == ServiceStatus.HEALTHY:
                    logger.info(f"Successfully reconnected to {service_name} after {attempt + 1} attempts")
                    return True
            except Exception as e:
                logger.warning(f"Retry attempt {attempt + 1} failed for {service_name}: {e}")

        logger.error(f"Failed to reconnect to {service_name} after {max_retries} attempts")
        return False

    def enable_degraded_mode(self, service_name: str, features: List[str]):
        """Enable degraded mode for a service"""
        if service_name in self.health_status:
            self.health_status[service_name].status = ServiceStatus.DEGRADED
            self.health_status[service_name].degraded_features = features
            logger.warning(f"Enabled degraded mode for {service_name}, disabled features: {features}")

    def disable_degraded_mode(self, service_name: str):
        """Disable degraded mode for a service"""
        if service_name in self.health_status:
            self.health_status[service_name].status = ServiceStatus.HEALTHY
            self.health_status[service_name].degraded_features = []
            logger.info(f"Disabled degraded mode for {service_name}")

    def is_service_healthy(self, service_name: str) -> bool:
        """Check if a service is healthy"""
        return (
            service_name in self.health_status
            and self.health_status[service_name].status == ServiceStatus.HEALTHY
        )

    def is_service_available(self, service_name: str) -> bool:
        """Check if a service is available (healthy or degraded)"""
        return (
            service_name in self.health_status
            and self.health_status[service_name].status in [ServiceStatus.HEALTHY, ServiceStatus.DEGRADED]
        )

    def get_service_status(self, service_name: str) -> Optional[HealthStatus]:
        """Get current status of a service"""
        return self.health_status.get(service_name)

    def get_all_statuses(self) -> Dict[str, HealthStatus]:
        """Get status of all registered services"""
        return dict(self.health_status)

    def get_degraded_features(self, service_name: str) -> List[str]:
        """Get list of features disabled due to service degradation"""
        if service_name in self.health_status:
            return self.health_status[service_name].degraded_features
        return []

    async def handle_connection_failure(self, service_name: str, error: Exception):
        """Handle connection failure for a service"""
        logger.error(f"Connection failure for {service_name}: {error}")
        
        if service_name in self.health_status:
            current_status = self.health_status[service_name]
            
            # Update status
            self.health_status[service_name] = HealthStatus(
                service=service_name,
                connection_type=current_status.connection_type,
                status=ServiceStatus.UNAVAILABLE,
                last_check=datetime.utcnow(),
                last_success=current_status.last_success,
                error_message=str(error),
                degraded_features=self._get_degraded_features(service_name),
                retry_count=current_status.retry_count + 1,
                next_retry=self._calculate_next_retry(current_status.retry_count + 1),
                response_time_ms=None,
                metadata={},
            )

            # Record failure for circuit breaker
            self._record_failure(service_name)

            # Execute degraded mode callbacks
            await self._execute_degraded_mode_callbacks(service_name)

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter"""
        delay = min(
            self.retry_config.base_delay * (self.retry_config.exponential_base ** attempt),
            self.retry_config.max_delay
        )
        
        if self.retry_config.jitter:
            # Add jitter to prevent thundering herd
            jitter = random.uniform(0.1, 0.3) * delay
            delay += jitter
        
        return delay

    def _calculate_next_retry(self, retry_count: int) -> datetime:
        """Calculate next retry time"""
        delay = self._calculate_retry_delay(retry_count)
        return datetime.utcnow() + timedelta(seconds=delay)

    def _get_degraded_features(self, service_name: str) -> List[str]:
        """Get features that should be disabled when service is unavailable"""
        feature_map = {
            "redis": ["caching", "session_persistence", "rate_limiting"],
            "database": ["data_persistence", "user_management", "audit_logging"],
        }
        
        if service_name in self.health_status:
            connection_type = self.health_status[service_name].connection_type.value
            return feature_map.get(connection_type, [])
        
        return []

    def _is_circuit_breaker_open(self, service_name: str) -> bool:
        """Check if circuit breaker is open for a service"""
        if service_name not in self.circuit_breakers:
            return False
        
        breaker = self.circuit_breakers[service_name]
        if breaker["failure_count"] < self.retry_config.circuit_breaker_threshold:
            return False
        
        # Check if timeout has passed
        if datetime.utcnow() > breaker["next_attempt"]:
            # Reset to half-open state
            breaker["failure_count"] = 0
            return False
        
        return True

    def _record_failure(self, service_name: str):
        """Record a failure for circuit breaker logic"""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = {
                "failure_count": 0,
                "next_attempt": datetime.utcnow(),
            }
        
        breaker = self.circuit_breakers[service_name]
        breaker["failure_count"] += 1
        
        if breaker["failure_count"] >= self.retry_config.circuit_breaker_threshold:
            breaker["next_attempt"] = datetime.utcnow() + timedelta(
                seconds=self.retry_config.circuit_breaker_timeout
            )
            logger.warning(f"Circuit breaker opened for {service_name}")

    def _reset_circuit_breaker(self, service_name: str):
        """Reset circuit breaker for a service"""
        if service_name in self.circuit_breakers:
            self.circuit_breakers[service_name]["failure_count"] = 0
            logger.info(f"Circuit breaker reset for {service_name}")

    async def _handle_status_change(self, service_name: str, old_status: ServiceStatus, new_status: ServiceStatus):
        """Handle service status changes"""
        logger.info(f"Service {service_name} status changed: {old_status} -> {new_status}")
        
        if old_status == ServiceStatus.HEALTHY and new_status in [ServiceStatus.DEGRADED, ServiceStatus.UNAVAILABLE]:
            await self._execute_degraded_mode_callbacks(service_name)
        elif old_status in [ServiceStatus.DEGRADED, ServiceStatus.UNAVAILABLE] and new_status == ServiceStatus.HEALTHY:
            await self._execute_recovery_callbacks(service_name)

    async def _execute_degraded_mode_callbacks(self, service_name: str):
        """Execute callbacks when service enters degraded mode"""
        callbacks = self.degraded_mode_callbacks.get(service_name, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(service_name)
                else:
                    callback(service_name)
            except Exception as e:
                logger.error(f"Error executing degraded mode callback for {service_name}: {e}")

    async def _execute_recovery_callbacks(self, service_name: str):
        """Execute callbacks when service recovers"""
        callbacks = self.recovery_callbacks.get(service_name, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(service_name)
                else:
                    callback(service_name)
            except Exception as e:
                logger.error(f"Error executing recovery callback for {service_name}: {e}")

    async def _monitoring_loop(self, check_interval: float):
        """Background monitoring loop"""
        while not self._shutdown_event.is_set():
            try:
                # Check all registered services
                for service_name in list(self.health_status.keys()):
                    try:
                        await self.check_service_health(service_name)
                    except Exception as e:
                        logger.error(f"Error checking health for {service_name}: {e}")
                
                # Wait for next check
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=check_interval)
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue monitoring
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying


# Global instance
_connection_health_manager: Optional[ConnectionHealthManager] = None


def get_connection_health_manager() -> ConnectionHealthManager:
    """Get global connection health manager instance"""
    global _connection_health_manager
    if _connection_health_manager is None:
        _connection_health_manager = ConnectionHealthManager()
    return _connection_health_manager


async def initialize_connection_health_manager(
    retry_config: Optional[RetryConfig] = None,
    start_monitoring: bool = True,
    check_interval: float = 30.0,
) -> ConnectionHealthManager:
    """Initialize and start the global connection health manager"""
    global _connection_health_manager
    _connection_health_manager = ConnectionHealthManager(retry_config)
    
    if start_monitoring:
        await _connection_health_manager.start_monitoring(check_interval)
    
    return _connection_health_manager


async def shutdown_connection_health_manager():
    """Shutdown the global connection health manager"""
    global _connection_health_manager
    if _connection_health_manager:
        await _connection_health_manager.stop_monitoring()
        _connection_health_manager = None