"""
Lazy Loading and Resource Management System for AI-Karen.
Implements on-demand service initialization and resource cleanup.
"""

import asyncio
import logging
import os
import threading
import time
from typing import Dict, Any, Optional, Set, TypeVar, Generic, Callable
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

ServiceType = TypeVar("ServiceType")


class ServiceState(Enum):
    """Service lifecycle states."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    IDLE = "idle"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass
class ServiceMetrics:
    """Metrics for service usage and performance."""

    last_used: datetime
    usage_count: int
    initialization_time: float
    total_runtime: float
    memory_usage_mb: float
    cpu_usage_percent: float


class LazyService(Generic[ServiceType]):
    """
    Lazy wrapper for services that initializes only when needed.
    Includes automatic cleanup and resource monitoring.
    """

    def __init__(
        self,
        name: str,
        factory: Callable[[], ServiceType],
        idle_timeout: float = 300.0,  # 5 minutes
        cleanup_callback: Optional[Callable[[ServiceType], None]] = None,
        max_memory_mb: Optional[float] = None,
        priority: int = 1,  # 1=low, 5=critical
    ):
        self.name = name
        self.factory = factory
        self.idle_timeout = idle_timeout
        self.cleanup_callback = cleanup_callback
        self.max_memory_mb = max_memory_mb
        self.priority = priority

        self._service: Optional[ServiceType] = None
        self._state = ServiceState.UNINITIALIZED
        self._lock = threading.RLock()
        self._metrics = ServiceMetrics(
            last_used=datetime.now(),
            usage_count=0,
            initialization_time=0.0,
            total_runtime=0.0,
            memory_usage_mb=0.0,
            cpu_usage_percent=0.0,
        )
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get(self) -> ServiceType:
        """Get the service, initializing if necessary."""
        async with self._get_lock():
            if self._service is None and self._state != ServiceState.ERROR:
                await self._initialize()

            if self._service is not None:
                self._metrics.last_used = datetime.now()
                self._metrics.usage_count += 1
                self._schedule_cleanup()
                return self._service
            else:
                raise RuntimeError(f"Service {self.name} failed to initialize")

    async def _initialize(self) -> None:
        """Initialize the service."""
        if self._state == ServiceState.INITIALIZING:
            return  # Already initializing

        self._state = ServiceState.INITIALIZING
        start_time = time.time()

        try:
            logger.info(f"🔧 Initializing lazy service: {self.name}")
            res = self.factory()
            if asyncio.iscoroutine(res):
                self._service = await res
            else:
                self._service = res

            # If service has async initialization
            if hasattr(self._service, "initialize") and callable(
                getattr(self._service, "initialize")
            ):
                await self._service.initialize()

            self._metrics.initialization_time = time.time() - start_time
            self._state = ServiceState.READY

            logger.info(
                f"✅ Service {self.name} initialized in {self._metrics.initialization_time:.2f}s"
            )

        except Exception as e:
            self._state = ServiceState.ERROR
            logger.error(f"❌ Failed to initialize service {self.name}: {e}")
            raise

    def _schedule_cleanup(self) -> None:
        """Schedule cleanup after idle timeout."""
        if self._cleanup_task:
            self._cleanup_task.cancel()

        self._cleanup_task = asyncio.create_task(self._auto_cleanup())

    async def _auto_cleanup(self) -> None:
        """Automatically cleanup service after idle timeout."""
        try:
            await asyncio.sleep(self.idle_timeout)

            # Check if still idle
            time_since_use = (datetime.now() - self._metrics.last_used).total_seconds()
            if (
                time_since_use >= self.idle_timeout
                and self._state == ServiceState.READY
            ):
                await self.cleanup()

        except asyncio.CancelledError:
            pass  # Normal cancellation

    async def cleanup(self) -> None:
        """Cleanup the service."""
        async with self._get_lock():
            if self._service is not None and self._state != ServiceState.SHUTDOWN:
                self._state = ServiceState.SHUTTING_DOWN

                try:
                    logger.info(f"🧹 Cleaning up service: {self.name}")

                    # Call custom cleanup if provided
                    if self.cleanup_callback:
                        self.cleanup_callback(self._service)

                    # Call service cleanup if available
                    if hasattr(self._service, "cleanup") and callable(
                        getattr(self._service, "cleanup")
                    ):
                        await self._service.cleanup()

                    self._service = None
                    self._state = ServiceState.SHUTDOWN

                    logger.info(f"✅ Service {self.name} cleaned up")

                except Exception as e:
                    logger.error(f"❌ Error cleaning up service {self.name}: {e}")

    @asynccontextmanager
    async def _get_lock(self):
        """Async context manager for thread-safe operations."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        try:
            yield
        finally:
            try:
                self._lock.release()
            except RuntimeError:
                # Lock may already be released if initialization raised.
                pass

    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._service is not None and self._state == ServiceState.READY

    @property
    def state(self) -> ServiceState:
        """Get current service state."""
        return self._state

    @property
    def metrics(self) -> ServiceMetrics:
        """Get service metrics."""
        return self._metrics


class ResourceManager:
    """
    Manages system resources and automatically cleans up services
    when resource limits are exceeded.
    """

    def __init__(
        self,
        max_memory_mb: Optional[float] = None,
        max_cpu_percent: Optional[float] = None,
        check_interval: float = 30.0,
    ):
        self.check_interval = check_interval
        self._memory_ratio = self._get_env_float("KAREN_MAX_MEMORY_RATIO", 0.95)
        self._memory_reserve_mb = self._get_env_float("KAREN_MEMORY_RESERVE_MB", 512.0)
        self._minimum_memory_mb = self._get_env_float("KAREN_MIN_MEMORY_MB", 2048.0)
        self._cpu_threshold_auto = self._get_env_float(
            "KAREN_CPU_AUTO_THRESHOLD_PERCENT", 90.0
        )
        self._limit_log_delta_mb = self._get_env_float(
            "KAREN_RESOURCE_LIMIT_LOG_DELTA_MB", 512.0
        )

        self._force_full_startup = (
            os.getenv("KAREN_FORCE_FULL_STARTUP", "true").lower() == "true"
        )
        self._detected_memory_limit_mb = self._detect_memory_limit_mb()
        self.max_memory_mb = max_memory_mb or self._detect_memory_threshold_mb()

        if self._force_full_startup:
            logger.info(
                "🚀 KAREN_FORCE_FULL_STARTUP enabled: Relaxing memory ceiling to 8GB for critical services"
            )
            self.max_memory_mb = max(self.max_memory_mb, 8192.0)

        self.max_cpu_percent = max_cpu_percent or self._detect_cpu_threshold_percent()

        self._services: Dict[str, LazyService] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._enabled = True
        self._warning_cooldown_seconds = float(
            os.getenv("KAREN_RESOURCE_WARNING_COOLDOWN_SECONDS", "300")
        )
        self._last_warning_at: Optional[float] = None
        self._last_warning_level: Optional[tuple[int, int]] = None
        self._last_logged_limits: tuple[float, float] = (
            self.max_memory_mb,
            self.max_cpu_percent,
        )

    def register_service(self, service: LazyService) -> None:
        """Register a service for resource monitoring."""
        self._services[service.name] = service
        logger.debug(f"Registered service for resource monitoring: {service.name}")

    def unregister_service(self, name: str) -> None:
        """Unregister a service."""
        if name in self._services:
            del self._services[name]
            logger.debug(f"Unregistered service: {name}")

    async def start_monitoring(self) -> None:
        """Start resource monitoring."""
        if self._monitoring_task is None:
            self._monitoring_task = asyncio.create_task(self._monitor_resources())
            logger.info("🔍 Resource monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop resource monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            self._monitoring_task = None
            logger.info("🛑 Resource monitoring stopped")

    async def _monitor_resources(self) -> None:
        """Monitor system resources and cleanup if needed."""
        while self._enabled:
            try:
                await asyncio.sleep(self.check_interval)
                self._refresh_dynamic_limits()

                # Get current resource usage
                memory_usage = await self._get_memory_usage()
                cpu_usage = await self._get_cpu_usage()

                # Check if cleanup is needed
                if (
                    memory_usage > self.max_memory_mb
                    or cpu_usage > self.max_cpu_percent
                ):
                    if self._should_emit_warning(memory_usage, cpu_usage):
                        logger.warning(
                            "🚨 Resource limits exceeded - Memory: %.1fMB / %.1fMB, CPU: %.1f%% / %.1f%%",
                            memory_usage,
                            self.max_memory_mb,
                            cpu_usage,
                            self.max_cpu_percent,
                        )
                    cleaned_count = await self._cleanup_idle_services()
                    self._reconcile_runtime_memory_limit(memory_usage, cleaned_count)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in resource monitoring: {e}")

    def _get_env_float(self, name: str, default: float) -> float:
        """Parse float configuration with fallback."""
        raw_value = os.getenv(name, "").strip()
        if not raw_value:
            return default
        try:
            return float(raw_value)
        except ValueError:
            logger.warning(
                "Invalid %s=%s; using default %.2f", name, raw_value, default
            )
            return default

    def _is_auto_env(self, name: str) -> bool:
        """Check if an environment setting should use dynamic detection."""
        return os.getenv(name, "").strip().lower() in {"", "auto", "dynamic"}

    def _detect_memory_threshold_mb(self) -> float:
        """Detect a sane memory threshold from cgroup/system limits."""
        env_value = os.getenv("KAREN_MAX_MEMORY_MB", "").strip().lower()
        if env_value and env_value not in {"auto", "dynamic"}:
            try:
                return float(env_value)
            except ValueError:
                logger.warning(
                    "Invalid KAREN_MAX_MEMORY_MB=%s; using dynamic detection", env_value
                )

        return self._compute_adaptive_memory_threshold_mb()

    def _compute_adaptive_memory_threshold_mb(self) -> float:
        """Compute the runtime-safe memory threshold from detected limits only."""
        limit_mb = self._detected_memory_limit_mb
        reserve_adjusted_mb = max(0.0, limit_mb - self._memory_reserve_mb)
        ratio_adjusted_mb = limit_mb * self._memory_ratio
        adaptive_threshold_mb = (
            min(ratio_adjusted_mb, reserve_adjusted_mb)
            if reserve_adjusted_mb
            else ratio_adjusted_mb
        )
        return max(self._minimum_memory_mb, adaptive_threshold_mb)

    def _detect_cpu_threshold_percent(self) -> float:
        """Detect a CPU threshold with support for explicit overrides."""
        env_value = os.getenv("KAREN_MAX_CPU_PERCENT", "").strip().lower()
        if env_value and env_value not in {"auto", "dynamic"}:
            try:
                return float(env_value)
            except ValueError:
                logger.warning(
                    "Invalid KAREN_MAX_CPU_PERCENT=%s; using dynamic detection",
                    env_value,
                )
        return min(95.0, max(70.0, self._cpu_threshold_auto))

    def _detect_memory_limit_mb(self) -> float:
        """Detect memory limit from cgroup or host memory."""
        cgroup_candidates = (
            "/sys/fs/cgroup/memory.max",
            "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        )
        for path in cgroup_candidates:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = handle.read().strip()
                if not raw or raw == "max":
                    continue
                limit_bytes = int(raw)
                # Ignore bogus "no real limit" values.
                if limit_bytes <= 0 or limit_bytes >= 1 << 60:
                    continue
                return limit_bytes / 1024 / 1024
            except Exception:
                continue

        try:
            import psutil

            return psutil.virtual_memory().total / 1024 / 1024
        except ImportError:
            return 2048.0

    def _refresh_dynamic_limits(self) -> None:
        """Refresh dynamic thresholds when auto mode is enabled."""
        previous_limits = (self.max_memory_mb, self.max_cpu_percent)
        self._detected_memory_limit_mb = self._detect_memory_limit_mb()

        if self._is_auto_env("KAREN_MAX_MEMORY_MB"):
            self.max_memory_mb = self._detect_memory_threshold_mb()
        if self._is_auto_env("KAREN_MAX_CPU_PERCENT"):
            self.max_cpu_percent = self._detect_cpu_threshold_percent()

        memory_delta = abs(self.max_memory_mb - self._last_logged_limits[0])
        cpu_delta = abs(self.max_cpu_percent - self._last_logged_limits[1])
        if memory_delta >= self._limit_log_delta_mb or cpu_delta >= 5.0:
            logger.info(
                "Adjusted resource limits dynamically - Memory: %.1fMB -> %.1fMB, CPU: %.1f%% -> %.1f%%",
                previous_limits[0],
                self.max_memory_mb,
                previous_limits[1],
                self.max_cpu_percent,
            )
            self._last_logged_limits = (self.max_memory_mb, self.max_cpu_percent)

    def _should_emit_warning(self, memory_usage: float, cpu_usage: float) -> bool:
        """Avoid warning spam for the same steady-state pressure level."""
        now = time.time()
        level = (
            int(memory_usage // 256),
            int(cpu_usage // 10),
        )
        if self._last_warning_at is None:
            self._last_warning_at = now
            self._last_warning_level = level
            return True
        if level != self._last_warning_level:
            self._last_warning_at = now
            self._last_warning_level = level
            return True
        if now - self._last_warning_at >= self._warning_cooldown_seconds:
            self._last_warning_at = now
            return True
        return False

    async def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil

            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0

    async def _get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            import psutil

            return psutil.cpu_percent(interval=1)
        except ImportError:
            return 0.0

    def _compute_idle_cleanup_threshold(
        self,
        memory_usage: float,
        cpu_usage: float,
    ) -> float:
        """Scale idle cleanup aggressiveness with current pressure."""
        memory_ratio = (
            memory_usage / self.max_memory_mb if self.max_memory_mb > 0 else 0.0
        )
        cpu_ratio = (
            cpu_usage / self.max_cpu_percent if self.max_cpu_percent > 0 else 0.0
        )
        severity = max(memory_ratio, cpu_ratio)
        if severity >= 1.50:
            return 15.0
        if severity >= 1.25:
            return 30.0
        if severity >= 1.10:
            return 45.0
        return 60.0

    def _reconcile_runtime_memory_limit(
        self, memory_usage: float, cleaned_count: int
    ) -> None:
        """
        Lift stale explicit memory ceilings to the detected container-safe threshold
        when baseline runtime footprint already exceeds the configured limit.
        """
        if cleaned_count > 0 or self._is_auto_env("KAREN_MAX_MEMORY_MB"):
            return

        adaptive_limit_mb = self._compute_adaptive_memory_threshold_mb()
        if adaptive_limit_mb <= self.max_memory_mb:
            return

        # Only reconcile when runtime baseline already exceeds the stale ceiling.
        if memory_usage <= self.max_memory_mb:
            return

        previous_limit = self.max_memory_mb
        self.max_memory_mb = adaptive_limit_mb
        self._last_logged_limits = (self.max_memory_mb, self.max_cpu_percent)
        logger.warning(
            "Adjusted stale explicit memory ceiling to runtime-safe threshold - Memory: %.1fMB -> %.1fMB (detected container limit %.1fMB)",
            previous_limit,
            self.max_memory_mb,
            self._detected_memory_limit_mb,
        )

    async def _cleanup_idle_services(self) -> int:
        """Cleanup idle services based on priority and usage."""
        # Sort services by priority (low priority first) and last used time
        services_to_cleanup = []
        memory_usage = await self._get_memory_usage()
        cpu_usage = await self._get_cpu_usage()
        idle_cleanup_threshold = self._compute_idle_cleanup_threshold(
            memory_usage, cpu_usage
        )

        for service in self._services.values():
            if service.is_initialized:
                idle_time = (datetime.now() - service.metrics.last_used).total_seconds()
                services_to_cleanup.append((service, idle_time))

        # Sort by priority (ascending) then by idle time (descending)
        services_to_cleanup.sort(key=lambda x: (x[0].priority, -x[1]))

        # Cleanup services until resources are under limits
        cleaned_count = 0
        for service, idle_time in services_to_cleanup:
            if idle_time > idle_cleanup_threshold:
                await service.cleanup()
                cleaned_count += 1

                # Check if we're under limits now
                memory_usage = await self._get_memory_usage()
                cpu_usage = await self._get_cpu_usage()

                if (
                    memory_usage <= self.max_memory_mb * 0.8
                    and cpu_usage <= self.max_cpu_percent * 0.8
                ):
                    break

        if cleaned_count > 0:
            logger.info(
                "🧹 Cleaned up %d idle services to free resources (idle threshold %.0fs)",
                cleaned_count,
                idle_cleanup_threshold,
            )
        return cleaned_count


class LazyServiceRegistry:
    """
    Registry for lazy services with automatic resource management.
    """

    def __init__(self):
        self._services: Dict[str, LazyService] = {}
        # Configure resource manager with dynamic defaults unless explicitly overridden.
        raw_max_memory = os.getenv("KAREN_MAX_MEMORY_MB", "auto").strip().lower()
        raw_max_cpu = os.getenv("KAREN_MAX_CPU_PERCENT", "auto").strip().lower()
        max_memory = (
            None if raw_max_memory in {"", "auto", "dynamic"} else float(raw_max_memory)
        )
        max_cpu = None if raw_max_cpu in {"", "auto", "dynamic"} else float(raw_max_cpu)
        check_interval = float(
            os.getenv("KAREN_RESOURCE_CHECK_INTERVAL", "30.0")
        )  # Check every 30s - less frequent

        self._resource_manager = ResourceManager(
            max_memory_mb=max_memory,
            max_cpu_percent=max_cpu,
            check_interval=check_interval,
        )
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the service registry."""
        if not self._initialized:
            await self._resource_manager.start_monitoring()
            self._initialized = True
            logger.info("🚀 Lazy service registry initialized")

    async def shutdown(self) -> None:
        """Shutdown all services and resource monitoring."""
        await self._resource_manager.stop_monitoring()

        # Cleanup all services
        cleanup_tasks = []
        for service in self._services.values():
            if service.is_initialized:
                cleanup_tasks.append(service.cleanup())

        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        self._services.clear()
        self._initialized = False
        logger.info("🛑 Lazy service registry shutdown complete")

    def register(
        self,
        name: str,
        factory: Callable[[], ServiceType],
        idle_timeout: float = 300.0,
        cleanup_callback: Optional[Callable[[ServiceType], None]] = None,
        max_memory_mb: Optional[float] = None,
        priority: int = 1,
    ) -> LazyService[ServiceType]:
        """Register a new lazy service."""
        service = LazyService(
            name=name,
            factory=factory,
            idle_timeout=idle_timeout,
            cleanup_callback=cleanup_callback,
            max_memory_mb=max_memory_mb,
            priority=priority,
        )

        self._services[name] = service
        self._resource_manager.register_service(service)

        logger.debug(f"Registered lazy service: {name}")
        return service

    def get_service(self, name: str) -> Optional[LazyService]:
        """Get a registered service."""
        return self._services.get(name)

    async def get_service_instance(self, name: str) -> Any:
        """Get an instance of a service, initializing if needed."""
        service = self.get_service(name)
        if service:
            return await service.get()
        else:
            raise KeyError(f"Service not registered: {name}")

    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """List all registered services and their status."""
        result = {}
        for name, service in self._services.items():
            result[name] = {
                "state": service.state.value,
                "is_initialized": service.is_initialized,
                "usage_count": service.metrics.usage_count,
                "last_used": service.metrics.last_used.isoformat(),
                "priority": service.priority,
            }
        return result


# Global lazy service registry
lazy_registry = LazyServiceRegistry()


# Convenience functions for common services
def create_nlp_service_factory():
    """Factory for canonical spaCy service."""

    def factory():
        from ai_karen_engine.core.memory.signals.spacy_service import SpacyService

        return SpacyService()

    return factory


def create_chat_orchestrator_factory():
    """Factory for Chat orchestrator service."""

    def factory():
        from ai_karen_engine.core.langgraph_orchestrator import (
            get_default_orchestrator,
        )

        return get_default_orchestrator()

    return factory


def create_langgraph_orchestrator_factory():
    """Factory for LangGraph orchestrator service."""

    def factory():
        from ai_karen_engine.core.services.base import ServiceConfig
        from ai_karen_engine.core.langgraph_orchestrator import (
            LangGraphOrchestrator,
        )

        return LangGraphOrchestrator(
            ServiceConfig(
                name="langgraph_orchestrator", dependencies=[], config={},
            )
        )

    return factory


def create_memory_service_factory():
    def factory():
        from ai_karen_engine.core.memory.service_factory import (
            create_unified_memory_service,
        )

        return create_unified_memory_service()

    return factory


def create_conversation_service_factory():
    async def factory():
        from ai_karen_engine.services.memory.conversation_service import ConversationService
        from ai_karen_engine.database.conversation_manager import ConversationManager
        from ai_karen_engine.database.client import MultiTenantPostgresClient

        # Get memory service from lazy registry
        memory_service = await lazy_registry.get_service_instance("memory_service")

        # Create database client and conversation manager
        db_client = MultiTenantPostgresClient()
        conversation_manager = ConversationManager(db_client=db_client)

        return ConversationService(
            base_conversation_manager=conversation_manager,
            memory_service=memory_service,
        )

    return factory


def create_persona_service_factory():
    async def factory():
        from ai_karen_engine.services.persona.persona_service import get_persona_service

        return get_persona_service()

    return factory


def create_analytics_service_factory():
    """Factory for analytics service."""

    def factory():
        from ai_karen_engine.services.monitoring.analytics_service import AnalyticsService

        return AnalyticsService()

    return factory


async def setup_lazy_services():
    """Setup all lazy services with appropriate configurations."""
    logger.info("🔍 DEBUG: Setting up lazy services...")
    await lazy_registry.initialize()

    # Get timeout configurations from environment - balanced cleanup
    # Get timeout configurations from environment - robust production settings
    nlp_timeout = float(os.getenv("KAREN_NLP_IDLE_TIMEOUT", "300.0"))  # 5 minutes
    orchestrator_timeout = float(
        os.getenv("KAREN_ORCHESTRATOR_IDLE_TIMEOUT", "300.0")
    )  # 5 minutes
    analytics_timeout = float(
        os.getenv("KAREN_ANALYTICS_IDLE_TIMEOUT", "120.0")
    )  # 2 minutes

    logger.info(
        f"🔍 DEBUG: Configuration - NLP timeout: {nlp_timeout}, Orchestrator timeout: {orchestrator_timeout}, Analytics timeout: {analytics_timeout}"
    )

    # Register NLP services (low priority, shorter timeout for memory efficiency)
    logger.info("🔍 DEBUG: Registering NLP service...")
    lazy_registry.register(
        name="nlp_service",
        factory=create_nlp_service_factory(),
        idle_timeout=nlp_timeout,
        priority=2,
        max_memory_mb=256,  # Reduced from 512MB
    )

    # Register LangGraph orchestrator (medium priority, aggressive cleanup)
    logger.info("🔍 DEBUG: Registering LangGraph orchestrator...")
    lazy_registry.register(
        name="langgraph_orchestrator",
        factory=create_langgraph_orchestrator_factory(),
        idle_timeout=orchestrator_timeout,
        priority=3,
    )

    # Register Chat orchestrator (high priority for chat functionality)
    logger.info("🔍 DEBUG: Registering Chat orchestrator...")
    lazy_registry.register(
        name="chat_orchestrator",
        factory=create_chat_orchestrator_factory(),
        idle_timeout=orchestrator_timeout,
        priority=4,
    )

    # Register memory service (high priority)
    logger.info("🔍 DEBUG: Registering memory service...")
    lazy_registry.register(
        name="memory_service",
        factory=create_memory_service_factory(),
        idle_timeout=orchestrator_timeout * 2,
        priority=4,
    )

    # Register conversation service (high priority, critical for history)
    logger.info("🔍 DEBUG: Registering conversation service...")
    lazy_registry.register(
        name="conversation_service",
        factory=create_conversation_service_factory(),
        idle_timeout=orchestrator_timeout * 2,
        priority=5,
    )

    # Register persona service (high priority, user-facing behavior control)
    logger.info("🔍 DEBUG: Registering persona service...")
    lazy_registry.register(
        name="persona_service",
        factory=create_persona_service_factory(),
        idle_timeout=orchestrator_timeout * 2,
        priority=4,
    )

    # Register analytics service (low priority, very aggressive cleanup)
    logger.info("🔍 DEBUG: Registering analytics service...")
    lazy_registry.register(
        name="analytics_service",
        factory=create_analytics_service_factory(),
        idle_timeout=analytics_timeout,
        priority=1,
    )

    logger.info(f"🔍 DEBUG: Lazy services registered: {lazy_registry.list_services()}")
    logger.info("✅ Lazy services configured")


async def cleanup_lazy_services():
    """Cleanup all lazy services."""
    await lazy_registry.shutdown()


class LazyServiceManager:
    """
    Main manager for lazy loading services and resource optimization.
    """

    def __init__(self):
        self.services: Dict[str, LazyService] = {}
        self.enabled = os.getenv("KARI_LAZY_LOADING", "false").lower() == "true"
        self.minimal_mode = os.getenv("KARI_MINIMAL_STARTUP", "false").lower() == "true"
        self.ultra_minimal = os.getenv("KARI_ULTRA_MINIMAL", "false").lower() == "true"
        self._initialized = False

    async def initialize(self):
        """Initialize the lazy service manager."""
        if self._initialized:
            return

        if self.enabled:
            await setup_lazy_services()
            logger.info("🚀 Lazy Service Manager initialized")
        else:
            logger.info("⚡ Lazy loading disabled, using eager initialization")

        self._initialized = True

    def get_service(self, name: str) -> Any:
        """Get a service, initializing it lazily if needed."""
        if not self.enabled:
            # Fall back to eager loading
            return self._get_eager_service(name)

        if name not in self.services:
            logger.warning(f"Service '{name}' not registered in lazy manager")
            return None

        return self.services[name].get()

    def _get_eager_service(self, name: str) -> Any:
        """Get service using eager initialization (fallback)."""
        # Import and create services directly for non-lazy mode
        if name == "nlp_service":
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService

            return SpacyService()
        elif name == "langgraph_orchestrator":
            from ai_karen_engine.core.services.base import ServiceConfig
            from ai_karen_engine.core.langgraph_orchestrator import (
                LangGraphOrchestrator,
            )

            return LangGraphOrchestrator(
                ServiceConfig(
                    name="langgraph_orchestrator", dependencies=[], config={}
                )
            )
        elif name == "analytics_service":
            from ai_karen_engine.services.monitoring.analytics_service import AnalyticsService

            return AnalyticsService()
        else:
            logger.warning(f"Unknown service: {name}")
            return None

    async def shutdown(self):
        """Shutdown all managed services."""
        await cleanup_lazy_services()
        logger.info("🛑 Lazy Service Manager shutdown complete")
