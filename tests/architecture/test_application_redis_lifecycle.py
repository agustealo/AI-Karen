"""Production Redis lifecycle is attached once by the canonical ASGI lifespan."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.config import runtime as runtime_config
from ai_karen_engine.core.runtime.operational_health import OperationalHealthService
from ai_karen_engine.server import application_runtime


def _redis_module(monkeypatch: pytest.MonkeyPatch, manager: object):
    """Inject the one canonical registry boundary without requiring live Redis."""
    module = ModuleType("ai_karen_engine.platform.memory.redis")
    module.get_redis_manager = lambda: manager
    module.shutdown_redis_manager = AsyncMock()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def _required(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(runtime_config, "get_runtime_settings", lambda: runtime_config.RuntimeSettings())
    monkeypatch.setattr(
        OperationalHealthService, "redis_required",
        classmethod(lambda cls: enabled),
    )


@pytest.mark.asyncio
async def test_lifespan_initializes_existing_redis_once_then_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _required(monkeypatch, True)
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=False),
        initialize=AsyncMock(return_value=True),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace())

    await application_runtime.initialize_application_redis(app)
    await application_runtime.initialize_application_redis(app)

    assert app.state.redis_connection_manager is manager
    assert app.state._canonical_redis_lifespan_owned is True
    manager.is_healthy.assert_awaited_once()
    manager.initialize.assert_awaited_once()

    await application_runtime.shutdown_application_redis(app)
    await application_runtime.shutdown_application_redis(app)
    module.shutdown_redis_manager.assert_awaited_once()
    assert app.state.redis_connection_manager is None
    assert app.state._canonical_redis_lifespan_owned is False


@pytest.mark.asyncio
async def test_healthy_canonical_redis_is_reused_without_second_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _required(monkeypatch, True)
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=True),
        initialize=AsyncMock(return_value=True),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace())

    await application_runtime.initialize_application_redis(app)

    assert app.state.redis_connection_manager is manager
    manager.initialize.assert_not_awaited()
    await application_runtime.shutdown_application_redis(app)
    module.shutdown_redis_manager.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_disabled_does_not_initialize_or_close_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _required(monkeypatch, False)
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=True),
        initialize=AsyncMock(),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace())

    await application_runtime.initialize_application_redis(app)
    await application_runtime.shutdown_application_redis(app)

    manager.is_healthy.assert_not_awaited()
    manager.initialize.assert_not_awaited()
    module.shutdown_redis_manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_redis_connection_never_claims_success_or_leaks_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    _required(monkeypatch, True)
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=False),
        initialize=AsyncMock(
            side_effect=ConnectionError("redis://:do-not-log@red-private:6379"),
        ),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace())

    await application_runtime.initialize_application_redis(app)
    assert app.state._canonical_redis_lifespan_owned is True
    assert "do-not-log" not in caplog.text
    assert "startup degraded" in caplog.text

    await application_runtime.shutdown_application_redis(app)
    module.shutdown_redis_manager.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_closes_redis_and_database_when_runtime_attachment_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_startup = ModuleType("ai_karen_engine.server.startup")
    server_startup.on_startup = AsyncMock()
    server_startup.on_shutdown = AsyncMock()
    monkeypatch.setitem(sys.modules, server_startup.__name__, server_startup)

    init_redis = AsyncMock()
    init_runtime = AsyncMock(side_effect=RuntimeError("runtime failed"))
    stop_runtime = AsyncMock()
    stop_redis = AsyncMock()
    monkeypatch.setattr(application_runtime, "initialize_application_redis", init_redis)
    monkeypatch.setattr(application_runtime, "initialize_application_runtime", init_runtime)
    monkeypatch.setattr(application_runtime, "shutdown_application_runtime", stop_runtime)
    monkeypatch.setattr(application_runtime, "shutdown_application_redis", stop_redis)

    app = SimpleNamespace(state=SimpleNamespace())
    lifecycle = application_runtime.create_application_lifespan(object())
    with pytest.raises(RuntimeError, match="runtime failed"):
        async with lifecycle(app):
            pytest.fail("Startup failure must not yield a request-ready app")

    server_startup.on_startup.assert_awaited_once()
    init_redis.assert_awaited_once_with(app)
    init_runtime.assert_awaited_once_with(app)
    stop_runtime.assert_awaited_once_with(app)
    stop_redis.assert_awaited_once_with(app)
    server_startup.on_shutdown.assert_awaited_once_with(app)


def test_redis_policy_matches_readiness_and_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    # One Redis authority governs both runtime initialization and /ready.
    # Disabling memory alone must not disable Redis while a security limiter
    # still depends on it.
    monkeypatch.setenv("KARI_ENABLE_MEMORY_SERVICE", "false")
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "false")
    assert OperationalHealthService.redis_required() is False

    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "true")
    assert OperationalHealthService.redis_required() is True
    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "true")
    assert OperationalHealthService.redis_required() is True

    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("KARI_ENABLE_MEMORY_SERVICE", "true")
    assert OperationalHealthService.redis_required() is True
    monkeypatch.delenv("KARI_ENABLE_MEMORY_SERVICE", raising=False)
    assert OperationalHealthService.redis_required() is True


@pytest.mark.parametrize("producer,wait,healthy", [
    (False, False, True),
    (True, False, True),
    (True, True, True),
    (True, True, False),
])
@pytest.mark.asyncio
async def test_optional_invalidation_owns_redis_without_promoting_readiness(
    monkeypatch: pytest.MonkeyPatch, producer: bool, wait: bool, healthy: bool,
) -> None:
    for name in ("KARI_ENABLE_MEMORY_SERVICE", "ENABLE_RATE_LIMITING", "AUTH_ENABLE_RATE_LIMITING"):
        monkeypatch.setenv(name, "false")
    settings = runtime_config.RuntimeSettings()
    settings.features.enable_communications_invalidation = producer
    settings.features.enable_communications_invalidation_wait = wait
    monkeypatch.setattr(runtime_config, "get_runtime_settings", lambda: settings)
    assert OperationalHealthService.redis_required() is False
    assert OperationalHealthService.redis_lifecycle_enabled() is producer

    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=False),
        initialize=AsyncMock(return_value=healthy),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace())
    await application_runtime.initialize_application_redis(app)
    await application_runtime.initialize_application_redis(app)
    if producer:
        assert app.state.redis_connection_manager is manager
        assert app.state._canonical_redis_lifespan_owned is True
        manager.is_healthy.assert_awaited_once()
        manager.initialize.assert_awaited_once()
    else:
        manager.is_healthy.assert_not_awaited()
        manager.initialize.assert_not_awaited()

    # Exercise the real readiness composition, not just the policy predicate.
    # Database is independently healthy; optional Redis must not gate it.
    health = OperationalHealthService()
    monkeypatch.setattr(health, "_database_check", AsyncMock(return_value={"ready": True}))
    result = await health.readiness(environment="development")
    assert result.ready is True
    assert result.checks["redis"] == {"ready": True, "status": "not_required"}
    if producer:
        manager.is_healthy.assert_awaited_once()
    else:
        manager.is_healthy.assert_not_awaited()
    await application_runtime.shutdown_application_redis(app)
    await application_runtime.shutdown_application_redis(app)
    if producer:
        module.shutdown_redis_manager.assert_awaited_once()
        assert app.state.redis_connection_manager is None
    else:
        module.shutdown_redis_manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_required_redis_still_gates_readiness_with_invalidation_enabled(monkeypatch):
    monkeypatch.setenv("KARI_ENABLE_MEMORY_SERVICE", "false")
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "true")
    settings = runtime_config.RuntimeSettings()
    settings.features.enable_communications_invalidation = True
    monkeypatch.setattr(runtime_config, "get_runtime_settings", lambda: settings)
    manager = SimpleNamespace(is_healthy=AsyncMock(return_value=False))
    _redis_module(monkeypatch, manager)
    health = OperationalHealthService()
    monkeypatch.setattr(health, "_database_check", AsyncMock(return_value={"ready": True}))
    assert OperationalHealthService.redis_required() is True
    assert OperationalHealthService.redis_lifecycle_enabled() is True
    result = await health.readiness(environment="development")
    assert result.ready is False
    assert result.checks["redis"] == {"ready": False, "status": "degraded"}
    manager.is_healthy.assert_awaited_once()



@pytest.mark.asyncio
async def test_production_distributed_coordination_attaches_canonical_redis_without_other_consumers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config import agent_medusa

    _required(monkeypatch, False)
    monkeypatch.setattr(
        agent_medusa, "get_agent_medusa_runtime_settings",
        lambda: agent_medusa.AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=True,
            run_redis_admission_reserve_bytes=16777216,
        ),
    )
    manager = SimpleNamespace(
        is_healthy=AsyncMock(return_value=False),
        initialize=AsyncMock(return_value=True),
    )
    module = _redis_module(monkeypatch, manager)
    app = SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(environment="production"),
    ))
    await application_runtime.initialize_application_redis(app)
    assert app.state.redis_connection_manager is manager
    manager.initialize.assert_awaited_once()
    await application_runtime.shutdown_application_redis(app)
    module.shutdown_redis_manager.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "prod"])
async def test_production_lifespan_rejects_cached_zero_reserve_before_startup(
    monkeypatch: pytest.MonkeyPatch, environment: str,
) -> None:
    from ai_karen_engine.config import agent_medusa

    server_startup = ModuleType("ai_karen_engine.server.startup")
    server_startup.on_startup = AsyncMock()
    server_startup.on_shutdown = AsyncMock()
    monkeypatch.setitem(sys.modules, server_startup.__name__, server_startup)
    monkeypatch.setattr(agent_medusa, "_SETTINGS", agent_medusa.AgentMedusaRuntimeSettings())
    settings = SimpleNamespace(environment=environment)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    lifecycle = application_runtime.create_application_lifespan(settings)
    with pytest.raises(agent_medusa.AgentMedusaConfigError, match="must be positive"):
        async with lifecycle(app):
            pytest.fail("Unsafe production configuration must not yield readiness")
    server_startup.on_startup.assert_not_awaited()
    server_startup.on_shutdown.assert_not_awaited()
