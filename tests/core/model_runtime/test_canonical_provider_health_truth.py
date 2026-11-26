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
    record_provider_failure("health-reuse", "test_observed_probe_failure")
    assert (
        registry.health_monitor.get_provider_health("health-reuse").health_status
        is HealthStatus.DEGRADED
    )
    record_provider_success("health-reuse")
    assert (
        registry.health_monitor.get_provider_health("health-reuse").health_status
        is HealthStatus.HEALTHY
    )


def test_legacy_provider_alias_and_canonical_id_share_one_health_record(
    monkeypatch,
) -> None:
    registry = provider_registry_service.ProviderRegistryService()
    monkeypatch.setattr(
        provider_registry_service, "_provider_registry_service", registry
    )
    record_provider_success("ollama")
    assert (
        registry.health_monitor.get_provider_health("ollama-local").health_status
        is HealthStatus.HEALTHY
    )
    assert registry.health_monitor.get_provider_health("ollama") is (
        registry.health_monitor.get_provider_health("ollama-local")
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


def test_observed_health_transitions_emit_distinct_canonical_events(monkeypatch):
    from ai_karen_engine.platform.observability import events
    from ai_karen_engine.platform.observability.contracts import EventType

    sink = events.InMemorySink()
    monkeypatch.setattr(events, "_emitter", events.ObservabilityEmitter([sink]))
    registry = provider_registry_service.ProviderRegistryService()
    monitor = registry.health_monitor
    for _ in range(5):
        monitor.record_provider_interaction("ollama", success=False)
    monitor.record_provider_interaction("ollama-local", success=True)
    monitor.record_provider_interaction("ollama", success=True)

    assert [event.event_type for event in sink.events] == [
        EventType.PROVIDER_HEALTH_CHANGED,
        EventType.PROVIDER_HEALTH_CHANGED,
        EventType.PROVIDER_HEALTH_CHANGED,
    ]
    assert [(event.metadata["previous_status"], event.status) for event in sink.events] == [
        ("unknown", "degraded"), ("degraded", "unhealthy"), ("unhealthy", "healthy"),
    ]
    assert all(event.provider == "ollama-local" for event in sink.events)
    assert all(event.degraded_mode is None for event in sink.events)
    assert all(event.execution_layer == "provider_health_monitor" for event in sink.events)


def test_health_observation_after_expiry_emits_unknown_to_current(monkeypatch):
    from datetime import timedelta
    from ai_karen_engine.platform.observability import events

    sink = events.InMemorySink()
    monkeypatch.setattr(events, "_emitter", events.ObservabilityEmitter([sink]))
    monitor = ProviderHealthMonitor(cache_ttl=60)
    monitor.record_provider_interaction("test", success=True)
    monitor.get_provider_health("test").last_checked_at -= timedelta(seconds=61)
    assert monitor.get_provider_health("test").health_status is HealthStatus.UNKNOWN
    monitor.record_provider_interaction("test", success=True)
    assert [(event.metadata["previous_status"], event.status) for event in sink.events] == [
        ("unknown", "healthy"), ("unknown", "healthy"),
    ]


def test_registry_projection_observes_failure_recovery_and_expiry_without_cache_delay():
    from datetime import timedelta

    registry = provider_registry_service.ProviderRegistryService()
    provider = "ollama-local"
    first = registry.get_provider_status(provider)
    assert first is not None and first.health_status is HealthStatus.UNKNOWN
    assert first.is_available
    for _ in range(5):
        registry.health_monitor.record_provider_interaction(provider, success=False)
    unhealthy = registry.get_provider_status(provider)
    assert unhealthy.health_status is HealthStatus.UNHEALTHY
    assert not unhealthy.is_available
    assert unhealthy.last_check == first.last_check  # credential cache retained
    assert first.health_status is HealthStatus.UNKNOWN  # prior projection unchanged

    registry.health_monitor.record_provider_interaction(provider, success=True)
    recovered = registry.get_provider_status(provider)
    assert recovered.health_status is HealthStatus.HEALTHY and recovered.is_available
    assert recovered.last_check == first.last_check

    registry.health_monitor.get_provider_health(provider).last_checked_at -= timedelta(
        seconds=registry.health_monitor._cache_ttl + 1,
    )
    expired = registry.get_provider_status(provider)
    assert expired.health_status is HealthStatus.UNKNOWN and expired.is_available
    assert expired.last_check == first.last_check


def test_disabled_endpoint_cannot_be_made_available_by_observation():
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.register_configured_endpoint({
        "provider_id": "disabled_health_projection", "enabled": False,
        "base_url": "http://127.0.0.1:1234/v1", "capabilities": ["chat"],
    })
    registry.health_monitor.record_provider_interaction(endpoint.provider_id, success=True)
    status = registry.get_provider_status(endpoint.provider_id)
    assert status.health_status is HealthStatus.UNAVAILABLE
    assert not status.is_available


def test_system_status_remote_outages_require_observed_shared_cloud_failure(monkeypatch):
    from ai_karen_engine.core.model_runtime.provider_endpoint import (
        ProviderEndpoint, ProviderEndpointType,
    )
    from ai_karen_engine.core.model_runtime.runtime_engine import EndpointKind, Locality

    registry = provider_registry_service.ProviderRegistryService()
    # Explicit credential classification, no network calls or real secrets.
    monkeypatch.setattr(
        registry, "_check_api_key_availability",
        lambda provider_id: provider_id != "cloud-missing-key",
    )
    for name, cloud, enabled, scoped, failed, key_required in [
        ("cloud-observed-failure", True, True, False, True, True),
        ("cloud-unchecked", True, True, False, False, True),
        ("cloud-disabled", True, False, False, True, True),
        ("cloud-missing-key", True, True, False, True, True),
        ("cloud-tenant-scoped", True, True, True, True, True),
        ("local-failed", False, True, False, True, False),
    ]:
        endpoint = ProviderEndpoint(
            provider_id=name, display_name=name,
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            kind=EndpointKind.CLOUD_PROVIDER if cloud else EndpointKind.LOCAL_ENDPOINT,
            locality=Locality.CLOUD if cloud else Locality.LOCAL,
            base_url="https://example.invalid/v1" if cloud else "http://localhost:1234/v1",
            enabled=enabled, tenant_scoped=scoped,
            api_key_env="TEST_ONLY_CREDENTIAL" if key_required else None,
        )
        registry.register_provider_endpoint(endpoint)
        if failed:
            for _ in range(5):
                registry.health_monitor.record_provider_interaction(name, success=False)

    assert registry.get_system_status()["remote_provider_outages"] == ["cloud-observed-failure"]
    registry.health_monitor.record_provider_interaction("cloud-observed-failure", success=True)
    assert registry.get_system_status()["remote_provider_outages"] == []


def test_diagnostic_snapshot_distinguishes_eligibility_inventory_and_observation():
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.register_configured_endpoint({
        "provider_id": "diagnostic_test", "enabled": True,
        "base_url": "http://127.0.0.1:1234/v1",
        "default_model": "registered-model", "capabilities": ["chat"],
    })
    first = registry.get_provider_health_snapshot(endpoint.provider_id)
    assert first["status"] == "unknown"
    assert first["is_available"] is True
    assert first["last_check"] is None
    assert first["response_time"] is None
    assert first["registered_model_count"] == 1
    registry.health_monitor.record_provider_interaction(
        endpoint.provider_id, success=False, error_message="private upstream text",
    )
    failed = registry.get_provider_health_snapshot(endpoint.provider_id)
    assert failed["status"] == "degraded"
    assert failed["last_check"] is not None
    assert "private upstream text" not in repr(failed)
    registry.health_monitor.record_provider_interaction(
        endpoint.provider_id, success=True, response_time=0.125,
    )
    recovered = registry.get_provider_health_snapshot(endpoint.provider_id)
    assert recovered["status"] == "healthy"
    assert recovered["response_time"] == 0.125
    assert registry.get_provider_health_snapshot("missing_test_provider") is None


def test_aggregate_health_preserves_all_five_states_and_observation_time(monkeypatch):
    registry = provider_registry_service.ProviderRegistryService()
    names = ["agg_healthy", "agg_degraded", "agg_unhealthy", "agg_unknown", "agg_disabled"]
    for name in names:
        registry.register_configured_endpoint({
            "provider_id": name, "enabled": name != "agg_disabled",
            "base_url": "http://localhost:1234/v1", "capabilities": ["chat"],
            "default_model": name + "_model",
        })
    monkeypatch.setattr(registry, "get_all_provider_names", lambda: names)
    unchecked = registry.get_provider_health_summary()
    assert unchecked["overall_status"] == "unknown"
    assert unchecked["last_health_check"] is None
    assert not unchecked["degraded_mode"]
    assert unchecked["groups"]["healthy"] == []
    registry.health_monitor.record_provider_interaction("agg_healthy", success=True)
    registry.health_monitor.record_provider_interaction("agg_degraded", success=False)
    for _ in range(5):
        registry.health_monitor.record_provider_interaction("agg_unhealthy", success=False)
    registry.health_monitor.record_provider_interaction("agg_disabled", success=True)
    summary = registry.get_provider_health_summary(llm_only=True)
    assert summary["groups"] == {
        "healthy": ["agg_healthy"], "degraded": ["agg_degraded"],
        "unhealthy": ["agg_unhealthy"], "unknown": ["agg_unknown"],
        "unavailable": ["agg_disabled"],
    }
    assert summary["overall_status"] == "degraded"
    assert summary["registered_model_count"] == 5
    assert summary["eligible_registered_model_count"] == 3
    assert summary["local_models_count"] == 3
    assert summary["last_health_check"] == max(
        row["last_check"] for row in summary["providers"].values()
        if row["last_check"] is not None
    )
