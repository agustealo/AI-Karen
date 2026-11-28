"""
Provider Health Monitor Service

Canonical provider health authority. Owns observed health state only.
Does not choose alternatives or make routing decisions.

Ownership:
    ProviderRegistryService   -> who exists
    ProviderHealthMonitor     -> observed health state
    RuntimeResilience         -> failure/retry/fallback decisions
    ProviderRouter            -> consumes health during selection
    Observability             -> records health transitions and failures
"""

from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from ai_karen_engine.core.logging import get_logger

if TYPE_CHECKING:
    from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass
class ProviderHealthInfo:
    """Canonical provider health state contract.

    Avoid free-form error strings as the primary machine contract.
    """

    provider_id: str
    configured: bool = False
    available: bool = False
    health_status: HealthStatus = HealthStatus.UNKNOWN

    last_checked_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    consecutive_failures: int = 0
    success_rate: float = 1.0
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None

    error_code: Optional[str] = None
    error_type: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)


# This is worker-local evidence, not a grant, reservation, or model registry.
_native_observation: ContextVar[NativeExecutionObservation | None] = ContextVar(
    "native_execution_observation", default=None,
)


@dataclass(slots=True)
class NativeExecutionObservation:
    """One governed native computation, published only by the owning coroutine."""

    operation: str
    endpoint: ProviderEndpoint | None = None
    started: float | None = None
    compute_calls: int = 0
    compute_returned: bool = False
    finished: bool = False
    soft_attempt: bool = False
    sealed_at: float | None = None
    registration: object | None = field(default=None, init=False, repr=False)

    @contextmanager
    def bind(self) -> Iterator[None]:
        # Bind occurs at the owned worker's handoff, before any model lock/I/O.
        if self.endpoint is not None and self.started is None:
            try:
                self.registration = get_health_monitor().capture_endpoint_registration(self.endpoint)
            except Exception:
                self.registration = None
        token = _native_observation.set(self)
        try:
            yield
        finally:
            _native_observation.reset(token)

    def finish(self, outcome: str) -> bool:
        """Report a bounded outcome after the admitted worker has retired.

        Model-specific failures are not evidence that every model on a shared
        native provider is unhealthy. Embeddings do not certify chat health.
        """
        if self.finished or self.started is None:
            return False
        self.finished = True
        if self.compute_calls != 1 or (outcome == "success" and not self.compute_returned):
            outcome = "unverified_result"
        elapsed = (
            self.sealed_at if self.sealed_at is not None else time.perf_counter()
        ) - self.started
        try:
            return get_health_monitor().record_native_execution(
                self.endpoint, operation=self.operation,
                outcome=outcome, response_time=elapsed,
                registration=self.registration,
            )
        except Exception:
            return False

    def finish_exception(self, exc: BaseException) -> None:
        import asyncio
        from ai_karen_engine.core.model_runtime.governed_model_admission import (
            ModelAdmissionDeadlineExceeded,
        )
        from ai_karen_engine.core.model_runtime.provider_contracts import (
            NativeRetirementUnverified,
        )

        if isinstance(exc, NativeRetirementUnverified):
            outcome = "retirement_unverified"
        elif isinstance(exc, asyncio.CancelledError):
            outcome = "cancelled"
        elif isinstance(exc, ModelAdmissionDeadlineExceeded):
            outcome = "deadline_exceeded"
        elif self.compute_returned:
            outcome = "unverified_result"
        else:
            outcome = "execution_failed"
        self.finish(outcome)


@contextmanager
def observe_native_compute(operation: str) -> Iterator[None]:
    """Mark the actual library invocation inside the already-owned worker."""
    observation = _native_observation.get()
    if observation is None:
        yield
        return
    if observation.soft_attempt:
        # The batch verifier reuses the canonical pipeline generation owner.
        # Relabel only within the admitted exploration attempt, never globally.
        role = {
            "generation": "soft_verifier",
            "soft_reference": "soft_reference",
            "soft_guided": "soft_guided",
        }.get(operation)
        if role is None:
            yield
            return
        if observation.compute_calls == 0:
            observation.operation = role
    elif observation.operation != operation:
        yield
        return
    observation.compute_calls += 1
    if observation.started is None:
        observation.started = time.perf_counter()
    yield
    observation.compute_returned = True


class NativeExecutionSequence:
    """Collect bounded per-attempt evidence inside one owned exploration worker.

    The existing exploration budget bounds the list. No telemetry is emitted
    inside the worker or while the native model lock is held. An attempt scope
    must enclose the canonical borrow/device fence, not just the library call.
    """

    def __init__(self) -> None:
        self._attempts: list[tuple[NativeExecutionObservation, BaseException | None]] = []
        self._finished = False

    @contextmanager
    def attempt(self) -> Iterator[None]:
        observation = NativeExecutionObservation("soft_attempt", soft_attempt=True)
        failure: BaseException | None = None
        try:
            with observation.bind():
                yield
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if observation.started is not None:
                observation.sealed_at = time.perf_counter()
                self._attempts.append((observation, failure))

    def finish(self, failure: BaseException | None = None) -> None:
        """Publish only after the sequence owner resolves its deadline/retirement."""
        if self._finished:
            return
        self._finished = True
        for observation, attempt_failure in self._attempts:
            if attempt_failure is not None:
                # The owning coroutine has the authoritative cancellation or
                # deadline result, including a failed retirement fence.
                observation.finish_exception(failure or attempt_failure)
            elif failure is not None:
                # The attempt returned, but the overall authorized sequence
                # did not complete. Do not promote intermediate work into
                # a successful admitted outcome.
                observation.finish("sequence_aborted")
            else:
                observation.finish("success")
        self._attempts.clear()


class ProviderHealthMonitor:
    """Single authority for observed provider health state."""

    def __init__(
        self,
        registry: Any = None,
        check_interval: int = 300,
        cache_ttl: int = 300,
    ) -> None:
        self.check_interval = check_interval
        self._cache_ttl = cache_ttl
        self._monitoring_active = False

        self._registry = registry
        self._health_cache: Dict[str, ProviderHealthInfo] = {}

        self._prev_statuses: Dict[str, HealthStatus] = {}

    def _provider_key(self, provider_id: str) -> str:
        """Canonicalize aliases once at the sole observed-health owner."""
        normalized = str(provider_id).strip().lower()
        if self._registry is not None:
            canonicalize = getattr(self._registry, "canonicalize_provider_id", None)
            if callable(canonicalize):
                canonical = canonicalize(normalized)
                if canonical:
                    return str(canonical).lower()
        return normalized

    def _get_provider_ids(self) -> List[str]:
        """Return the current provider inventory from the registry."""
        if self._registry is None:
            return []
        try:
            return self._registry.get_all_provider_names()
        except Exception:
            return []

    def get_provider_health(self, provider_id: str) -> ProviderHealthInfo:
        """Get health state for a provider.

        Returns a ProviderHealthInfo with UNKNOWN status if not yet checked.
        """
        provider_key = self._provider_key(provider_id)
        self._refresh_health_identity(provider_key)
        return self._read_cached_provider_health(provider_key)

    def _refresh_health_identity(self, provider_key: str) -> None:
        refresh = getattr(self._registry, "refresh_endpoint_health_identity", None)
        if callable(refresh):
            refresh(provider_key)

    def _read_cached_provider_health(self, provider_key: str) -> ProviderHealthInfo:
        cached = self._health_cache.get(provider_key)
        if cached is not None:
            cache_age = (
                (datetime.utcnow() - cached.last_checked_at).total_seconds()
                if cached.last_checked_at is not None else float("inf")
            )
            if cache_age < self._cache_ttl:
                return cached
            logger.debug("Health cache expired for %s", provider_key)

        return ProviderHealthInfo(
            provider_id=provider_key,
            health_status=HealthStatus.UNKNOWN,
            last_checked_at=None,
            metadata={"cache_miss": True},
        )

    def update_provider_health(
        self,
        provider_id: str,
        is_healthy: bool,
        response_time: Optional[float] = None,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Compatibility ingress; canonical endpoints require fenced publication."""
        publish = getattr(self._registry, "publish_legacy_provider_health", None)
        if callable(publish):
            publish(
                provider_id, is_healthy=is_healthy, response_time=response_time,
                error_code=error_code, error_type=error_type, error_message=error_message,
            )
            return
        self._apply_provider_health(
            provider_id, is_healthy=is_healthy, response_time=response_time,
            error_code=error_code, error_type=error_type, error_message=error_message,
        )

    def _apply_provider_health(
        self,
        provider_id: str,
        is_healthy: bool,
        response_time: Optional[float] = None,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Apply an observation admitted by the canonical registry."""
        provider_key = self._provider_key(provider_id)
        now = datetime.utcnow()

        existing = self._health_cache.get(provider_key)
        if existing is not None:
            health_info = existing
        else:
            health_info = ProviderHealthInfo(
                provider_id=provider_key,
                last_checked_at=now,
            )

        # An expired snapshot is UNKNOWN to readers. A fresh observation
        # must not silently suppress a transition from that visible state.
        # Registry-fenced publication has already admitted the observation.
        # Do not advance the destination generation between that check and
        # this write. Subsequent reads retire a now-superseded observation.
        prev_status = self._read_cached_provider_health(provider_key).health_status

        if is_healthy:
            health_info.health_status = HealthStatus.HEALTHY
            health_info.consecutive_failures = 0
            health_info.last_success_at = now
            health_info.error_code = None
            health_info.error_type = None
        else:
            health_info.consecutive_failures += 1
            health_info.last_failure_at = now
            health_info.error_code = error_code
            health_info.error_type = error_type
            if health_info.consecutive_failures >= 5:
                health_info.health_status = HealthStatus.UNHEALTHY
            elif health_info.consecutive_failures >= 2:
                health_info.health_status = HealthStatus.DEGRADED
            else:
                # An observed failed probe cannot be reported healthy.
                # A later verified success restores the healthy state.
                health_info.health_status = HealthStatus.DEGRADED

        health_info.last_checked_at = now
        health_info.latency_ms = response_time * 1000.0 if response_time is not None else None

        if error_message and not health_info.metadata:
            health_info.metadata = {}
        if error_message:
            health_info.metadata["last_error_message"] = error_message

        if not hasattr(health_info, "_recent_attempts"):
            health_info._recent_attempts: List[bool] = []
        health_info._recent_attempts.append(is_healthy)
        if len(health_info._recent_attempts) > 10:
            health_info._recent_attempts.pop(0)
        health_info.success_rate = sum(health_info._recent_attempts) / len(health_info._recent_attempts)

        self._health_cache[provider_key] = health_info

        self._emit_transition_if_changed(provider_key, prev_status, health_info.health_status)

        logger.debug(
            "Updated health for %s: %s", provider_id, health_info.health_status.value
        )

    def capture_endpoint_registration(
        self, endpoint: ProviderEndpoint, *, wire_base_url: str | None = None,
    ) -> object | None:
        """Read the canonical registry's opaque observation fence at handoff."""
        if self._registry is None:
            return None
        return self._registry.capture_endpoint_health_registration(
            endpoint, wire_base_url=wire_base_url,
        )

    def record_shared_http_execution(
        self, endpoint: ProviderEndpoint, *, transport: str,
        outcome: str, response_time: float, registration: object | None,
        wire_base_url: str | None,
    ) -> bool:
        """Accept only bounded observations for the still-registered shared endpoint.

        Personal/tenant-specific credentials and endpoints must not change the
        global availability of a provider alias. No request, tenant, model,
        URL or error body becomes a metrics label.
        """
        if (
            endpoint.tenant_scoped is not False
            or transport not in {"text", "structured", "sse"}
            or outcome not in {
                "success", "http_server_error", "connection_failure",
                "invalid_provider_response",
            }
            or not math.isfinite(response_time)
            or response_time < 0
            or self._registry is None
            or registration is None
            or not wire_base_url
        ):
            return False
        if not self._registry.publish_endpoint_health(
            endpoint, registration, is_healthy=outcome == "success",
            response_time=response_time,
            error_code=None if outcome == "success" else outcome,
            wire_base_url=wire_base_url,
        ):
            return False
        try:
            from ai_karen_engine.platform.observability.metrics import get_metrics_collector

            collector = get_metrics_collector()
            labels = {"transport": transport, "outcome": outcome}
            collector.counter(
                "kari_provider_http_observations_total",
                "Classified terminal shared provider HTTP observations",
                ["transport", "outcome"],
            ).labels(**labels).inc()
            collector.histogram(
                "kari_provider_http_observation_duration_seconds",
                "Elapsed client handoff to classified HTTP outcome",
                ["transport", "outcome"],
            ).labels(**labels).observe(response_time)
        except Exception:
            # Metrics failure must not reverse an observed health update.
            pass
        return True

    def record_native_execution(
        self, endpoint: ProviderEndpoint | None, *, operation: str,
        outcome: str, response_time: float, registration: object | None,
    ) -> bool:
        """Observe native execution without conflating reasoning, encoder and chat health."""
        if (
            operation not in {
                "generation", "embedding", "soft_reference", "soft_guided", "soft_verifier",
            }
            or outcome not in {
                "success", "cancelled", "deadline_exceeded", "execution_failed",
                "unverified_result", "retirement_unverified", "sequence_aborted",
            }
            or not math.isfinite(response_time)
            or response_time < 0
        ):
            return False
        try:
            from ai_karen_engine.platform.observability.metrics import get_metrics_collector

            collector = get_metrics_collector()
            labels = {"operation": operation, "outcome": outcome}
            collector.counter(
                "kari_native_execution_observations_total",
                "Governed native execution outcomes after worker retirement",
                ["operation", "outcome"],
            ).labels(**labels).inc()
            collector.histogram(
                "kari_native_execution_observation_duration_seconds",
                "Elapsed native invocation to attempt or admitted terminal outcome",
                ["operation", "outcome"],
            ).labels(**labels).observe(response_time)
        except Exception:
            pass
        if (
            operation == "generation" and outcome == "success"
            and endpoint is not None and endpoint.tenant_scoped is False
            and self._registry is not None and registration is not None
        ):
            from ai_karen_engine.core.model_runtime.runtime_engine import EndpointProtocol
            if endpoint.protocol is EndpointProtocol.NATIVE:
                return self._registry.publish_endpoint_health(
                    endpoint, registration, is_healthy=True, response_time=response_time,
                )
        return False

    def _emit_transition_if_changed(
        self,
        provider_id: str,
        prev_status: HealthStatus,
        new_status: HealthStatus,
    ) -> None:
        """Emit observability events on meaningful health transitions."""
        if prev_status == new_status:
            return

        try:
            from ai_karen_engine.core.observability.emitter import get_observability_emitter
            from ai_karen_engine.core.observability.contracts import RuntimeEventType

            # Use a health event, never an execution completion/failure or a
            # request-level degraded-mode signal. Unknown -> degraded is a
            # real first failed observation, not an event to discard.
            get_observability_emitter().emit(
                RuntimeEventType.PROVIDER_HEALTH_CHANGED,
                provider=provider_id,
                status=new_status.value,
                execution_layer="provider_health_monitor",
                metadata={
                    "previous_status": prev_status.value,
                    "new_status": new_status.value,
                },
            )
        except Exception:
            # Observability cannot make provider execution unavailable.
            pass

    def record_provider_interaction(
        self,
        provider_name: str,
        success: bool,
        response_time: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the result of an interaction with a provider."""
        self.update_provider_health(
            provider_id=provider_name,
            is_healthy=success,
            response_time=response_time,
            error_message=error_message,
        )

    def get_all_provider_health(self) -> Dict[str, ProviderHealthInfo]:
        """Get health state for all providers known to the registry."""
        result: Dict[str, ProviderHealthInfo] = {}
        for provider_id in self._get_provider_ids():
            result[provider_id] = self.get_provider_health(provider_id)
        return result

    def get_healthy_providers(self) -> List[str]:
        """Get providers currently in healthy or degraded state."""
        healthy: List[str] = []
        for provider_id in self._get_provider_ids():
            info = self.get_provider_health(provider_id)
            if info and info.health_status in {HealthStatus.HEALTHY, HealthStatus.DEGRADED}:
                healthy.append(provider_id)
        return healthy

    def invalidate_provider(self, provider_id: str) -> None:
        """Discard observations for a replaced or withdrawn endpoint identity."""
        provider_key = self._provider_key(provider_id)
        self._health_cache.pop(provider_key, None)
        self._prev_statuses.pop(provider_key, None)

    def clear_cache(self) -> None:
        """Clear the health state cache."""
        self._health_cache.clear()
        self._prev_statuses.clear()
        logger.info("Provider health cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the health cache."""
        for provider_key in tuple(self._health_cache):
            self._refresh_health_identity(provider_key)
        now = datetime.utcnow()
        stats: Dict[str, Any] = {
            "total_providers": len(self._health_cache),
            "healthy_count": 0,
            "degraded_count": 0,
            "unhealthy_count": 0,
            "unknown_count": 0,
            "cache_age_seconds": {},
            "average_latency_ms": None,
        }

        response_times: List[float] = []
        for provider_name, info in tuple(self._health_cache.items()):
            if info.health_status == HealthStatus.HEALTHY:
                stats["healthy_count"] += 1
            elif info.health_status == HealthStatus.DEGRADED:
                stats["degraded_count"] += 1
            elif info.health_status == HealthStatus.UNHEALTHY:
                stats["unhealthy_count"] += 1
            else:
                stats["unknown_count"] += 1

            if info.last_checked_at:
                stats["cache_age_seconds"][provider_name] = (
                    now - info.last_checked_at
                ).total_seconds()

            if info.latency_ms is not None:
                response_times.append(info.latency_ms)

        if response_times:
            stats["average_latency_ms"] = sum(response_times) / len(response_times)

        return stats


def get_health_monitor() -> ProviderHealthMonitor:
    """Return the registry-owned canonical health monitor.

    Startup, provider interaction receipts and the settings catalog must all
    consult the same observed health cache. No shadow global monitor.
    Import at call time to avoid the registry/health-module import cycle.
    """
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        get_provider_registry_service,
    )

    return get_provider_registry_service().health_monitor


def record_provider_success(provider_name: str, response_time: Optional[float] = None) -> None:
    """Convenience function to record a successful provider interaction."""
    monitor = get_health_monitor()
    monitor.record_provider_interaction(
        provider_name=provider_name,
        success=True,
        response_time=response_time,
    )


def record_provider_failure(provider_name: str, error_message: str) -> None:
    """Convenience function to record a failed provider interaction."""
    monitor = get_health_monitor()
    monitor.record_provider_interaction(
        provider_name=provider_name,
        success=False,
        error_message=error_message,
    )
