"""
Chat Runtime Control Plane — Single Authoritative Runtime Controller.

This module is the ONE authority for chat runtime mode decisions.
All chat entry points (standard, copilot, websocket, streaming) must
consult this control plane before processing any request.

Modes:
  - normal:             Full orchestrator with all dependencies healthy.
  - degraded:           Dynamic — uses whatever is available (memory, tools,
                        providers) and reports honestly what's missing.
  - maintenance:        Operator-activated planned maintenance (distinct from
                        failure). Overrides normal/degraded when active.
  - emergency_fallback: Hardcoded last-resort, independent of DB/Redis/model.

Priority order (fixed):
  1. maintenance  (if explicitly enabled by operator)
  2. normal       (if all critical deps healthy)
  3. degraded     (if normal unavailable)
  4. emergency_fallback (if nothing else works)

Design rules:
  - Dependency failures NEVER auto-activate planned maintenance.
  - Anti-flapping requires N consecutive healthy probes before upgrade.
  - Emergency fallback is fully self-contained (no I/O).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums & Value Objects
# ---------------------------------------------------------------------------


class RuntimeMode(str, Enum):
    """Runtime mode enumeration — the four possible states."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    EMERGENCY_FALLBACK = "emergency_fallback"


class DependencyStatus(str, Enum):
    """Dependency health status — reported by probes."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Centralized Runtime Constants
# ---------------------------------------------------------------------------


class RuntimeConstants:
    """Centralized strings and labels for runtime communication."""

    # Standard fallback messages
    EMERGENCY_UNAVAILABLE = "Service temporarily unavailable. Please try again shortly."
    MAINTENANCE_MESSAGE = (
        "We're performing scheduled improvements to enhance your experience."
    )

    # Source labels
    SOURCE_DEGRADED_STATIC = "degraded_fallback"
    SOURCE_EMERGENCY = "emergency_fallback"


# ---------------------------------------------------------------------------
# Structured Response Contracts
# ---------------------------------------------------------------------------


@dataclass
class DegradedCapabilities:
    """Declares what degraded mode can currently do based on dynamic probe results."""

    memory_available: bool = False
    tools_available: bool = False
    plugins_available: bool = False
    external_providers_available: bool = False
    streaming_supported: bool = False
    local_model_available: bool = False
    description: str = "Minimal text-only assistant"

    @property
    def is_minimal(self) -> bool:
        return not any(
            [
                self.memory_available,
                self.tools_available,
                self.plugins_available,
                self.external_providers_available,
                self.local_model_available,
            ]
        )


@dataclass
class MaintenanceResponse:
    """Structured maintenance response — sent to clients during planned maintenance."""

    mode: str = "maintenance"
    message: str = RuntimeConstants.MAINTENANCE_MESSAGE
    estimated_completion_time: Optional[str] = None
    notification_supported: bool = True
    notification_request_allowed: bool = True
    retry_after_seconds: int = 300
    system_status_code: int = 503
    reason: Optional[str] = None
    started_at: Optional[str] = None


@dataclass
class EmergencyFallbackResponse:
    """
    Emergency fallback response — fully self-contained.
    MUST work without DB, Redis, or any model runtime.
    """

    mode: str = "emergency_fallback"
    message: str = RuntimeConstants.EMERGENCY_UNAVAILABLE
    retry_after_seconds: int = 60
    system_status_code: int = 503
    support_hint: str = "If this persists, please contact support."


@dataclass
class DegradedResponse:
    """Structured degraded mode response with available capabilities."""

    mode: str = "degraded"
    message: str = "Service operating in limited mode"
    capabilities: Optional[DegradedCapabilities] = None
    is_minimal: bool = False
    retry_after_seconds: int = 60
    system_status_code: int = 503
    support_hint: str = "If this persists, please contact support."


@dataclass
class DependencyHealth:
    """Health snapshot for a single dependency."""

    name: str
    status: DependencyStatus
    reason: Optional[str] = None
    checked_at: Optional[datetime] = None
    response_time_ms: float = 0.0
    consecutive_successes: int = 0
    consecutive_failures: int = 0

    def __post_init__(self):
        if self.checked_at is None:
            self.checked_at = datetime.utcnow()


@dataclass
class RuntimeSnapshot:
    """Complete snapshot of current runtime state — for API/admin consumption."""

    mode: RuntimeMode
    maintenance_active: bool
    maintenance_message: Optional[str]
    estimated_completion_time: Optional[str]
    normal_ready: bool
    degraded_ready: bool
    degraded_capabilities: Optional[DegradedCapabilities]
    dependencies: Dict[str, DependencyHealth]
    last_transition_at: Optional[str]
    last_transition_reason: Optional[str]


@dataclass
class MaintenanceStateSnapshot:
    """Canonical maintenance state mirrored from the authoritative backend owner."""

    enabled: bool
    reason: Optional[str]
    message: Optional[str]
    estimated_completion_time: Optional[str]
    notifications_supported: bool
    started_at: Optional[str]
    last_updated_at: Optional[str]
    auto_end_policy: str
    created_by: Optional[str]
    maintenance_window_id: Optional[str]
    source_of_truth: str = "maintenance_windows"


@dataclass
class RuntimeEnvironmentValidation:
    """Centralized validation result for runtime-control env requirements."""

    valid: bool
    required_in_current_env: bool
    missing_required: List[str] = field(default_factory=list)
    invalid_values: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


RuntimeResponse = Union[
    MaintenanceResponse,
    EmergencyFallbackResponse,
    DegradedResponse,
    None,
]


# ---------------------------------------------------------------------------
# Valid Transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: Dict[RuntimeMode, set] = {
    RuntimeMode.NORMAL: {
        RuntimeMode.DEGRADED,
        RuntimeMode.MAINTENANCE,
        RuntimeMode.EMERGENCY_FALLBACK,
    },
    RuntimeMode.DEGRADED: {
        RuntimeMode.NORMAL,
        RuntimeMode.MAINTENANCE,
        RuntimeMode.EMERGENCY_FALLBACK,
    },
    RuntimeMode.MAINTENANCE: {
        RuntimeMode.NORMAL,
        RuntimeMode.DEGRADED,
        RuntimeMode.EMERGENCY_FALLBACK,
    },
    RuntimeMode.EMERGENCY_FALLBACK: {
        RuntimeMode.NORMAL,
        RuntimeMode.DEGRADED,
        RuntimeMode.MAINTENANCE,
    },
}

_MODE_PRECEDENCE: tuple[RuntimeMode, ...] = (
    RuntimeMode.MAINTENANCE,
    RuntimeMode.NORMAL,
    RuntimeMode.DEGRADED,
    RuntimeMode.EMERGENCY_FALLBACK,
)

_MODE_RANK: Dict[RuntimeMode, int] = {
    RuntimeMode.EMERGENCY_FALLBACK: 0,
    RuntimeMode.DEGRADED: 1,
    RuntimeMode.NORMAL: 2,
    RuntimeMode.MAINTENANCE: 3,
}


# ---------------------------------------------------------------------------
# Dependency Probe Protocol
# ---------------------------------------------------------------------------


class DependencyProbe(Protocol):
    """Protocol for dependency health probes."""

    @property
    def name(self) -> str: ...

    async def check(self) -> DependencyHealth: ...


# ---------------------------------------------------------------------------
# Concrete Probes
# ---------------------------------------------------------------------------


class PostgreSQLProbe:
    """Probes PostgreSQL via SELECT 1."""

    name = "database"

    async def check(self) -> DependencyHealth:
        start = time.time()
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient

            client = MultiTenantPostgresClient()
            elapsed = (time.time() - start) * 1000
            if hasattr(client, "async_comprehensive_health_check"):
                health_result = await client.async_comprehensive_health_check()
                healthy = bool(getattr(health_result, "is_healthy", False))
                reason = (
                    None
                    if healthy
                    else (
                        getattr(health_result, "error_details", None)
                        or getattr(health_result, "message", None)
                        or "Database unhealthy"
                    )
                )
                response_time_ms = getattr(health_result, "response_time_ms", elapsed)
            else:
                healthy = await client.async_health_check()
                reason = None if healthy else "SELECT 1 failed"
                response_time_ms = elapsed
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.HEALTHY
                if healthy
                else DependencyStatus.UNHEALTHY,
                reason=reason,
                response_time_ms=response_time_ms,
            )
        except Exception as e:
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.UNHEALTHY,
                reason=str(e),
                response_time_ms=(time.time() - start) * 1000,
            )


class RedisProbe:
    """Probes Redis via PING through existing connection manager."""

    name = "redis"

    async def check(self) -> DependencyHealth:
        start = time.time()
        from ai_karen_engine.core.memory.redis_connection_manager import (
            get_redis_manager,
        )

        manager = get_redis_manager()
        health = await manager.health_check()
        degraded_mode = bool(health.get("degraded_mode"))
        healthy = bool(health.get("healthy"))
        if healthy:
            status = DependencyStatus.HEALTHY
            reason = None
        else:
            status = DependencyStatus.UNHEALTHY
                reason = (
                    "Redis degraded mode active"
                    if degraded_mode
                    else health.get("error") or "Redis unhealthy"
                )

            return DependencyHealth(
                name=self.name,
                status=status,
                reason=reason,
                response_time_ms=health.get(
                    "response_time_ms", (time.time() - start) * 1000
                ),
            )
        except Exception as e:
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.UNHEALTHY,
                reason=str(e),
                response_time_ms=(time.time() - start) * 1000,
            )


class ProviderRouterProbe:
    """Probes whether at least one LLM provider is available."""

    name = "provider_router"

    async def check(self) -> DependencyHealth:
        start = time.time()
        try:
            from ai_karen_engine.core.expression.gateway import ExpressionGateway
            from ai_karen_engine.core.expression.contracts import ExpressionTask

            gateway = ExpressionGateway()
            test_task = ExpressionTask(
                task_id="health_probe",
                kind="probe",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
                timeout_ms=5000,
                required_capabilities=[],
                forbidden_capabilities=[],
                response_mode="text"
            )
            
            result = await gateway.generate(test_task)
            
            elapsed = (time.time() - start) * 1000
            is_healthy = result.engine_id != "disabled"
            
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.HEALTHY if is_healthy else DependencyStatus.UNHEALTHY,
                reason=None if is_healthy else "No expression engines available",
                response_time_ms=elapsed,
            )
        except Exception as e:
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.UNHEALTHY,
                reason=str(e),
                response_time_ms=(time.time() - start) * 1000,
            )


class MemorySubsystemProbe:
    """Probes whether the memory subsystem is reachable."""

    name = "memory_subsystem"

    async def check(self) -> DependencyHealth:
        start = time.time()
        try:
            from ai_karen_engine.core.services.service_registry import get_service_registry

            registry = get_service_registry()
            svc = await registry.get_service("memory_service")
            elapsed = (time.time() - start) * 1000
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.HEALTHY if svc else DependencyStatus.UNHEALTHY,
                reason=None if svc else "Memory service not found in registry",
                response_time_ms=elapsed,
            )
        except Exception as e:
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.UNHEALTHY,
                reason=str(e),
                response_time_ms=(time.time() - start) * 1000,
            )


class ProviderRegistryProbe:
    """Probes whether at least one provider is registered and available."""

    name = "provider_registry"

    async def check(self) -> DependencyHealth:
        start = time.time()
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            registry = get_provider_registry_service()
            providers = registry.get_all_provider_names()

            elapsed = (time.time() - start) * 1000
            healthy = len(providers) > 0
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.HEALTHY if healthy else DependencyStatus.UNHEALTHY,
                reason=None if healthy else "No providers registered",
                response_time_ms=elapsed,
            )
        except Exception as e:
            return DependencyHealth(
                name=self.name,
                status=DependencyStatus.UNHEALTHY,
                reason=str(e),
                response_time_ms=(time.time() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Chat Runtime Control Plane
# ---------------------------------------------------------------------------


class ChatRuntimeControlPlane:
    """
    Enhanced central authority for chat runtime mode management with hardening features.

    This is the ONE place that decides which mode the system is in.
    All chat entry points must consult this before processing requests.

    Enhanced features:
    - Runtime state persistence with recovery mechanisms
    - Emergency protocol system
    - Circuit breaker integration
    - Enhanced dependency health checks
    - Guaranteed response contracts
    """

    # Critical dependencies required for normal mode
    NORMAL_MODE_DEPS = frozenset(
        {
            "database",
            "redis",
            "provider_router",
            "memory_subsystem",
        }
    )

    def __init__(self):
        # Runtime state
        self._current_mode: RuntimeMode = RuntimeMode.EMERGENCY_FALLBACK  # Safe default
        self._dependency_health: Dict[str, DependencyHealth] = {}
        self._degraded_capabilities: DegradedCapabilities = DegradedCapabilities()

        # Maintenance state (in-memory mirror of DB truth)
        self._maintenance_enabled: bool = False
        self._maintenance_reason: Optional[str] = None
        self._maintenance_message: Optional[str] = None
        self._maintenance_started_at: Optional[datetime] = None
        self._maintenance_eta: Optional[datetime] = None
        self._maintenance_window_id: Optional[str] = None
        self._maintenance_notifications_supported: bool = True
        self._maintenance_last_updated_at: Optional[datetime] = None
        self._maintenance_created_by: Optional[str] = None
        self._maintenance_auto_end_policy: str = "manual"

        # Anti-flapping
        self._stabilization_threshold: int = int(
            os.getenv("KAREN_STABILIZATION_THRESHOLD", "3")
        )
        self._mode_transition_cooldown_s: int = int(
            os.getenv("KAREN_MODE_COOLDOWN_SECONDS", "15")
        )
        self._last_mode_transition: datetime = datetime.utcnow()
        self._last_transition_reason: Optional[str] = None

        # Background tasks
        self._health_check_interval: int = int(
            os.getenv("KAREN_HEALTH_CHECK_INTERVAL", "30")
        )
        self._maintenance_recheck_interval: int = int(
            os.getenv("KAREN_MAINTENANCE_RECHECK_INTERVAL", "60")
        )
        self._health_check_task: Optional[asyncio.Task] = None
        self._maintenance_monitor_task: Optional[asyncio.Task] = None
        self._startup_health_checks_completed: bool = False

        # Probes — registered at init, executed in background loop
        self._probes: List[DependencyProbe] = [
            PostgreSQLProbe(),
            RedisProbe(),
            ProviderRouterProbe(),
            MemorySubsystemProbe(),
            ProviderRegistryProbe(),
        ]

        # Enhanced hardening features
        self._runtime_state_persistence: bool = True
        self._emergency_protocols_active: bool = False
        self._circuit_breaker_state: Dict[str, Any] = {}
        self._response_contracts: Dict[str, Any] = {}
        self._health_check_history: List[Dict[str, Any]] = []
        self._mode_transition_history: List[Dict[str, Any]] = []
        self._failure_thresholds: Dict[str, int] = {
            "normal_to_degraded": 3,
            "degraded_to_emergency": 5,
            "emergency_to_degraded": 2,
            "maintenance_to_normal": 1,
        }
        self._recovery_windows: Dict[str, int] = {
            "normal_recovery": 300,  # 5 minutes
            "degraded_recovery": 600,  # 10 minutes
            "emergency_recovery": 1800,  # 30 minutes
        }

        # Runtime authority state
        self._authority_initialized: bool = False
        self._last_authority_check: Optional[datetime] = None
        self._authority_health_score: float = 0.0
        self._emergency_protocol_triggers: List[str] = []

        # Performance monitoring
        self._performance_metrics: Dict[str, Any] = {
            "mode_changes": 0,
            "health_check_duration": [],
            "response_time": [],
            "error_rate": 0.0,
            "last_healthy_mode": None,
        }

        self._initialized = False

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the control plane: load DB state, run first health check, start loops."""
        if self._initialized:
            return

        logger.info("Initializing Chat Runtime Control Plane")

        # 1. Load persisted state from DB (if DB is available)
        await self._load_runtime_state()

        # 2. Run initial health check to determine starting mode
        await self._run_health_checks()
        self._startup_health_checks_completed = True

        # 3. Determine initial mode from current conditions
        initial_mode = self.resolve_mode_from_current_conditions()
        if initial_mode != self._current_mode:
            self._current_mode = initial_mode
            self._last_transition_reason = "Initial health assessment"
            self._last_mode_transition = datetime.utcnow()

        # 4. Start background monitoring
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._maintenance_monitor_task = asyncio.create_task(
            self._maintenance_monitor_loop()
        )

        # 5. Initialize enhanced runtime authority
        await self.initialize_runtime_authority()

        self._initialized = True
        logger.info(f"Control Plane ready — mode: {self._current_mode.value}")

    async def shutdown(self) -> None:
        """Gracefully stop background tasks."""
        logger.info("Shutting down Chat Runtime Control Plane")
        for task in [self._health_check_task, self._maintenance_monitor_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._initialized = False
        logger.info("Control Plane shutdown complete")

    # -----------------------------------------------------------------------
    # Core Query API — used by all chat entry points
    # -----------------------------------------------------------------------

    async def get_current_mode(self) -> RuntimeMode:
        """Get the current runtime mode. The single source of truth."""
        return self._current_mode

    def get_capabilities(self) -> DegradedCapabilities:
        """Return the current set of derived degraded capabilities."""
        return self._degraded_capabilities

    def get_status(self) -> Dict[str, Any]:
        """Return simplified status for lightweight health checks."""
        return {
            "mode": self._current_mode.value,
            "ready": self._startup_health_checks_completed,
            "degraded": self._current_mode == RuntimeMode.DEGRADED,
            "maintenance": self._maintenance_enabled,
        }

    def get_fallback_provider(self) -> tuple[str, str]:
        """Return (provider, model) for fallback generation."""
        from ai_karen_engine.config.config_manager import (
            get_default_model,
            get_default_provider,
        )

        provider = os.getenv("KARI_DEGRADED_PROVIDER", get_default_provider())
        model = os.getenv("KARI_DEGRADED_MODEL", get_default_model())
        return provider, model

    def get_snapshot(self) -> RuntimeSnapshot:
        """Get complete runtime snapshot for admin/API inspection."""
        return RuntimeSnapshot(
            mode=self._current_mode,
            maintenance_active=self._maintenance_enabled,
            maintenance_message=self._maintenance_message,
            estimated_completion_time=(
                self._maintenance_eta.isoformat() if self._maintenance_eta else None
            ),
            normal_ready=self._is_normal_ready(),
            degraded_ready=self._is_degraded_ready(),
            degraded_capabilities=self._degraded_capabilities,
            dependencies=dict(self._dependency_health),
            last_transition_at=(
                self._last_mode_transition.isoformat()
                if self._last_mode_transition
                else None
            ),
            last_transition_reason=self._last_transition_reason,
        )

    def has_active_maintenance(self) -> bool:
        """Expose maintenance activity without leaking internal fields."""
        return self._maintenance_enabled

    def is_planned_maintenance_active(self) -> bool:
        """
        Planned maintenance is explicit operator state only.
        Dependency failures must never activate this implicitly.
        """
        return self._maintenance_enabled

    def get_active_maintenance_window_id(self) -> Optional[str]:
        """Expose the current maintenance window ID without route-level internals."""
        return self._maintenance_window_id

    def get_maintenance_state_snapshot(self) -> MaintenanceStateSnapshot:
        """Return maintenance state from the canonical backend-owned model mirror."""
        return MaintenanceStateSnapshot(
            enabled=self._maintenance_enabled,
            reason=self._maintenance_reason,
            message=self._maintenance_message,
            estimated_completion_time=(
                self._maintenance_eta.isoformat() if self._maintenance_eta else None
            ),
            notifications_supported=self._maintenance_notifications_supported,
            started_at=(
                self._maintenance_started_at.isoformat()
                if self._maintenance_started_at
                else None
            ),
            last_updated_at=(
                self._maintenance_last_updated_at.isoformat()
                if self._maintenance_last_updated_at
                else None
            ),
            auto_end_policy=self._maintenance_auto_end_policy,
            created_by=self._maintenance_created_by,
            maintenance_window_id=self._maintenance_window_id,
        )

    def validate_runtime_environment(self) -> RuntimeEnvironmentValidation:
        """
        Validate the control-plane-owned runtime env contract.

        Production-like environments must provide explicit DB and Redis config
        instead of relying on dev defaults. Control-plane timing envs must be
        positive integers everywhere.
        """
        env_name = os.getenv("KAREN_ENV", "development").strip().lower()
        required_in_current_env = env_name in {
            "production",
            "staging",
            "public",
            "public-launch",
        }
        missing_required: List[str] = []
        invalid_values: Dict[str, str] = {}
        warnings: List[str] = []

        if required_in_current_env:
            has_database_config = bool(
                os.getenv("DATABASE_URL")
                or os.getenv("POSTGRES_URL")
                or (
                    os.getenv("POSTGRES_HOST")
                    and os.getenv("POSTGRES_USER")
                    and os.getenv("POSTGRES_PASSWORD")
                    and os.getenv("POSTGRES_DB")
                )
            )
            if not has_database_config:
                missing_required.append(
                    "DATABASE_URL or POSTGRES_URL or POSTGRES_HOST/POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB"
                )

            if not os.getenv("REDIS_URL"):
                missing_required.append("REDIS_URL")
        else:
            if not (
                os.getenv("DATABASE_URL")
                or os.getenv("POSTGRES_URL")
                or os.getenv("POSTGRES_HOST")
            ):
                warnings.append(
                    "Database runtime env is not explicitly configured; development defaults may be in use"
                )
            if not os.getenv("REDIS_URL"):
                warnings.append(
                    "REDIS_URL is not explicitly configured; development defaults may be in use"
                )

        for env_var in (
            "KAREN_STABILIZATION_THRESHOLD",
            "KAREN_MODE_COOLDOWN_SECONDS",
            "KAREN_HEALTH_CHECK_INTERVAL",
            "KAREN_MAINTENANCE_RECHECK_INTERVAL",
        ):
            raw = os.getenv(env_var)
            if raw is None:
                continue
            try:
                if int(raw) <= 0:
                    invalid_values[env_var] = "must be a positive integer"
            except ValueError:
                invalid_values[env_var] = "must be a positive integer"

        return RuntimeEnvironmentValidation(
            valid=not missing_required and not invalid_values,
            required_in_current_env=required_in_current_env,
            missing_required=missing_required,
            invalid_values=invalid_values,
            warnings=warnings,
        )

    async def get_runtime_response(self, **context) -> RuntimeResponse:
        """
        Get appropriate response object based on current mode.
        Routes call this to decide what to return to the client.
        """
        mode = self._current_mode

        if mode == RuntimeMode.MAINTENANCE:
            return self._build_maintenance_response()
        elif mode == RuntimeMode.EMERGENCY_FALLBACK:
            # Chat emergency static is owned by the provider/router fallback path.
            # A failed dependency snapshot must degrade chat, not bypass every live
            # provider attempt. Routes still catch orchestrator setup failures and
            # return emergency static only after execution paths fail.
            logger.warning(
                "Runtime is marked emergency_fallback; allowing chat route/provider fallback to execute",
                extra={
                    "runtime_mode": mode.value,
                    "dependencies": {
                        name: health.status.value
                        for name, health in self._dependency_health.items()
                    },
                },
            )
            return None
        elif mode == RuntimeMode.DEGRADED:
            # Let orchestrator handle DEGRADED mode to provide best-effort responses
            return None
        else:
            # NORMAL — return None to signal "proceed with orchestrator"
            return None

    # -----------------------------------------------------------------------
    # Mode Transitions
    # -----------------------------------------------------------------------

    async def transition_mode(self, new_mode: RuntimeMode, reason: str) -> bool:
        """
        Request a mode transition. Returns True if transition succeeded.
        Validates transition legality, respects cooldown, persists state.
        """
        if new_mode == self._current_mode:
            return True

        # Validate transition
        if not self.is_transition_allowed(self._current_mode, new_mode):
            logger.warning(
                f"Rejected invalid transition: {self._current_mode.value} → {new_mode.value}"
            )
            return False

        # Anti-flapping cooldown for automatic recovery upgrades.
        if self._is_recovery_upgrade(self._current_mode, new_mode):
            elapsed = (datetime.utcnow() - self._last_mode_transition).total_seconds()
            if elapsed < self._mode_transition_cooldown_s:
                logger.debug(
                    f"Transition {self._current_mode.value} → {new_mode.value} "
                    f"blocked by cooldown ({elapsed:.0f}s < {self._mode_transition_cooldown_s}s)"
                )
                return False

        if self._is_recovery_upgrade(self._current_mode, new_mode):
            if not self._has_recovery_stabilization(new_mode):
                return False

        # Perform transition
        old_mode = self._current_mode
        self._current_mode = new_mode
        self._last_mode_transition = datetime.utcnow()
        self._last_transition_reason = reason

        logger.info(f"Mode transition: {old_mode.value} → {new_mode.value} ({reason})")

        # Persist to DB (best-effort, don't fail the transition)
        await self._persist_runtime_state(reason)
        await self._log_runtime_event(
            "mode_transition",
            new_mode.value,
            {
                "from": old_mode.value,
                "to": new_mode.value,
                "reason": reason,
            },
        )

        return True

    # -----------------------------------------------------------------------
    # Maintenance Management
    # -----------------------------------------------------------------------

    async def enable_maintenance(
        self,
        reason: str,
        message: str,
        estimated_completion_time: Optional[datetime] = None,
        auto_end_policy: str = "manual",
        created_by: Optional[str] = None,
    ) -> bool:
        """Enable maintenance mode. This is an EXPLICIT operator action."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceWindow
            from sqlalchemy import select

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                maintenance = MaintenanceWindow(
                    enabled=True,
                    reason=reason,
                    message=message,
                    estimated_completion_time=estimated_completion_time,
                    auto_end_policy=auto_end_policy,
                    started_at=datetime.utcnow(),
                    created_by=created_by,
                    updated_by=created_by,
                )
                session.add(maintenance)
                await session.flush()

                # Update in-memory cache
                self._apply_maintenance_window(maintenance)

            # Transition to maintenance — overrides normal/degraded
            await self.transition_mode(
                RuntimeMode.MAINTENANCE, f"Maintenance enabled: {reason}"
            )
            await self._log_runtime_event(
                "maintenance_enabled",
                RuntimeMode.MAINTENANCE.value,
                {
                    "reason": reason,
                    "message": message,
                    "estimated_completion_time": (
                        estimated_completion_time.isoformat()
                        if estimated_completion_time
                        else None
                    ),
                    "auto_end_policy": auto_end_policy,
                    "created_by": created_by,
                    "maintenance_window_id": self._maintenance_window_id,
                },
            )

            logger.info(f"Maintenance mode enabled: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to enable maintenance: {e}", exc_info=True)
            return False

    async def disable_maintenance(self, updated_by: Optional[str] = None) -> bool:
        """Disable maintenance mode and auto-recover to best available mode."""
        try:
            if not self._maintenance_enabled:
                return True

            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceWindow
            from sqlalchemy import update

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                if self._maintenance_window_id:
                    import uuid

                    stmt = (
                        update(MaintenanceWindow)
                        .where(
                            MaintenanceWindow.id
                            == uuid.UUID(self._maintenance_window_id)
                        )
                        .values(
                            enabled=False,
                            ended_at=datetime.utcnow(),
                            updated_by=updated_by,
                        )
                    )
                    await session.execute(stmt)

            # Clear in-memory maintenance state
            self._clear_maintenance_state()

            # Auto-recover: run health checks and pick the best available mode
            await self._run_health_checks()
            next_mode = self._resolve_mode_after_maintenance_exit()
            await self.transition_mode(
                next_mode, "Maintenance disabled — auto-recovery"
            )

            # Trigger notification dispatch for subscribers
            await self._dispatch_maintenance_complete_notifications()
            await self._log_runtime_event(
                "maintenance_disabled",
                next_mode.value,
                {
                    "updated_by": updated_by,
                    "recovered_mode": next_mode.value,
                },
            )

            logger.info("Maintenance mode disabled")
            return True

        except Exception as e:
            logger.error(f"Failed to disable maintenance: {e}", exc_info=True)
            return False

    async def update_maintenance(
        self,
        *,
        message: Optional[str] = None,
        estimated_completion_time: Optional[datetime] = None,
        auto_end_policy: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> bool:
        """Update the active maintenance window through the authoritative control plane."""
        if not self._maintenance_enabled or not self._maintenance_window_id:
            return False

        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceWindow
            from sqlalchemy import update
            import uuid

            update_values: Dict[str, Any] = {}
            if message is not None:
                update_values["message"] = message
            if estimated_completion_time is not None:
                update_values["estimated_completion_time"] = estimated_completion_time
            if auto_end_policy is not None:
                update_values["auto_end_policy"] = auto_end_policy
            if updated_by is not None:
                update_values["updated_by"] = updated_by

            if not update_values:
                return True

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                stmt = (
                    update(MaintenanceWindow)
                    .where(
                        MaintenanceWindow.id == uuid.UUID(self._maintenance_window_id)
                    )
                    .values(**update_values)
                )
                await session.execute(stmt)

            if message is not None:
                self._maintenance_message = message
            if estimated_completion_time is not None:
                self._maintenance_eta = estimated_completion_time
            if auto_end_policy is not None:
                self._maintenance_auto_end_policy = auto_end_policy
            self._maintenance_last_updated_at = datetime.utcnow()

            await self._persist_runtime_state("Maintenance window updated")
            await self._log_runtime_event(
                "maintenance_updated",
                RuntimeMode.MAINTENANCE.value,
                {
                    "message_updated": message is not None,
                    "eta_updated": estimated_completion_time is not None,
                    "auto_end_policy_updated": auto_end_policy is not None,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update maintenance window: {e}", exc_info=True)
            return False

    async def create_maintenance_notification_request(
        self,
        *,
        notification_channel: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Persist a maintenance-complete notification request through the canonical owner."""
        if (
            not self._maintenance_enabled
            or not self._maintenance_window_id
            or not self._maintenance_notifications_supported
        ):
            return False
        if not user_id and not session_id:
            return False

        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceNotificationRequest
            import uuid

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                request = MaintenanceNotificationRequest(
                    maintenance_window_id=uuid.UUID(self._maintenance_window_id),
                    user_id=user_id,
                    session_id=session_id,
                    notification_channel=notification_channel,
                    status="pending",
                    requested_at=datetime.utcnow(),
                )
                session.add(request)

            await self._log_runtime_event(
                "maintenance_notification_requested",
                RuntimeMode.MAINTENANCE.value,
                {
                    "maintenance_window_id": self._maintenance_window_id,
                    "notification_channel": notification_channel,
                    "user_id": user_id,
                    "session_id": session_id,
                },
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to persist maintenance notification request: {e}")
            return False

    async def get_maintenance_notification_subscriptions(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return persisted maintenance notification subscriptions from the canonical owner."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceNotificationRequest
            from sqlalchemy import select

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                result = await session.execute(
                    select(MaintenanceNotificationRequest)
                    .order_by(MaintenanceNotificationRequest.requested_at.desc())
                    .limit(limit)
                )
                requests = result.scalars().all()

            return [
                {
                    "id": str(req.id),
                    "user_id": str(req.user_id)
                    if getattr(req, "user_id", None)
                    else None,
                    "session_id": getattr(req, "session_id", None),
                    "channel": getattr(req, "notification_channel", None),
                    "status": getattr(req, "status", None),
                    "requested_at": (
                        req.requested_at.isoformat()
                        if getattr(req, "requested_at", None)
                        else None
                    ),
                    "dispatched_at": (
                        req.dispatched_at.isoformat()
                        if getattr(req, "dispatched_at", None)
                        else None
                    ),
                }
                for req in requests
            ]
        except Exception as e:
            logger.warning(
                f"Failed to fetch maintenance notification subscriptions: {e}"
            )
            return []

    # -----------------------------------------------------------------------
    # Dependency Health Checks
    # -----------------------------------------------------------------------

    async def check_dependency(self, name: str) -> DependencyHealth:
        """Run a single dependency probe and update tracked state."""
        for probe in self._probes:
            if probe.name == name:
                health = await probe.check()
                self._update_dependency_tracking(health)
                return health
        health = DependencyHealth(
            name=name, status=DependencyStatus.UNKNOWN, reason="No probe registered"
        )
        self._dependency_health[name] = health
        return health

    async def _run_health_checks(self) -> None:
        """Run all dependency probes concurrently."""
        results = await asyncio.gather(
            *(probe.check() for probe in self._probes),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, DependencyHealth):
                self._update_dependency_tracking(result)
            elif isinstance(result, Exception):
                logger.error(f"Probe failed with exception: {result}")

        # Update degraded capabilities based on probe results
        self._update_degraded_capabilities()
        await self._log_runtime_event(
            "dependency_health_evaluated",
            self._current_mode.value,
            {
                "dependency_count": len(self._dependency_health),
                "healthy_dependencies": [
                    name
                    for name, health in self._dependency_health.items()
                    if health.status == DependencyStatus.HEALTHY
                ],
                "unhealthy_dependencies": [
                    name
                    for name, health in self._dependency_health.items()
                    if health.status == DependencyStatus.UNHEALTHY
                ],
            },
        )

    def _update_dependency_tracking(self, health: DependencyHealth) -> None:
        """Update consecutive success/failure counters (anti-flapping)."""
        existing = self._dependency_health.get(health.name)

        if health.status == DependencyStatus.HEALTHY:
            health.consecutive_successes = (
                (existing.consecutive_successes + 1) if existing else 1
            )
            health.consecutive_failures = 0
        else:
            health.consecutive_failures = (
                (existing.consecutive_failures + 1) if existing else 1
            )
            health.consecutive_successes = 0

        self._dependency_health[health.name] = health

    def _update_degraded_capabilities(self) -> None:
        """Detect what's available for degraded mode — dynamic, not static."""
        self._degraded_capabilities = self._derive_degraded_capabilities()

    def _derive_degraded_capabilities(self) -> DegradedCapabilities:
        """
        Derive degraded-mode boundaries from dependency health.

        Boundary rules:
        - memory requires both the memory subsystem and DB-backed context access
        - tools/plugins require DB-backed runtime infrastructure
        - streaming requires external provider availability
        - local model is disabled until a dedicated probe exists
        """
        db = self._dependency_health.get("database")
        memory = self._dependency_health.get("memory_subsystem")
        provider = self._dependency_health.get("provider_router")
        local_model = self._dependency_health.get("local_model")

        db_ok = db and db.status == DependencyStatus.HEALTHY
        memory_ok = memory and memory.status == DependencyStatus.HEALTHY
        provider_ok = provider and provider.status == DependencyStatus.HEALTHY
        local_model_ok = local_model and local_model.status == DependencyStatus.HEALTHY

        capabilities = DegradedCapabilities(
            memory_available=bool(memory_ok and db_ok),
            tools_available=bool(db_ok),
            plugins_available=bool(db_ok),
            external_providers_available=bool(provider_ok),
            streaming_supported=bool(provider_ok),
            local_model_available=bool(local_model_ok),
        )

        # Build human-readable status description (for mode metadata, not answer text)
        caps = []
        if capabilities.memory_available:
            caps.append("memory")
        if capabilities.tools_available:
            caps.append("tools")
        if capabilities.external_providers_available:
            caps.append("external providers")
        if caps:
            capabilities.description = (
                f"Degraded mode active ({', '.join(caps)} available)"
            )
        else:
            capabilities.description = "Degraded mode active (minimal capabilities)"
        return capabilities

    # -----------------------------------------------------------------------
    # Mode Decision Logic
    # -----------------------------------------------------------------------

    def _is_normal_ready(self) -> bool:
        """All critical dependencies must be healthy."""
        if not self._startup_health_checks_completed:
            return False
        for dep_name in self.NORMAL_MODE_DEPS:
            health = self._dependency_health.get(dep_name)
            if not health or health.status != DependencyStatus.HEALTHY:
                return False
        return True

    def _is_degraded_ready(self) -> bool:
        """Allow degraded service when persistence or any chat execution path is available."""
        db = self._dependency_health.get("database")
        orchestrator = self._dependency_health.get("chat_orchestrator")
        provider = self._dependency_health.get("provider_router")
        local_model = self._dependency_health.get("local_model")
        return bool(
            (db is not None and db.status == DependencyStatus.HEALTHY)
            or (
                orchestrator is not None
                and orchestrator.status == DependencyStatus.HEALTHY
            )
            or (
                provider is not None
                and provider.status == DependencyStatus.HEALTHY
            )
            or (
                local_model is not None
                and local_model.status == DependencyStatus.HEALTHY
            )
        )

    def _has_chat_execution_path(self) -> bool:
        """Return True when a live/degraded chat path can still attempt generation."""
        for dep_name in ("provider_router", "chat_orchestrator", "local_model"):
            health = self._dependency_health.get(dep_name)
            if health is not None and health.status == DependencyStatus.HEALTHY:
                return True
        return False

    async def _has_live_provider_path(self) -> bool:
        """Query the canonical provider registry before blocking chat in emergency mode."""
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            registry = get_provider_registry_service()

            for provider_name in registry.get_all_provider_names():
                if provider_name in {"fallback", "copilotkit", "custom_copilotkit"}:
                    continue
                status = registry.get_provider_status(provider_name)
                if status is None or not status.is_available:
                    continue
                if provider_name == "builtin_vllm":
                    endpoint = registry.get_provider_endpoint("builtin_vllm")
                    if endpoint is not None and endpoint.enabled:
                        return True
                    continue
                if provider_name == "builtin_transformers":
                    endpoint = registry.get_provider_endpoint("builtin_transformers")
                    if endpoint is not None and endpoint.enabled:
                        return True
                    continue
                if not status.has_api_key:
                    continue
                models = registry.get_registered_models(provider_name)
                if status.has_api_key and models:
                    return True
        except Exception as exc:
            logger.debug("Live provider path probe failed: %s", exc)
        return False

    def _compute_optimal_mode(self) -> RuntimeMode:
        """
        Determine the optimal mode from current conditions.
        Called ONLY when NOT in maintenance. Maintenance is operator-controlled.
        """
        if self._is_normal_ready():
            return RuntimeMode.NORMAL
        if self._is_degraded_ready():
            return RuntimeMode.DEGRADED
        return RuntimeMode.EMERGENCY_FALLBACK

    def _resolve_mode_after_maintenance_exit(self) -> RuntimeMode:
        """Resolve post-maintenance recovery through the central precedence selector."""
        return self._select_mode_by_precedence(
            {
                RuntimeMode.MAINTENANCE: False,
                RuntimeMode.NORMAL: self._is_normal_ready(),
                RuntimeMode.DEGRADED: self._is_degraded_ready(),
                RuntimeMode.EMERGENCY_FALLBACK: True,
            }
        )

    def resolve_mode_from_current_conditions(self) -> RuntimeMode:
        """
        Resolve the single authoritative mode from current state inputs.
        This is the central runtime state-machine evaluator.
        """
        candidates = {
            RuntimeMode.MAINTENANCE: self.is_planned_maintenance_active(),
            RuntimeMode.NORMAL: self._is_normal_ready(),
            RuntimeMode.DEGRADED: self._is_degraded_ready(),
            RuntimeMode.EMERGENCY_FALLBACK: True,
        }
        return self._select_mode_by_precedence(candidates)

    def _select_mode_by_precedence(
        self,
        candidates: Dict[RuntimeMode, bool],
    ) -> RuntimeMode:
        """Select the first valid mode according to the fixed precedence order."""
        for mode in _MODE_PRECEDENCE:
            if candidates.get(mode, False):
                return mode
        return RuntimeMode.EMERGENCY_FALLBACK

    def is_transition_allowed(
        self,
        current_mode: RuntimeMode,
        new_mode: RuntimeMode,
    ) -> bool:
        """Central legality check for state transitions."""
        if new_mode == current_mode:
            return True
        return new_mode in _VALID_TRANSITIONS.get(current_mode, set())

    def _is_recovery_upgrade(
        self,
        current_mode: RuntimeMode,
        new_mode: RuntimeMode,
    ) -> bool:
        """Return True only for automatic health recovery to a stronger runtime mode."""
        if RuntimeMode.MAINTENANCE in {current_mode, new_mode}:
            return False
        return _MODE_RANK.get(new_mode, 0) > _MODE_RANK.get(current_mode, 0)

    def _required_stable_dependencies_for_mode(
        self,
        mode: RuntimeMode,
    ) -> tuple[str, ...]:
        """Return the dependency set that must stabilize before recovering into a mode."""
        if mode == RuntimeMode.NORMAL:
            return tuple(self.NORMAL_MODE_DEPS)
        if mode == RuntimeMode.DEGRADED:
            return ("chat_orchestrator",)
        return ()

    def _has_recovery_stabilization(self, new_mode: RuntimeMode) -> bool:
        """Require consecutive healthy checks before recovery upgrades to avoid flapping."""
        for dep_name in self._required_stable_dependencies_for_mode(new_mode):
            health = self._dependency_health.get(dep_name)
            if (
                not health
                or health.status != DependencyStatus.HEALTHY
                or health.consecutive_successes < self._stabilization_threshold
            ):
                logger.debug(
                    f"{new_mode.value} upgrade blocked: {dep_name} has only "
                    f"{health.consecutive_successes if health else 0} consecutive successes "
                    f"(need {self._stabilization_threshold})"
                )
                return False
        return True

    async def reconcile_mode(self, reason: str) -> bool:
        """
        Reconcile the current mode with the central state-machine decision.
        Returns True when the current mode already matches or transitions cleanly.
        """
        target_mode = self.resolve_mode_from_current_conditions()
        if target_mode == self._current_mode:
            return True
        return await self.transition_mode(target_mode, reason)

    # -----------------------------------------------------------------------
    # Response Builders
    # -----------------------------------------------------------------------

    def _build_maintenance_response(self) -> MaintenanceResponse:
        notification_request_allowed = bool(
            self._maintenance_enabled
            and self._maintenance_window_id
            and self._maintenance_notifications_supported
        )
        return MaintenanceResponse(
            message=self._maintenance_message or MaintenanceResponse.message,
            estimated_completion_time=(
                self._maintenance_eta.isoformat() if self._maintenance_eta else None
            ),
            notification_supported=self._maintenance_notifications_supported,
            notification_request_allowed=notification_request_allowed,
            reason=self._maintenance_reason,
            started_at=(
                self._maintenance_started_at.isoformat()
                if self._maintenance_started_at
                else None
            ),
        )

    def _build_emergency_fallback_response(self) -> EmergencyFallbackResponse:
        """Build the single structured emergency fallback response."""
        return EmergencyFallbackResponse()

    def _build_degraded_response(self, **context) -> DegradedResponse:
        caps = self._degraded_capabilities
        return DegradedResponse(
            message=caps.description,
            capabilities=caps,
            is_minimal=caps.is_minimal,
        )

    # -----------------------------------------------------------------------
    # Background Loops
    # -----------------------------------------------------------------------

    async def _health_check_loop(self) -> None:
        """Periodic health checks and automatic mode transitions."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._run_health_checks()

                # Do NOT auto-transition if in maintenance — that's operator-controlled
                if self._current_mode == RuntimeMode.MAINTENANCE:
                    continue

                await self.reconcile_mode("Automatic health-based transition")

                # Persist health snapshots (best-effort)
                await self._persist_dependency_health()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")

    async def _maintenance_monitor_loop(self) -> None:
        """Monitor maintenance state for auto-end policies."""
        while True:
            try:
                await asyncio.sleep(self._maintenance_recheck_interval)

                if not self._maintenance_enabled:
                    continue

                should_end = await self._should_auto_end_maintenance()
                if should_end:
                    logger.info("Auto-ending maintenance based on policy")
                    await self.disable_maintenance(updated_by="auto_policy")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in maintenance monitor loop: {e}")

    async def _should_auto_end_maintenance(self) -> bool:
        """Check if maintenance should automatically end based on policy."""
        if self._maintenance_auto_end_policy == "after_healthy_check":
            await self._run_health_checks()
            return self._is_normal_ready()
        elif self._maintenance_auto_end_policy == "at_time" and self._maintenance_eta:
            return datetime.utcnow() >= self._maintenance_eta
        return False  # "manual" policy — never auto-end

    # -----------------------------------------------------------------------
    # Persistence (best-effort — failures don't break the control plane)
    # -----------------------------------------------------------------------

    async def _load_runtime_state(self) -> None:
        """Load persisted runtime state from DB."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import (
                SystemRuntimeState,
                MaintenanceWindow,
            )
            from sqlalchemy import select

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                # Load latest runtime state
                result = await session.execute(
                    select(SystemRuntimeState)
                    .order_by(SystemRuntimeState.updated_at.desc())
                    .limit(1)
                )
                state = result.scalar_one_or_none()
                if state:
                    try:
                        self._current_mode = RuntimeMode(state.current_mode)
                    except ValueError:
                        self._current_mode = RuntimeMode.EMERGENCY_FALLBACK
                    logger.info(
                        f"Loaded persisted runtime state: {self._current_mode.value}"
                    )

                # Load active maintenance window
                result = await session.execute(
                    select(MaintenanceWindow)
                    .where(MaintenanceWindow.enabled == True)
                    .order_by(MaintenanceWindow.started_at.desc())
                    .limit(1)
                )
                maint = result.scalar_one_or_none()
                if maint:
                    self._apply_maintenance_window(maint)
                    self._current_mode = RuntimeMode.MAINTENANCE
                    logger.info(f"Active maintenance window loaded: {maint.reason}")

        except Exception as e:
            logger.warning(
                f"Could not load runtime state from DB (safe to continue): {e}"
            )

    def _apply_maintenance_window(self, maintenance: Any) -> None:
        """Mirror the canonical maintenance_windows record into runtime memory."""
        self._maintenance_enabled = bool(getattr(maintenance, "enabled", False))
        self._maintenance_reason = getattr(maintenance, "reason", None)
        self._maintenance_message = getattr(maintenance, "message", None)
        self._maintenance_started_at = getattr(maintenance, "started_at", None)
        self._maintenance_eta = getattr(maintenance, "estimated_completion_time", None)
        self._maintenance_window_id = (
            str(maintenance.id) if getattr(maintenance, "id", None) else None
        )
        self._maintenance_notifications_supported = bool(
            getattr(maintenance, "notifications_supported", True)
        )
        self._maintenance_last_updated_at = getattr(maintenance, "updated_at", None)
        created_by = getattr(maintenance, "created_by", None)
        self._maintenance_created_by = str(created_by) if created_by else None
        self._maintenance_auto_end_policy = (
            getattr(maintenance, "auto_end_policy", None) or "manual"
        )

    def _clear_maintenance_state(self) -> None:
        """Clear the in-memory mirror of canonical maintenance state."""
        self._maintenance_enabled = False
        self._maintenance_reason = None
        self._maintenance_message = None
        self._maintenance_started_at = None
        self._maintenance_eta = None
        self._maintenance_window_id = None
        self._maintenance_notifications_supported = True
        self._maintenance_last_updated_at = None
        self._maintenance_created_by = None
        self._maintenance_auto_end_policy = "manual"

    async def _persist_runtime_state(self, reason: str) -> None:
        """Persist current state to DB."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import SystemRuntimeState

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                state = SystemRuntimeState(
                    current_mode=self._current_mode.value,
                    normal_ready=self._is_normal_ready(),
                    degraded_ready=self._is_degraded_ready(),
                    maintenance_enabled=self._maintenance_enabled,
                    maintenance_reason=self._maintenance_reason,
                    estimated_completion_time=self._maintenance_eta,
                    last_transition_at=self._last_mode_transition,
                    last_transition_reason=reason,
                )
                session.add(state)

        except Exception as e:
            logger.warning(f"Failed to persist runtime state: {e}")

    async def _persist_dependency_health(self) -> None:
        """Persist dependency health snapshots to DB."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import RuntimeDependencyHealth

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                for health in self._dependency_health.values():
                    record = RuntimeDependencyHealth(
                        dependency_name=health.name,
                        status=health.status.value,
                        reason=health.reason,
                        consecutive_successes=health.consecutive_successes,
                        consecutive_failures=health.consecutive_failures,
                        last_failure_at=(
                            health.checked_at
                            if health.status == DependencyStatus.UNHEALTHY
                            else None
                        ),
                    )
                    session.add(record)

        except Exception as e:
            logger.warning(f"Failed to persist dependency health: {e}")

    async def _log_runtime_event(
        self, event_type: str, mode: str, details: Any
    ) -> None:
        """Log auditable runtime event to DB."""
        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import ChatRuntimeEvent

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                event = ChatRuntimeEvent(
                    event_type=event_type,
                    mode=mode,
                    details_json=details
                    if isinstance(details, dict)
                    else {"message": str(details)},
                )
                session.add(event)

        except Exception as e:
            logger.warning(f"Failed to log runtime event: {e}")

    async def _dispatch_maintenance_complete_notifications(self) -> None:
        """Dispatch notifications to users who requested maintenance-complete alerts."""
        if not self._maintenance_window_id:
            return

        try:
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            from ai_karen_engine.database.models import MaintenanceNotificationRequest
            from sqlalchemy import select, update
            import uuid

            db = MultiTenantPostgresClient()
            async with db.get_async_session() as session:
                # Find all pending notification requests for this window
                result = await session.execute(
                    select(MaintenanceNotificationRequest).where(
                        MaintenanceNotificationRequest.maintenance_window_id
                        == uuid.UUID(self._maintenance_window_id),
                        MaintenanceNotificationRequest.status.in_(
                            ["active", "pending"]
                        ),
                    )
                )
                requests = result.scalars().all()

                dispatched_count = 0
                for req in requests:
                    if getattr(req, "cancelled_at", None) is not None:
                        continue
                    if getattr(req, "status", None) == "completed":
                        continue

                    # TODO: dispatch via actual notification channel (in-app, websocket)
                    # For now, mark as dispatched in DB
                    req.status = "completed"
                    req.dispatched_at = datetime.utcnow()
                    dispatched_count += 1

                if dispatched_count:
                    await self._log_runtime_event(
                        "maintenance_notification_dispatched",
                        RuntimeMode.MAINTENANCE.value,
                        {
                            "maintenance_window_id": self._maintenance_window_id,
                            "dispatch_count": dispatched_count,
                        },
                    )

                logger.info(
                    f"Dispatched {dispatched_count} maintenance-complete notifications"
                )

        except Exception as e:
            logger.warning(f"Failed to dispatch maintenance notifications: {e}")

    # -----------------------------------------------------------------------
    # Enhanced Hardening Features
    # -----------------------------------------------------------------------

    async def initialize_runtime_authority(self) -> bool:
        """Initialize runtime authority with enhanced hardening features."""
        try:
            logger.info("Initializing Runtime Authority with enhanced hardening")

            # Initialize runtime state persistence
            await self._initialize_runtime_state_persistence()

            # Initialize emergency protocols
            await self._initialize_emergency_protocols()

            # Initialize circuit breaker integration
            await self._initialize_circuit_breakers()

            # Initialize response contracts
            await self._initialize_response_contracts()

            # Initialize performance monitoring
            await self._initialize_performance_monitoring()

            self._authority_initialized = True
            self._last_authority_check = datetime.utcnow()

            # Calculate initial authority health score
            self._authority_health_score = (
                await self._calculate_authority_health_score()
            )

            logger.info(
                f"Runtime Authority initialized with health score: {self._authority_health_score:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize runtime authority: {e}")
            self._emergency_protocol_triggers.append("authority_initialization_failed")
            return False

    async def _initialize_runtime_state_persistence(self) -> None:
        """Initialize runtime state persistence with recovery mechanisms."""
        try:
            # Load persisted state from storage
            persisted_state = await self._load_persisted_runtime_state()

            if persisted_state:
                # Restore runtime state
                self._restore_runtime_state(persisted_state)
                logger.info("Runtime state restored from persistence")
            else:
                logger.info("No persisted runtime state found, using defaults")

        except Exception as e:
            logger.warning(f"Failed to initialize runtime state persistence: {e}")

    async def _initialize_emergency_protocols(self) -> None:
        """Initialize emergency protocol system."""
        try:
            # Define emergency protocol triggers
            self._emergency_protocol_triggers = []

            # Define emergency responses
            self._emergency_responses = {
                "database_unavailable": self._emergency_database_response,
                "redis_unavailable": self._emergency_redis_response,
                "orchestrator_unavailable": self._emergency_orchestrator_response,
                "provider_router_unavailable": self._emergency_provider_response,
                "memory_unavailable": self._emergency_memory_response,
            }

            logger.info("Emergency protocols initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize emergency protocols: {e}")

    async def _initialize_circuit_breakers(self) -> None:
        """Initialize circuit breaker integration."""
        try:
            self._circuit_breaker_state = {
                "database": {"state": "closed", "failures": 0, "last_failure": None},
                "redis": {"state": "closed", "failures": 0, "last_failure": None},
                "orchestrator": {
                    "state": "closed",
                    "failures": 0,
                    "last_failure": None,
                },
                "provider_router": {
                    "state": "closed",
                    "failures": 0,
                    "last_failure": None,
                },
                "memory": {"state": "closed", "failures": 0, "last_failure": None},
            }

            logger.info("Circuit breakers initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize circuit breakers: {e}")

    async def _initialize_response_contracts(self) -> None:
        """Initialize response contract system."""
        try:
            self._response_contracts = {
                "normal_execution": {
                    "guaranteed": True,
                    "timeout": 30,
                    "fallback": "degraded",
                    "dependencies": [
                        "database",
                        "redis",
                        "provider_router",
                        "memory_subsystem",
                    ],
                },
                "degraded_execution": {
                    "guaranteed": True,
                    "timeout": 60,
                    "fallback": "emergency",
                    "dependencies": ["provider_router"],
                },
                "emergency_execution": {
                    "guaranteed": True,
                    "timeout": 10,
                    "fallback": None,
                    "dependencies": [],
                },
                "maintenance_execution": {
                    "guaranteed": True,
                    "timeout": 5,
                    "fallback": None,
                    "dependencies": [],
                },
            }

            logger.info("Response contracts initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize response contracts: {e}")

    async def _initialize_performance_monitoring(self) -> None:
        """Initialize performance monitoring."""
        try:
            self._performance_metrics = {
                "mode_changes": 0,
                "health_check_duration": [],
                "response_time": [],
                "error_rate": 0.0,
                "last_healthy_mode": None,
                "circuit_breaker_trips": 0,
                "emergency_protocol_activations": 0,
                "response_contract_violations": 0,
            }

            logger.info("Performance monitoring initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize performance monitoring: {e}")

    async def _calculate_authority_health_score(self) -> float:
        """Calculate overall authority health score (0.0 to 1.0)."""
        try:
            factors = []

            # Dependency health score
            healthy_deps = sum(
                1
                for health in self._dependency_health.values()
                if health.status == DependencyStatus.HEALTHY
            )
            total_deps = len(self._dependency_health)
            if total_deps > 0:
                factors.append(healthy_deps / total_deps)

            # Mode appropriateness score
            if self._current_mode == RuntimeMode.NORMAL:
                factors.append(1.0)
            elif self._current_mode == RuntimeMode.DEGRADED:
                factors.append(0.7)
            elif self._current_mode == RuntimeMode.MAINTENANCE:
                factors.append(0.5)
            else:  # EMERGENCY_FALLBACK
                factors.append(0.3)

            # Circuit breaker health score
            closed_breakers = sum(
                1
                for state in self._circuit_breaker_state.values()
                if state["state"] == "closed"
            )
            total_breakers = len(self._circuit_breaker_state)
            if total_breakers > 0:
                factors.append(closed_breakers / total_breakers)

            # Emergency protocol health score
            if not self._emergency_protocol_triggers:
                factors.append(1.0)
            else:
                factors.append(
                    max(0.0, 1.0 - len(self._emergency_protocol_triggers) * 0.1)
                )

            # Return weighted average
            if factors:
                return sum(factors) / len(factors)
            return 0.0

        except Exception as e:
            logger.error(f"Failed to calculate authority health score: {e}")
            return 0.0

    def _update_circuit_breaker_state(self, service_name: str, failure: bool) -> None:
        """Update circuit breaker state for a service."""
        try:
            if service_name not in self._circuit_breaker_state:
                return

            state = self._circuit_breaker_state[service_name]

            if failure:
                state["failures"] += 1
                state["last_failure"] = datetime.utcnow()

                # Check if circuit breaker should trip
                if state["failures"] >= 5:  # Threshold
                    state["state"] = "open"
                    self._performance_metrics["circuit_breaker_trips"] += 1
                    logger.warning(f"Circuit breaker opened for {service_name}")

                    # Add to emergency protocol triggers
                    if service_name not in self._emergency_protocol_triggers:
                        self._emergency_protocol_triggers.append(
                            f"{service_name}_circuit_breaker"
                        )
            else:
                state["failures"] = 0
                state["last_failure"] = None

                # Check if circuit breaker should close
                if state["state"] == "open" and state["failures"] == 0:
                    state["state"] = "closed"
                    logger.info(f"Circuit breaker closed for {service_name}")

        except Exception as e:
            logger.error(f"Failed to update circuit breaker state: {e}")

    async def _execute_emergency_protocol(self, trigger: str) -> None:
        """Execute emergency protocol for a given trigger."""
        try:
            logger.warning(f"Executing emergency protocol for trigger: {trigger}")

            if trigger in self._emergency_responses:
                response = await self._emergency_responses[trigger]()

                # Update performance metrics
                self._performance_metrics["emergency_protocol_activations"] += 1

                # Log the emergency activation
                await self._log_runtime_event(
                    "emergency_protocol_activated",
                    self._current_mode.value,
                    {"trigger": trigger, "response": str(response)},
                )

                return response
            else:
                logger.warning(f"No emergency response defined for trigger: {trigger}")

        except Exception as e:
            logger.error(f"Failed to execute emergency protocol: {e}")

    async def _emergency_database_response(self) -> RuntimeResponse:
        """Emergency response when database is unavailable."""
        self._update_circuit_breaker_state("database", True)

        if self._current_mode == RuntimeMode.NORMAL:
            # Downgrade to degraded mode
            await self.transition_mode(RuntimeMode.DEGRADED, "database_emergency")

        return EmergencyFallbackResponse(
            message="Database temporarily unavailable. Using limited functionality.",
            retry_after_seconds=30,
        )

    async def _emergency_redis_response(self) -> RuntimeResponse:
        """Emergency response when Redis is unavailable."""
        self._update_circuit_breaker_state("redis", True)

        if self._current_mode == RuntimeMode.NORMAL:
            # Downgrade to degraded mode
            await self.transition_mode(RuntimeMode.DEGRADED, "redis_emergency")

        return DegradedResponse(
            message="Cache service temporarily unavailable. Using degraded mode.",
            capabilities=DegradedCapabilities(
                memory_available=False,
                tools_available=False,
                plugins_available=False,
                external_providers_available=False,
                streaming_supported=False,
                local_model_available=False,
                description="Limited text-only assistant without caching",
            ),
            is_minimal=True,
        )

    async def _emergency_orchestrator_response(self) -> RuntimeResponse:
        """Emergency response when orchestrator is unavailable."""
        self._update_circuit_breaker_state("orchestrator", True)

        return EmergencyFallbackResponse(
            message="Chat service temporarily unavailable. Please try again shortly.",
            retry_after_seconds=60,
        )

    async def _emergency_provider_response(self) -> RuntimeResponse:
        """Emergency response when provider router is unavailable."""
        self._update_circuit_breaker_state("provider_router", True)

        return EmergencyFallbackResponse(
            message="AI service temporarily unavailable. Using limited responses.",
            retry_after_seconds=30,
        )

    async def _emergency_memory_response(self) -> RuntimeResponse:
        """Emergency response when memory service is unavailable."""
        self._update_circuit_breaker_state("memory", True)

        return DegradedResponse(
            message="Memory service temporarily unavailable. Conversation history limited.",
            capabilities=DegradedCapabilities(
                memory_available=False,
                tools_available=True,
                plugins_available=True,
                external_providers_available=True,
                streaming_supported=True,
                local_model_available=True,
                description="Assistant with limited conversation memory",
            ),
            is_minimal=False,
        )

    async def _load_persisted_runtime_state(self) -> Optional[Dict[str, Any]]:
        """Load persisted runtime state from storage."""
        try:
            # This would typically load from a database or file
            # For now, return None to indicate no persistence
            return None

        except Exception as e:
            logger.error(f"Failed to load persisted runtime state: {e}")
            return None

    def _restore_runtime_state(self, state: Dict[str, Any]) -> None:
        """Restore runtime state from persisted data."""
        try:
            # Restore mode
            if "mode" in state:
                self._current_mode = RuntimeMode(state["mode"])

            # Restore dependency health
            if "dependency_health" in state:
                self._dependency_health = {
                    name: DependencyHealth(**health)
                    for name, health in state["dependency_health"].items()
                }

            # Restore performance metrics
            if "performance_metrics" in state:
                self._performance_metrics.update(state["performance_metrics"])

            logger.info("Runtime state restored successfully")

        except Exception as e:
            logger.error(f"Failed to restore runtime state: {e}")

    async def get_runtime_authority_status(self) -> Dict[str, Any]:
        """Get comprehensive runtime authority status."""
        try:
            # Calculate current health score
            health_score = await self._calculate_authority_health_score()

            # Get circuit breaker states
            circuit_breaker_states = {
                name: state["state"]
                for name, state in self._circuit_breaker_state.items()
            }

            # Get emergency protocol status
            emergency_status = {
                "active": len(self._emergency_protocol_triggers) > 0,
                "triggers": self._emergency_protocol_triggers,
            }

            # Get performance metrics
            performance_metrics = dict(self._performance_metrics)

            # Get response contract status
            response_contracts = {
                name: {
                    "guaranteed": contract["guaranteed"],
                    "dependencies_met": all(
                        dep in self._dependency_health
                        and self._dependency_health[dep].status
                        == DependencyStatus.HEALTHY
                        for dep in contract["dependencies"]
                    ),
                }
                for name, contract in self._response_contracts.items()
            }

            return {
                "authority_initialized": self._authority_initialized,
                "current_mode": self._current_mode.value,
                "health_score": health_score,
                "circuit_breakers": circuit_breaker_states,
                "emergency_protocols": emergency_status,
                "performance_metrics": performance_metrics,
                "response_contracts": response_contracts,
                "last_authority_check": self._last_authority_check.isoformat()
                if self._last_authority_check
                else None,
                "dependency_health": {
                    name: {
                        "status": health.status.value,
                        "consecutive_successes": health.consecutive_successes,
                        "consecutive_failures": health.consecutive_failures,
                    }
                    for name, health in self._dependency_health.items()
                },
            }

        except Exception as e:
            logger.error(f"Failed to get runtime authority status: {e}")
            return {
                "authority_initialized": False,
                "error": str(e),
            }

    async def enforce_response_contract(self, contract_name: str) -> bool:
        """Enforce response contract for a given execution path."""
        try:
            if contract_name not in self._response_contracts:
                logger.warning(f"Unknown response contract: {contract_name}")
                return False

            contract = self._response_contracts[contract_name]

            # Check if dependencies are healthy
            dependencies_met = all(
                dep in self._dependency_health
                and self._dependency_health[dep].status == DependencyStatus.HEALTHY
                for dep in contract["dependencies"]
            )

            if not dependencies_met and contract["guaranteed"]:
                # Log contract violation
                self._performance_metrics["response_contract_violations"] += 1

                logger.warning(
                    f"Response contract violation: {contract_name} - dependencies not met"
                )

                # Attempt to recover
                await self.reconcile_mode("response_contract_violation")

                return False

            return True

        except Exception as e:
            logger.error(f"Failed to enforce response contract: {e}")
            return False

    async def health_check(self) -> bool:
        """Enhanced health check for runtime authority."""
        try:
            if not self._authority_initialized:
                return False

            # Check if we need to reinitialize
            if (
                self._last_authority_check
                and (datetime.utcnow() - self._last_authority_check).total_seconds()
                > 300
            ):  # 5 minutes
                await self.initialize_runtime_authority()

            # Check emergency protocols
            if self._emergency_protocol_triggers:
                logger.warning(
                    f"Emergency protocols active: {self._emergency_protocol_triggers}"
                )

            # Check circuit breakers
            open_breakers = [
                name
                for name, state in self._circuit_breaker_state.items()
                if state["state"] == "open"
            ]

            if open_breakers:
                logger.warning(f"Open circuit breakers: {open_breakers}")

            return True

        except Exception as e:
            logger.error(f"Runtime authority health check failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Global Singleton
# ---------------------------------------------------------------------------

_runtime_control_plane: Optional[ChatRuntimeControlPlane] = None


def serialize_runtime_response(response: RuntimeResponse) -> Optional[Dict[str, Any]]:
    """Convert a structured runtime response into the authoritative payload shape."""
    if response is None:
        return None

    if isinstance(response, MaintenanceResponse):
        return {
            "mode": response.mode,
            "message": response.message,
            "estimated_completion_time": response.estimated_completion_time,
            "notification_supported": response.notification_supported,
            "notification_request_allowed": response.notification_request_allowed,
            "retry_after_seconds": response.retry_after_seconds,
            "system_status_code": response.system_status_code,
            "reason": response.reason,
            "started_at": response.started_at,
        }

    if isinstance(response, EmergencyFallbackResponse):
        return {
            "mode": response.mode,
            "message": response.message,
            "retry_after_seconds": response.retry_after_seconds,
            "system_status_code": response.system_status_code,
            "support_hint": response.support_hint,
        }

    if isinstance(response, DegradedResponse):
        return {
            "mode": response.mode,
            "message": response.message,
            "capabilities": (
                asdict(response.capabilities) if response.capabilities else None
            ),
            "is_minimal": response.is_minimal,
            "retry_after_seconds": response.retry_after_seconds,
            "system_status_code": response.system_status_code,
            "support_hint": response.support_hint,
        }

    raise TypeError(f"Unsupported runtime response type: {type(response)!r}")


def runtime_response_http_status(response: RuntimeResponse) -> Optional[int]:
    """Return the canonical HTTP status for a runtime response."""
    if response is None:
        return None
    if isinstance(response, DegradedResponse):
        return 200
    return response.system_status_code


async def get_chat_runtime_control_plane() -> ChatRuntimeControlPlane:
    """Get the global control plane instance (lazy-initialized)."""
    global _runtime_control_plane
    if _runtime_control_plane is None:
        _runtime_control_plane = ChatRuntimeControlPlane()
        await _runtime_control_plane.initialize()
    return _runtime_control_plane


__all__ = [
    "ChatRuntimeControlPlane",
    "RuntimeMode",
    "DependencyStatus",
    "DependencyHealth",
    "DegradedCapabilities",
    "MaintenanceResponse",
    "EmergencyFallbackResponse",
    "DegradedResponse",
    "RuntimeSnapshot",
    "RuntimeResponse",
    "serialize_runtime_response",
    "runtime_response_http_status",
    "get_chat_runtime_control_plane",
]
