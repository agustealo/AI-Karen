"""Health diagnostics must never turn registry eligibility into inference evidence."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.models import providers
from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService
from ai_karen_engine.core.model_runtime.provider_execution import _resolve_base_url


def _publish_fixture(registry, endpoint):
    url = _resolve_base_url(endpoint)
    token = registry.capture_endpoint_health_registration(endpoint, wire_base_url=url)
    assert registry.publish_endpoint_health(
        endpoint, token, is_healthy=True, response_time=0.1, wire_base_url=url,
    )


@pytest.mark.asyncio
async def test_health_routes_read_observations_without_legacy_provider_callbacks(monkeypatch):
    registry = ProviderRegistryService()
    endpoint = registry.register_configured_endpoint({
        "provider_id": "diagnostic_test", "enabled": True, "tenant_scoped": False,
        "base_url": "http://127.0.0.1:1234/v1",
        "default_model": "registered-model", "capabilities": ["chat"],
    })
    app = FastAPI()
    app.include_router(providers.router)
    app.dependency_overrides[providers.get_provider_registry_service] = lambda: registry
    def forbidden():
        pytest.fail("health diagnostics must not resolve the legacy registry")
    app.dependency_overrides[providers.get_llm_registry] = forbidden

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for path in (
            "/health/diagnostic_test", "/diagnostic_test/health", "/diagnostic_test/health/detailed",
        ):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json()["status"] == "unknown"
            assert response.json()["last_check"] is None
        detail = response.json()
        assert detail["model_availability"]["total_models"] == 1
        assert detail["model_availability"]["execution_verified"] is False
        assert detail["model_availability"]["discovery_successful"] is None
        all_health = await client.post("/health-check-all")
        assert all_health.json()["diagnostic_test"]["status"] == "unknown"
        assert (await client.get("/health/not_registered_test")).status_code == 404
        _publish_fixture(registry, endpoint)
        recovered = await client.get("/health/diagnostic_test")
        assert recovered.json()["status"] == "healthy"
        assert recovered.json()["last_check"] is not None


@pytest.mark.asyncio
async def test_aggregate_routes_use_canonical_health_and_static_summary_path(monkeypatch):
    from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import (
        ProviderModelCompatibilityService,
    )

    registry = ProviderRegistryService()
    endpoint = registry.register_configured_endpoint({
        "provider_id": "aggregate_test", "enabled": True, "tenant_scoped": False,
        "base_url": "http://localhost:1234/v1", "default_model": "registered-model",
        "capabilities": ["chat"],
    })
    monkeypatch.setattr(registry, "get_all_provider_names", lambda: ["aggregate_test"])
    monkeypatch.setattr(
        ProviderModelCompatibilityService, "validate_provider_model_setup",
        lambda self, name: {"status": "error", "error": "private diagnostic error"},
    )
    app = FastAPI()
    app.include_router(providers.router)
    app.dependency_overrides[providers.get_provider_registry_service] = lambda: registry

    def forbidden():
        pytest.fail("aggregate health must not resolve legacy registry")

    app.dependency_overrides[providers.get_llm_registry] = forbidden
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        stats = (await client.get("/stats")).json()
        assert stats["healthy_providers"] == 0
        assert stats["unknown_providers"] == 1
        assert stats["last_health_check"] is None
        summary_response = await client.get("/health/llms")
        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["overall_status"] == "unknown"
        assert summary["unknown_providers"] == ["aggregate_test"]
        assert summary["last_health_check"] is None
        assert summary["degraded_mode_active"] is False
        integration_response = await client.get("/integration/status")
        assert integration_response.status_code == 200
        integration = integration_response.json()
        assert integration["healthy_providers"] == 0
        assert integration["overall_status"] == "unknown"
        row = integration["providers"]["aggregate_test"]
        assert row["has_compatible_models"] is None
        assert row["total_compatible"] is None
        assert "private diagnostic error" not in integration_response.text
        _publish_fixture(registry, endpoint)
        assert (await client.get("/health/llms")).json()["healthy_providers"] == ["aggregate_test"]
