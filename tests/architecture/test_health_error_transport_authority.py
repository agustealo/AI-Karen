from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import StatementError


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", (True, False))
async def test_public_health_uses_real_readiness_projection(
    monkeypatch: pytest.MonkeyPatch, ready: bool,
) -> None:
    from ai_karen_engine.api_routes.public import public
    from ai_karen_engine.core.runtime.operational_health import OperationalHealthResult

    result = OperationalHealthResult(
        status="ready" if ready else "not_ready", ready=ready,
        checks={
            "configuration": {"ready": True, "violations": ["SECRET_VALUE_NEVER_EXPOSE"]},
            "database": {"ready": ready, "error": "PRIVATE_DB_PASSWORD"},
            "redis": {"ready": ready, "error": "PRIVATE_REDIS_PASSWORD"},
        },
        timestamp=123.0,
    )
    service = SimpleNamespace(readiness=AsyncMock(return_value=result))
    monkeypatch.setattr(public, "get_operational_health_service", lambda: service)
    app = FastAPI()
    app.state.settings = SimpleNamespace(environment="production")
    app.include_router(public.router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get("/api/public/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == ("healthy" if ready else "degraded")
    assert body["services"]["api"] == "operational"
    assert body["services"]["database"] == ("ready" if ready else "not_ready")
    assert body["services"]["redis"] == ("ready" if ready else "not_ready")
    assert "authentication" not in body["services"]
    assert "2025-08-25" not in response.text
    datetime.fromisoformat(body["timestamp"]).astimezone(timezone.utc)
    for sensitive in ("PRIVATE_DB_PASSWORD", "PRIVATE_REDIS_PASSWORD", "SECRET_VALUE_NEVER_EXPOSE"):
        assert sensitive not in response.text
    service.readiness.assert_awaited_once_with(environment="production")


@pytest.mark.asyncio
async def test_public_health_does_not_fabricate_ready_or_leak_sql_exceptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from ai_karen_engine.api_routes.public import public

    secret = "SENSITIVE_PUBLIC_BOUND_PARAMETER"
    sql = StatementError(
        "private", "SELECT :private", {"private": secret}, RuntimeError("private driver"),
    )
    service = SimpleNamespace(readiness=AsyncMock(side_effect=sql))
    monkeypatch.setattr(public, "get_operational_health_service", lambda: service)
    app = FastAPI()
    app.include_router(public.router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        missing = await client.get("/api/public/health")
    assert missing.status_code == 200
    assert missing.json()["status"] == "degraded"
    assert missing.json()["services"]["readiness"] == "unavailable"
    service.readiness.assert_not_awaited()

    app.state.settings = SimpleNamespace(environment="production")
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            failed = await client.get("/api/public/health")
    assert failed.status_code == 200
    assert failed.json()["status"] == "degraded"
    assert failed.json()["message"] == "Runtime readiness unavailable"
    assert secret not in failed.text + caplog.text
    assert "SELECT :private" not in failed.text + caplog.text
    assert "private driver" not in failed.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.name == public.__name__)


@pytest.mark.asyncio
async def test_public_health_install_route_is_disabled_without_running_downloads() -> None:
    from ai_karen_engine.api_routes.monitoring import health

    app = FastAPI()
    app.include_router(health.router)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/health/nlp-assets/install")
    assert response.status_code == 403
    assert response.json()["detail"] == "NLP asset installation requires trusted provisioning"
    assert "_install_nlp_assets" not in (
        __import__("inspect").getsource(health)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ("/health/extensions", "/health/extensions/widget"))
async def test_extension_health_failures_do_not_reflect_bound_sql(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    path: str,
) -> None:
    from ai_karen_engine.api_routes.monitoring import health
    from ai_karen_engine.extensions import health as extension_health

    secret = "PRIVATE_EXTENSION_BOUND_SQL_PARAMETER"
    sql = StatementError(
        "private", "SELECT :private", {"private": secret}, RuntimeError("private SQL driver"),
    )
    monitor = SimpleNamespace(
        get_extension_health_for_api=AsyncMock(side_effect=sql),
        check_extension_system_health=AsyncMock(side_effect=sql),
    )
    monkeypatch.setattr(extension_health, "get_extension_health_monitor", lambda: monitor)
    monkeypatch.setattr(
        health, "get_structured_logging_service",
        lambda: SimpleNamespace(log_api_request=lambda **_kwargs: None),
    )
    app = FastAPI()
    app.include_router(health.router)
    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["error"] == "Extension health unavailable"
    for sensitive in (secret, "SELECT :private", "private SQL driver"):
        assert sensitive not in response.text + caplog.text


@pytest.mark.asyncio
async def test_extension_health_success_projections_hide_stored_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.extensions.health import ExtensionHealthMonitor

    secret = "PRIVATE_EXTENSION_STORED_ERROR"
    metrics = SimpleNamespace(
        health=SimpleNamespace(value="unhealthy"),
        response_time_ms=20.0, uptime_seconds=50.0, error_count=3,
        success_count=1, background_tasks_active=0, background_tasks_failed=0,
        last_check=datetime.now(timezone.utc), error=secret,
    )
    data = SimpleNamespace(
        overall_status=SimpleNamespace(value="unhealthy"),
        timestamp=datetime.now(timezone.utc), system_uptime_seconds=30.0,
        total_extensions=1, healthy_extensions=0, degraded_extensions=0,
        unhealthy_extensions=1, extension_metrics={"widget": metrics},
        authentication_healthy=False, database_healthy=False,
        background_tasks_healthy=False,
    )
    monitor = ExtensionHealthMonitor.__new__(ExtensionHealthMonitor)
    monitor.check_extension_system_health = AsyncMock(return_value=data)
    response = await monitor.get_extension_health_for_api()
    assert response["extensions"]["details"]["widget"]["error"] == "Extension health check failed"
    assert secret not in repr(response)


@pytest.mark.asyncio
async def test_service_health_failure_does_not_reflect_sql_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.api_routes.monitoring import health

    secret = "PRIVATE_SERVICE_HEALTH_BOUND_VALUE"
    failure = StatementError(
        "private", "SELECT :private", {"private": secret}, RuntimeError("private driver"),
    )
    fake = SimpleNamespace(check_service_health=AsyncMock(side_effect=failure))
    monkeypatch.setattr(health, "get_connection_health_manager", lambda: fake)
    monkeypatch.setattr(
        health, "get_structured_logging_service",
        lambda: SimpleNamespace(log_api_request=lambda **_kwargs: None),
    )
    app = FastAPI()
    app.include_router(health.router)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/dependency")
    assert response.status_code == 200
    assert response.json()["result"] == {
        "status": "unknown", "error": "Health check unavailable",
    }
    assert secret not in response.text



@pytest.mark.asyncio
async def test_individual_extension_health_uses_canonical_health_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.api_routes.monitoring import health
    from ai_karen_engine.extensions import health as extension_health

    secret = "PRIVATE_HEALTH_RECORD_ERROR"
    metrics = SimpleNamespace(
        health=SimpleNamespace(value="degraded"),
        response_time_ms=12.0, uptime_seconds=50.0, error_count=2,
        success_count=3, background_tasks_active=0, background_tasks_failed=1,
        api_calls_per_minute=0.0, memory_usage_mb=10.0, cpu_usage_percent=1.0,
        last_check=None, error=secret,
    )
    monitor = SimpleNamespace(
        check_extension_system_health=AsyncMock(
            return_value=SimpleNamespace(extension_metrics={"widget": metrics})
        ),
    )
    monkeypatch.setattr(extension_health, "get_extension_health_monitor", lambda: monitor)
    monkeypatch.setattr(
        health, "get_structured_logging_service",
        lambda: SimpleNamespace(log_api_request=lambda **_kwargs: None),
    )
    app = FastAPI()
    app.include_router(health.router)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/extensions/widget")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["last_check"] is None
    assert response.json()["error"] == "Extension health check failed"
    assert secret not in response.text
