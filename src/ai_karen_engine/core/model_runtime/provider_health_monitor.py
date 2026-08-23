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
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
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
        provider_key = provider_id.lower()
        cached = self._health_cache.get(provider_key)
        if cached is not None:
            cache_age = (datetime.utcnow() - cached.last_checked_at).total_seconds()
            if cache_age < self._cache_ttl:
                return cached
            logger.debug("Health cache expired for %s", provider_id)

        return ProviderHealthInfo(
            provider_id=provider_id,
            health_status=HealthStatus.UNKNOWN,
            last_checked_at=datetime.utcnow(),
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
        """Update observed health state for a provider."""
        provider_key = provider_id.lower()
        now = datetime.utcnow()

        existing = self._health_cache.get(provider_key)
        if existing is not None:
            health_info = existing
        else:
            health_info = ProviderHealthInfo(
                provider_id=provider_id,
                last_checked_at=now,
            )

        prev_status = health_info.health_status

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
                health_info.health_status = HealthStatus.HEALTHY

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

        self._emit_transition_if_changed(provider_id, prev_status, health_info.health_status)

        logger.debug(
            "Updated health for %s: %s", provider_id, health_info.health_status.value
        )

    def _emit_transition_if_changed(
        self,
        provider_id: str,
        prev_status: HealthStatus,
        new_status: HealthStatus,
    ) -> None:
        """Emit observability events on meaningful health transitions."""
        if prev_status == new_status:
            return

        transition = (prev_status, new_status)
        meaningful = {
            (HealthStatus.HEALTHY, HealthStatus.DEGRADED),
            (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY),
            (HealthStatus.UNHEALTHY, HealthStatus.HEALTHY),
            (HealthStatus.UNKNOWN, HealthStatus.HEALTHY),
            (HealthStatus.UNKNOWN, HealthStatus.UNHEALTHY),
            (HealthStatus.DEGRADED, HealthStatus.HEALTHY),
        }
        if transition not in meaningful:
            return

        event_type = None
        if new_status == HealthStatus.UNHEALTHY:
            event_type = "provider.unavailable"
        elif new_status == HealthStatus.DEGRADED:
            event_type = "provider.health.changed"
        elif new_status == HealthStatus.HEALTHY:
            event_type = "provider.available"

        if event_type is None:
            return

        try:
            from ai_karen_engine.core.observability.emitter import get_observability_emitter
            from ai_karen_engine.core.observability.contracts import RuntimeEventType

            emitter = get_observability_emitter()
            if event_type == "provider.available":
                emitter.emit(
                    RuntimeEventType.PROVIDER_ATTEMPT_COMPLETED,
                    provider=provider_id,
                    status="recovered",
                    metadata={
                        "previous_status": prev_status.value,
                        "new_status": new_status.value,
                    },
                )
            elif event_type == "provider.unavailable":
                emitter.emit(
                    RuntimeEventType.PROVIDER_ATTEMPT_FAILED,
                    provider=provider_id,
                    status="unavailable",
                    metadata={
                        "previous_status": prev_status.value,
                        "new_status": new_status.value,
                    },
                )
            else:
                emitter.emit(
                    RuntimeEventType.RUNTIME_DEGRADED,
                    provider=provider_id,
                    degraded_mode=True,
                    status=new_status.value,
                    metadata={
                        "previous_status": prev_status.value,
                        "new_status": new_status.value,
                    },
                )
        except Exception:
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

    def clear_cache(self) -> None:
        """Clear the health state cache."""
        self._health_cache.clear()
        self._prev_statuses.clear()
        logger.info("Provider health cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the health cache."""
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
        for provider_name, info in self._health_cache.items():
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


_health_monitor: Optional[ProviderHealthMonitor] = None


def get_health_monitor() -> ProviderHealthMonitor:
    """Get the global provider health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = ProviderHealthMonitor()
    return _health_monitor


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
