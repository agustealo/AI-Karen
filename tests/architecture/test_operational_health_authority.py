from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.operational_health import OperationalHealthService


_REQUIRED_SECRET_ENV = {
    "SECRET_KEY": "prod-secret-key-0123456789abcdef",
    "AUTH_SECRET_KEY": "prod-auth-secret-0123456789abcdef",
    "EXTENSION_SECRET_KEY": "prod-extension-secret-0123456789abcdef",
    "EXTENSION_API_KEY": "prod-extension-api-key-0123456789abcdef",
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
    monkeypatch.setenv("REDIS_URL", "redis://red-private:6379/0")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)


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
        AsyncMock(return_value={"ready": True, "status": "healthy"}),
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
        AsyncMock(return_value={"ready": True, "status": "healthy"}),
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
        AsyncMock(return_value={"ready": True, "status": "healthy"}),
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


def test_readiness_serialization_matches_canonical_frontend_health_contract() -> None:
    from ai_karen_engine.core.runtime.operational_health import OperationalHealthResult

    healthy = OperationalHealthResult(
        status="ready",
        ready=True,
        checks={
            "configuration": {"ready": True, "violations": []},
            "database": {"ready": True, "status": "healthy"},
            "redis": {"ready": True, "status": "healthy"},
        },
        timestamp=1.0,
    ).as_dict()
    assert healthy["components"] == {
        "configuration": "ready", "database": "ready", "redis": "ready",
    }
    assert healthy["checks"]["configuration"]["ready"] is True

    failed = OperationalHealthResult(
        status="not_ready", ready=False,
        checks={
            "configuration": {"ready": True},
            "database": {"ready": False, "status": "degraded"},
        }, timestamp=1.0,
    ).as_dict()
    assert failed["components"]["database"] == "not_ready"
    assert failed["components"]["configuration"] == "ready"
    assert failed["ready"] is False


@pytest.mark.parametrize(("url", "expected"), [
    ("redis://red-private:6379", True),
    ("redis://redis:6379/0", True),
    ("rediss://private-user:long-strong-password-12345@cache.example.com:6379/0", True),
    ("redis://localhost:6379/0", False),
    ("redis://127.0.0.1:6379/0", False),
    ("redis://10.0.0.5:6379/0", False),
    ("redis://public.example.com:6379", False),
    ("redis://user:long-strong-password-12345@public.example.com:6379", False),
    ("rediss://public.example.com:6379", False),
    ("rediss://user:short@public.example.com:6379", False),
    ("redis://user@red-private:6379", False),
    ("redis://red-private:6379?ssl_cert_reqs=none", False),
    ("redis://red-private:6379/42", False),
    ("not-a-url", False),
    ("", False),
])
def test_production_redis_target_requires_private_network_or_authenticated_tls(
    url: str, expected: bool,
) -> None:
    assert OperationalHealthService._redis_target_secure(url) is expected


@pytest.mark.asyncio
async def test_redis_readiness_uses_canonical_live_connection_and_never_returns_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.platform.memory import redis as redis_module

    class Manager:
        is_healthy = AsyncMock(return_value=True)

    manager = Manager()
    monkeypatch.setattr(redis_module, "get_redis_manager", lambda: manager)
    result = await OperationalHealthService._redis_check(required=True)
    assert result == {"ready": True, "status": "healthy"}
    manager.is_healthy.assert_awaited_once()

    manager.is_healthy = AsyncMock(return_value=False)
    assert await OperationalHealthService._redis_check(required=True) == {
        "ready": False, "status": "degraded",
    }
    manager.is_healthy = AsyncMock(
        side_effect=ConnectionError("private-user:do-not-print@red-private"),
    )
    failed = await OperationalHealthService._redis_check(required=True)
    assert failed["ready"] is False
    assert failed["status"] == "unavailable"
    assert failed["error_type"] == "ConnectionError"
    assert "do-not-print" not in repr(failed)

    assert await OperationalHealthService._redis_check(required=False) == {
        "ready": True, "status": "not_required",
    }


@pytest.mark.asyncio
async def test_uninitialized_canonical_redis_manager_cannot_report_healthy() -> None:
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
        RedisConnectionManager,
    )

    manager = RedisConnectionManager(redis_url="redis://red-private:6379")
    assert manager.is_degraded() is False
    assert manager.health() is False
    assert await manager.is_healthy() is False

    manager._client = type("HealthyClient", (), {"ping": AsyncMock(return_value=True)})()
    assert await manager.is_healthy() is True
    manager._degraded_mode = True
    assert await manager.is_healthy() is False
    manager._degraded_mode = False
    manager._client.ping = AsyncMock(side_effect=ConnectionError("offline"))
    assert await manager.is_healthy() is False


def test_server_and_web_consumer_health_projection_share_a_contract() -> None:
    from pathlib import Path

    server = Path("src/ai_karen_engine/server/health_endpoints.py").read_text()
    web = Path("src/ui_launchers/Karen-AI-Theme/src/app/api/health/route.ts").read_text()
    operational = Path("src/ai_karen_engine/core/runtime/operational_health.py").read_text()

    assert "result.as_dict()" in server
    assert 'readiness.status !== \'ready\'' in web
    assert "readiness.components" not in web  # Components are read as a property.
    assert "const components = readiness.components" in web
    assert "components" in operational
    assert '"configuration"' in web and '"database"' in web
