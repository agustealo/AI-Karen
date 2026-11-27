from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.operational_health import OperationalHealthService


_REQUIRED_SECRET_ENV = {
    "SECRET_KEY": "prod-secret-key-0123456789abcdef",
    "AUTH_SECRET_KEY": "prod-auth-secret-0123456789abcdef",
    "EXTENSION_SECRET_KEY": "prod-extension-secret-0123456789abcdef",
    "EXTENSION_API_KEY": "prod-extension-api-key-0123456789abcdef",
}


def _load_medusa_config_for_contract(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Execute the actual stdlib-only owner in the lean deployment test.

    The configuration package initializer imports optional application
    dependencies. Isolate that package boundary, not the Medusa loader or
    its validation. Restore the canonical module after each test.
    """
    name = "ai_karen_engine.config.agent_medusa"
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/config/agent_medusa.py"
    )
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _set_safe_production_environment(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
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
    monkeypatch.setenv("KAREN_MEDUSA_DISTRIBUTED_RUN_CONTROL_ENABLED", "true")
    monkeypatch.setenv("KAREN_MEDUSA_DURABLE_RUN_LEDGER_ENABLED", "true")
    monkeypatch.setenv("KAREN_MEDUSA_DURABLE_RUN_LEDGER_REQUIRED", "true")
    monkeypatch.setenv("KAREN_MEDUSA_DEEPAGENTS_RESEARCH_ENABLED", "false")
    monkeypatch.setenv("KAREN_MEDUSA_DEEPAGENTS_CHECKPOINT_ENABLED", "false")
    return _load_medusa_config_for_contract(monkeypatch)


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
    service._redis_check.assert_awaited_once_with(required=True, durability_required=True)


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
    # This architecture contract is also run by a dependency-light
    # deployment job; only the runtime-health boundary is mocked here.
    # The actual manager import/ping belongs to the full runtime test suite.
    import sys
    from types import ModuleType

    redis_module = ModuleType("ai_karen_engine.platform.memory.redis")
    monkeypatch.setitem(sys.modules, redis_module.__name__, redis_module)

    class Manager:
        is_healthy = AsyncMock(return_value=True)

    manager = Manager()
    redis_module.get_redis_manager = lambda: manager  # type: ignore[attr-defined]
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


def test_server_and_web_consumer_health_projection_share_a_contract() -> None:
    from pathlib import Path

    server = Path("src/ai_karen_engine/server/health_endpoints.py").read_text()
    web = Path("src/ui_launchers/Karen-AI-Theme/src/app/api/health/route.ts").read_text()
    operational = Path("src/ai_karen_engine/core/runtime/operational_health.py").read_text()

    assert "result.as_dict()" in server
    assert 'readiness.status !== \'ready\'' in web
    assert "const components = readiness.components" in web
    assert "components" in operational
    assert ".configuration !== 'ready'" in web
    assert ".database !== 'ready'" in web


def test_redis_remains_required_when_rate_limit_enforcement_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.runtime.operational_health import OperationalHealthService

    monkeypatch.setenv("KARI_ENABLE_MEMORY_SERVICE", "false")
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "true")
    assert OperationalHealthService.redis_required() is True

    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "true")
    assert OperationalHealthService.redis_required() is True

    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    assert OperationalHealthService.redis_required() is False



@pytest.mark.parametrize(("changes", "expected_reason"), [
    ({}, None),
    ({"status": "partial"}, "redis_durability_evidence_incomplete"),
    ({"status": "unavailable"}, "redis_durability_evidence_incomplete"),
    ({"maxmemory_policy": "volatile-lru"}, "redis_eviction_policy_unsafe"),
    ({"maxmemory_policy": "allkeys-lru"}, "redis_eviction_policy_unsafe"),
    ({"aof_enabled": False}, "redis_aof_disabled"),
    ({"appendfsync": "everysec"}, "redis_fsync_policy_unsafe"),
    ({"appendfsync": "no"}, "redis_fsync_policy_unsafe"),
    ({"aof_write_ok": False}, "redis_aof_write_unhealthy"),
])
def test_redis_durability_readiness_classification(changes, expected_reason):
    evidence = {
        "status": "observed",
        "maxmemory_policy": "noeviction",
        "aof_enabled": True,
        "appendfsync": "always",
        "aof_write_ok": True,
        "used_memory_bytes": 123456789,
    }
    evidence.update(changes)
    result = OperationalHealthService._redis_durability_result(
        SimpleNamespace(**evidence),
    )
    assert result["ready"] is (expected_reason is None)
    if expected_reason is None:
        assert result["durability_status"] == "configuration_verified"
    else:
        assert result["reason"] == expected_reason
    assert "123456789" not in repr(result)


@pytest.mark.asyncio
async def test_production_distributed_readiness_requires_redis_even_without_memory(
    monkeypatch,
):
    agent_medusa = _set_safe_production_environment(monkeypatch)
    for name in ("KARI_ENABLE_MEMORY_SERVICE", "ENABLE_RATE_LIMITING", "AUTH_ENABLE_RATE_LIMITING"):
        monkeypatch.setenv(name, "false")
    service = OperationalHealthService()
    redis_check = AsyncMock(return_value={"ready": False, "status": "durability_unsafe"})
    monkeypatch.setattr(service, "_database_check", AsyncMock(return_value={"ready": True}))
    monkeypatch.setattr(service, "_redis_check", redis_check)
    result = await service.readiness(environment="production")
    assert result.ready is False
    assert result.as_dict()["components"]["redis"] == "not_ready"
    redis_check.assert_awaited_once_with(required=True, durability_required=True)
    assert service.redis_lifecycle_enabled(environment="production") is True

    monkeypatch.setenv("KAREN_MEDUSA_DISTRIBUTED_RUN_CONTROL_ENABLED", "false")
    monkeypatch.setattr(agent_medusa, "_SETTINGS", None)
    redis_check.reset_mock()
    redis_check.return_value = {"ready": True, "status": "not_required"}
    assert (await service.readiness(environment="production")).ready is True
    redis_check.assert_awaited_once_with(required=False)


@pytest.mark.asyncio
async def test_invalid_medusa_configuration_never_waives_durability(monkeypatch):
    _set_safe_production_environment(monkeypatch)
    service = OperationalHealthService()
    monkeypatch.setenv(
        "KAREN_MEDUSA_DISTRIBUTED_RUN_CONTROL_ENABLED", "private configuration content",
    )
    monkeypatch.setattr(service, "_database_check", AsyncMock(return_value={"ready": True}))
    redis_check = AsyncMock(return_value={"ready": True, "status": "healthy"})
    monkeypatch.setattr(service, "_redis_check", redis_check)
    result = await service.readiness(environment="production")
    assert not result.ready
    assert "medusa_runtime_settings=invalid_or_unavailable" in result.checks["configuration"]["violations"]
    assert "private configuration content" not in repr(result)
    redis_check.assert_awaited_once_with(required=True, durability_required=True)


@pytest.mark.asyncio
async def test_required_durability_uses_live_manager_and_propagates_cancellation(monkeypatch):
    import sys
    from types import ModuleType

    module = ModuleType("ai_karen_engine.platform.memory.redis")
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=True),
        observe_durability=AsyncMock(return_value=SimpleNamespace(status="partial")),
    )
    module.get_redis_manager = lambda: manager
    monkeypatch.setitem(sys.modules, module.__name__, module)

    result = await OperationalHealthService._redis_check(required=False, durability_required=True)
    assert not result["ready"]
    manager.is_healthy.assert_awaited_once()
    manager.observe_durability.assert_awaited_once()
    manager.is_healthy.return_value = False
    manager.observe_durability.reset_mock()
    assert not (await OperationalHealthService._redis_check(
        required=True, durability_required=True,
    ))["ready"]
    manager.observe_durability.assert_not_awaited()
    manager.is_healthy.return_value = True
    manager.observe_durability.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await OperationalHealthService._redis_check(required=True, durability_required=True)
