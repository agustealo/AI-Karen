"""Health diagnostics must never turn registry eligibility into inference evidence."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.models import providers
from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService


@pytest.mark.asyncio
async def test_health_routes_read_observations_without_legacy_provider_callbacks(monkeypatch):
    registry = ProviderRegistryService()
    endpoint = registry.register_configured_endpoint({
        "provider_id": "diagnostic_test", "enabled": True,
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
        registry.health_monitor.record_provider_interaction(endpoint.provider_id, success=True)
        recovered = await client.get("/health/diagnostic_test")
        assert recovered.json()["status"] == "healthy"
        assert recovered.json()["last_check"] is not None
