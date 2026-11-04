"""Canonical provider-health ownership and observed-state truth.

No live endpoints or credentials are needed. These tests prove the registry
owns the observed-health monitor, that a failed probe is never marked healthy,
and that registration is not itself an observed successful probe.
"""

from __future__ import annotations

from types import SimpleNamespace

from ai_karen_engine.core.model_runtime import provider_registry_service
from ai_karen_engine.core.model_runtime.provider_health_monitor import (
    HealthStatus,
    ProviderHealthMonitor,
    get_health_monitor,
    record_provider_failure,
    record_provider_success,
)


def test_unknown_provider_is_unchecked_not_healthy() -> None:
    monitor = ProviderHealthMonitor(
        registry=SimpleNamespace(get_all_provider_names=lambda: ["local-test"])
    )
    unknown = monitor.get_provider_health("local-test")
    assert unknown.health_status is HealthStatus.UNKNOWN
    assert unknown.last_checked_at is None
    assert monitor.get_all_provider_health()["local-test"].health_status is HealthStatus.UNKNOWN


def test_first_failed_probe_is_degraded_not_healthy_and_success_recovers() -> None:
    monitor = ProviderHealthMonitor()
    monitor.record_provider_interaction("local-test", success=False)
    degraded = monitor.get_provider_health("local-test")
    assert degraded.health_status is HealthStatus.DEGRADED
    assert degraded.last_checked_at is not None
    assert degraded.consecutive_failures == 1
    monitor.record_provider_interaction("local-test", success=True)
    healthy = monitor.get_provider_health("local-test")
    assert healthy.health_status is HealthStatus.HEALTHY
    assert healthy.consecutive_failures == 0


def test_repeated_observed_failure_becomes_unhealthy() -> None:
    monitor = ProviderHealthMonitor()
    for _ in range(5):
        monitor.record_provider_interaction("local-test", success=False)
    assert monitor.get_provider_health("local-test").health_status is HealthStatus.UNHEALTHY


def test_global_monitor_accessor_reuses_registry_instance(monkeypatch) -> None:
    registry = provider_registry_service.ProviderRegistryService()
    monkeypatch.setattr(
        provider_registry_service, "_provider_registry_service", registry
    )
    assert get_health_monitor() is registry.health_monitor
    record_provider_failure("health-reuse")
    assert (
        registry.health_monitor.get_provider_health("health-reuse").health_status
        is HealthStatus.DEGRADED
    )
    record_provider_success("health-reuse")
    assert (
        registry.health_monitor.get_provider_health("health-reuse").health_status
        is HealthStatus.HEALTHY
    )


def test_endpoint_registration_does_not_fabricate_healthy_probe() -> None:
    registry = provider_registry_service.ProviderRegistryService()
    registry.register_configured_endpoint(
        {
            "provider_id": "local_unchecked_test",
            "display_name": "Local unchecked test",
            "enabled": True,
            "base_url": "http://127.0.0.1:1234/v1",
            "capabilities": ["chat"],
        }
    )
    status = registry.get_provider_status("local_unchecked_test")
    assert status is not None
    assert status.health_status is HealthStatus.UNKNOWN
    # Existing execution selection can attempt a first local request; no
    # backend health record should claim that it has already succeeded.
    assert status.is_available is True


def test_disabled_endpoint_reports_unavailable_without_crashing() -> None:
    registry = provider_registry_service.ProviderRegistryService()
    registry.register_configured_endpoint(
        {
            "provider_id": "local_disabled_test",
            "display_name": "Local disabled test",
            "enabled": False,
            "base_url": "http://127.0.0.1:1234/v1",
            "capabilities": ["chat"],
        }
    )
    status = registry.get_provider_status("local_disabled_test")
    assert status is not None
    assert status.health_status is HealthStatus.UNAVAILABLE
    assert status.is_available is False
