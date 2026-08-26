from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.operational_health import OperationalHealthService


_REQUIRED_SECRET_ENV = {
    "SECRET_KEY": "prod-secret-key-0123456789abcdef",
    "AUTH_SECRET_KEY": "prod-auth-secret-0123456789abcdef",
    "EXTENSION_SECRET_KEY": "prod-extension-secret-0123456789abcdef",
    "EXTENSION_API_KEY": "prod-extension-api-key-0123456789abcdef",
    "REDIS_PASSWORD": "prod-redis-password-0123456789abcdef",
}


def _set_safe_production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _REQUIRED_SECRET_ENV.items():
        monkeypatch.setenv(name, value)

    for name in (
        "AUTH_DEV_MODE",
        "AUTH_ALLOW_DEV_LOGIN",
        "KARI_AUTH_BYPASS",
        "EXTENSION_DEV_BYPASS_ENABLED",
        "KARI_SKIP_STARTUP_CHECK",
        "KARI_SKIP_AUTO_INIT",
        "KARI_DEFER_ROUTER_WIRING",
        "KARI_FAST_STARTUP",
    ):
        monkeypatch.setenv(name, "false")

    monkeypatch.setenv("KARI_ENABLE_MEMORY_SERVICE", "true")


def test_liveness_has_no_dependency_requirements() -> None:
    payload = OperationalHealthService.liveness()

    assert payload["status"] == "alive"
    assert payload["alive"] is True
    assert "checks" not in payload


@pytest.mark.asyncio
async def test_readiness_accepts_safe_production_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_production_environment(monkeypatch)
    service = OperationalHealthService()
    service._database_check = AsyncMock(  # type: ignore[method-assign]
        return_value={"ready": True, "status": "healthy"}
    )
    monkeypatch.setattr(
        service,
        "_redis_check",
        lambda *, required: {"ready": True, "status": "healthy"},
    )

    result = await service.readiness(environment="production")

    assert result.ready is True
    assert result.status == "ready"
    assert result.checks["configuration"]["ready"] is True


@pytest.mark.asyncio
async def test_readiness_rejects_production_dev_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_production_environment(monkeypatch)
    monkeypatch.setenv("KARI_AUTH_BYPASS", "true")
    service = OperationalHealthService()
    service._database_check = AsyncMock(  # type: ignore[method-assign]
        return_value={"ready": True, "status": "healthy"}
    )
    monkeypatch.setattr(
        service,
        "_redis_check",
        lambda *, required: {"ready": True, "status": "healthy"},
    )

    result = await service.readiness(environment="production")

    assert result.ready is False
    assert "KARI_AUTH_BYPASS=true" in result.checks["configuration"]["violations"]


@pytest.mark.asyncio
async def test_readiness_rejects_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_production_environment(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "CHANGE_ME_GENERATE_RANDOM_32_PLUS_BYTES")
    service = OperationalHealthService()
    service._database_check = AsyncMock(  # type: ignore[method-assign]
        return_value={"ready": True, "status": "healthy"}
    )
    monkeypatch.setattr(
        service,
        "_redis_check",
        lambda *, required: {"ready": True, "status": "healthy"},
    )

    result = await service.readiness(environment="production")

    assert result.ready is False
    assert "SECRET_KEY=missing_or_insecure" in result.checks["configuration"]["violations"]


def test_health_ingress_delegates_operational_checks_to_runtime() -> None:
    path = "src/ai_karen_engine/server/health_endpoints.py"
    source = open(path, encoding="utf-8").read()

    assert "get_operational_health_service" in source
    assert "get_database_client" not in source
    assert "get_redis_manager" not in source
    assert '@operational_router.get("/live")' in source
    assert '@operational_router.get("/ready")' in source
