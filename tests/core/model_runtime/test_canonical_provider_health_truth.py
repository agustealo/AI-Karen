"""Canonical provider-health ownership and observed-state truth.

No live endpoints or credentials are needed. These tests prove the registry
owns the observed-health monitor, that a failed probe is never marked healthy,
and that registration is not itself an observed successful probe.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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



def test_endpoint_replacement_discards_old_health_and_keeps_registration_eligible():
    from dataclasses import replace
    from ai_karen_engine.core.model_runtime.provider_execution import _resolve_base_url

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    registration = monitor.capture_endpoint_registration(endpoint)
    assert registration is not None
    assert monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=registration, wire_base_url=_resolve_base_url(endpoint),
    )
    monitor.record_provider_interaction("lmstudio-desktop", success=True)
    replacement = replace(endpoint, base_url="http://127.0.0.1:11435/v1")
    registry.register_provider_endpoint(replacement)

    snapshot = registry.get_provider_health_snapshot("ollama-local")
    assert snapshot["status"] == "unknown"
    assert snapshot["last_check"] is None
    assert snapshot["response_time"] is None
    assert snapshot["is_available"] is True
    assert monitor.get_provider_health("ollama").health_status is HealthStatus.UNKNOWN
    assert monitor.get_provider_health("lmstudio-desktop").health_status is HealthStatus.HEALTHY
    # Completion against the superseded endpoint cannot restore its evidence.
    assert not monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=registration, wire_base_url=_resolve_base_url(endpoint),
    )
    assert monitor.get_provider_health("ollama-local").health_status is HealthStatus.UNKNOWN
    assert monitor.record_shared_http_execution(
        replacement, transport="text", outcome="success", response_time=0.2,
        registration=monitor.capture_endpoint_registration(replacement),
        wire_base_url=_resolve_base_url(replacement),
    )
    assert registry.get_provider_health_snapshot("ollama-local")["status"] == "healthy"


def test_identical_endpoint_registration_preserves_health_observation():
    from dataclasses import replace

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    monitor.record_provider_interaction(endpoint.provider_id, success=True)
    before = monitor.get_provider_health(endpoint.provider_id)
    registry.register_provider_endpoint(replace(endpoint))
    assert monitor.get_provider_health(endpoint.provider_id) is before


def test_replacing_failed_endpoint_does_not_inherit_old_failure():
    from dataclasses import replace

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    for _ in range(5):
        registry.health_monitor.record_provider_interaction(endpoint.provider_id, success=False)
    assert not registry.get_provider_status(endpoint.provider_id).is_available
    registry.register_provider_endpoint(replace(endpoint, default_model="new-model"))
    status = registry.get_provider_status(endpoint.provider_id)
    assert status.health_status is HealthStatus.UNKNOWN
    assert status.is_available
    assert registry.health_monitor.get_provider_health(endpoint.provider_id).consecutive_failures == 0


def test_disable_and_reenable_endpoint_does_not_restore_prior_health():
    from dataclasses import replace

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    registry.health_monitor.record_provider_interaction(endpoint.provider_id, success=True)
    registry.register_provider_endpoint(replace(endpoint, enabled=False))
    assert registry.get_provider_status(endpoint.provider_id).health_status is HealthStatus.UNAVAILABLE
    registry.register_provider_endpoint(endpoint)
    assert registry.get_provider_status(endpoint.provider_id).health_status is HealthStatus.UNKNOWN


def test_withdrawn_configured_endpoint_discards_observed_health(monkeypatch):
    from dataclasses import replace

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    configured = replace(
        endpoint, provider_id="withdrawn_test", metadata={"configuration_owner": "llm_provider_config"},
    )
    monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: configured)
    registry.register_provider_endpoint(configured)
    registry.health_monitor.record_provider_interaction(configured.provider_id, success=True)
    monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: None)
    assert registry.get_provider_endpoint(configured.provider_id) is None
    assert registry.health_monitor.get_provider_health(configured.provider_id).health_status is HealthStatus.UNKNOWN
    monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: configured)
    assert registry.get_provider_status(configured.provider_id).health_status is HealthStatus.UNKNOWN


@pytest.mark.parametrize("transport", ["http", "native"])
@pytest.mark.parametrize("mutation", ["replace", "aba", "identical", "withdraw"])
def test_transport_health_publication_is_registration_fenced(monkeypatch, transport, mutation):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Event

    from ai_karen_engine.core.model_runtime import provider_health_monitor as health
    from ai_karen_engine.core.model_runtime.provider_execution import _HttpExecutionObservation, _resolve_base_url

    registry = provider_registry_service.ProviderRegistryService()
    provider = "ollama-local" if transport == "http" else "builtin_transformers"
    endpoint = registry.get_provider_endpoint(provider)
    assert endpoint is not None
    if mutation == "withdraw":
        endpoint = replace(endpoint, metadata={
            **endpoint.metadata, "configuration_owner": "llm_provider_config",
        })
        monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: endpoint)
        registry.register_provider_endpoint(endpoint)
    monitor = registry.health_monitor
    monkeypatch.setattr(health, "get_health_monitor", lambda: monitor)

    if transport == "http":
        observation = _HttpExecutionObservation(endpoint, transport="text", shared=True)
        observation.handoff(_resolve_base_url(endpoint))
        observation.response_status = 200
        finish = observation.complete
    else:
        native = health.NativeExecutionObservation("generation", endpoint=endpoint)
        with native.bind(), health.observe_native_compute("generation"):
            pass
        def finish_native():
            return native.finish("success")

        finish = finish_native

    # A real admitted handoff precedes the concurrent registration change.
    token = monitor.capture_endpoint_registration(endpoint)
    assert token is not None
    entered = Event()
    release = Event()
    original = registry.publish_endpoint_health
    transitions = []
    monkeypatch.setattr(monitor, "_emit_transition_if_changed", lambda *args: transitions.append(args))

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "publication barrier was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "publish_endpoint_health", blocked)
    replacement = replace(endpoint, default_model="replacement-model")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(finish)
        try:
            assert entered.wait(5), "transport did not attempt publication"
            if mutation == "withdraw":
                monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: None)
                assert registry.get_provider_endpoint(provider) is None
                monkeypatch.setattr(registry, "_configured_external_endpoint", lambda _: endpoint)
                registry.get_provider_endpoint(provider)
            elif mutation == "identical":
                registry.register_provider_endpoint(replace(endpoint))
            else:
                registry.register_provider_endpoint(replacement)
                if mutation == "aba":
                    registry.register_provider_endpoint(endpoint)
        finally:
            release.set()
        future.result(timeout=5)

    if mutation == "identical":
        assert len(transitions) == 1
        assert monitor.get_provider_health(provider).health_status is HealthStatus.HEALTHY
        assert monitor.capture_endpoint_registration(endpoint) is token
    else:
        assert transitions == []
        assert monitor.get_provider_health(provider).health_status is HealthStatus.UNKNOWN
        current = registry.get_provider_endpoint(provider)
        assert current is not None
        fresh = monitor.capture_endpoint_registration(current)
        assert fresh is not None and fresh is not token
        assert original(
            current, fresh, is_healthy=True, response_time=0.1,
            wire_base_url=_resolve_base_url(current) if transport == "http" else None,
        )
        assert monitor.get_provider_health(provider).health_status is HealthStatus.HEALTHY


def test_unfenced_endpoint_observation_cannot_publish_health():
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    assert not monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=None, wire_base_url=endpoint.base_url,
    )
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.UNKNOWN



def test_wire_destination_rechecked_inside_registry_publication(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from ai_karen_engine.core.model_runtime import provider_health_monitor as health
    from ai_karen_engine.core.model_runtime.provider_execution import _HttpExecutionObservation

    old_url = "http://localhost:11434/v1"
    new_url = "http://localhost:11435/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", old_url)
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    monkeypatch.setattr(health, "get_health_monitor", lambda: monitor)
    observation = _HttpExecutionObservation(endpoint, transport="text", shared=True)
    observation.handoff(old_url)
    assert observation.registration is not None
    observation.response_status = 200
    entered, release = Event(), Event()
    original = registry.publish_endpoint_health

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "publish_endpoint_health", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(observation.complete)
        try:
            assert entered.wait(5)
            monkeypatch.setenv("OLLAMA_BASE_URL", new_url)
        finally:
            release.set()
        future.result(timeout=5)
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.UNKNOWN
    assert monitor.capture_endpoint_registration(endpoint, wire_base_url=old_url) is None
    fresh = monitor.capture_endpoint_registration(endpoint, wire_base_url=new_url)
    assert fresh is not None
    assert not monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=fresh, wire_base_url=None,
    )
    assert original(endpoint, fresh, is_healthy=True, response_time=0.1, wire_base_url=new_url)
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.HEALTHY



@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("reader", ["monitor", "snapshot", "aggregate", "cache_stats", "registry"])
def test_observed_destination_drift_retires_cached_health_and_registration(monkeypatch, success, reader):
    old_url = "http://localhost:11434/v1"
    new_url = "http://localhost:11435/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", old_url)
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    token = monitor.capture_endpoint_registration(endpoint, wire_base_url=old_url)
    assert token is not None
    for _ in range(5):
        assert monitor.record_shared_http_execution(
            endpoint, transport="text", outcome="success" if success else "http_server_error",
            response_time=0.1, registration=token, wire_base_url=old_url,
        )
    assert monitor.get_provider_health(endpoint.provider_id).health_status is (
        HealthStatus.HEALTHY if success else HealthStatus.UNHEALTHY
    )
    monitor.record_provider_interaction("lmstudio-desktop", success=True)
    other = monitor.get_provider_health("lmstudio-desktop")
    monkeypatch.setenv("OLLAMA_BASE_URL", new_url)
    if reader == "monitor":
        assert monitor.get_provider_health("ollama").health_status is HealthStatus.UNKNOWN
    elif reader == "snapshot":
        assert registry.get_provider_health_snapshot(endpoint.provider_id)["status"] == "unknown"
    elif reader == "aggregate":
        assert monitor.get_all_provider_health()[endpoint.provider_id].health_status is HealthStatus.UNKNOWN
    elif reader == "cache_stats":
        assert monitor.get_cache_stats()["total_providers"] == 1
    else:
        assert registry.get_provider_endpoint(endpoint.provider_id) == endpoint

    info = monitor.get_provider_health(endpoint.provider_id)
    assert info.health_status is HealthStatus.UNKNOWN
    assert info.last_checked_at is None and info.latency_ms is None
    assert info.consecutive_failures == 0
    assert monitor.get_provider_health("lmstudio-desktop") is other
    new_token = monitor.capture_endpoint_registration(endpoint, wire_base_url=new_url)
    assert new_token is not None and new_token is not token
    assert not monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=token, wire_base_url=old_url,
    )
    # Observed ABA cannot revive the original token or its cached health.
    monkeypatch.setenv("OLLAMA_BASE_URL", old_url)
    fresh = monitor.capture_endpoint_registration(endpoint, wire_base_url=old_url)
    assert fresh is not None and fresh is not token and fresh is not new_token
    assert not monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="success", response_time=0.1,
        registration=token, wire_base_url=old_url,
    )
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.UNKNOWN
    assert monitor.record_shared_http_execution(
        endpoint, transport="text", outcome="http_server_error", response_time=0.2,
        registration=fresh, wire_base_url=old_url,
    )
    info = monitor.get_provider_health(endpoint.provider_id)
    assert info.health_status is HealthStatus.DEGRADED
    assert info.consecutive_failures == 1


def test_equivalent_effective_destination_preserves_health_generation(monkeypatch):
    url = "http://localhost:11434/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", url)
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    token = monitor.capture_endpoint_registration(endpoint, wire_base_url=url)
    assert token is not None
    assert monitor.record_shared_http_execution(
        endpoint, transport="sse", outcome="success", response_time=0.1,
        registration=token, wire_base_url=url,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", url + "/")
    assert monitor.capture_endpoint_registration(endpoint, wire_base_url=url) is token
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.HEALTHY



@pytest.mark.parametrize("wire_url", [None, "", "http://localhost:11435/v1"])
@pytest.mark.parametrize("success", [True, False])
def test_registry_publication_requires_http_wire_destination(monkeypatch, wire_url, success):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    registry = provider_registry_service.ProviderRegistryService()
    endpoint = registry.get_provider_endpoint("ollama-local")
    assert endpoint is not None
    monitor = registry.health_monitor
    # An otherwise valid opaque registration cannot substitute for the
    # transport's observed wire identity at the final publication boundary.
    registration = registry.capture_endpoint_health_registration(endpoint)
    assert registration is not None
    assert not registry.publish_endpoint_health(
        endpoint, registration, is_healthy=success, response_time=0.1,
        wire_base_url=wire_url,
    )
    assert monitor.get_provider_health(endpoint.provider_id).health_status is HealthStatus.UNKNOWN
    assert registry.publish_endpoint_health(
        endpoint, registration, is_healthy=success, response_time=0.1,
        wire_base_url="http://localhost:11434/v1",
    )
    assert monitor.get_provider_health(endpoint.provider_id).health_status is (
        HealthStatus.HEALTHY if success else HealthStatus.DEGRADED
    )
