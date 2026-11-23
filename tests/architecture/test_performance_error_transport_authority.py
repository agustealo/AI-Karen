from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import StatementError


SECRET = "PRIVATE_PERFORMANCE_BOUND_PARAMETER"
ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE = ROOT / "src/ai_karen_engine/api_routes/monitoring/performance.py"


def _private_error() -> StatementError:
    return StatementError(
        "operation unavailable",
        "SELECT * FROM private_metrics WHERE token=:secret",
        {"secret": SECRET},
        RuntimeError("private database driver"),
    )


def _app() -> FastAPI:
    from ai_karen_engine.api_routes.monitoring import performance

    app = FastAPI()
    app.include_router(performance.router)
    return app


def _assert_no_secret(response, caplog: pytest.LogCaptureFixture) -> None:
    for value in (SECRET, "token=:secret", "private database driver"):
        assert value not in response.text + caplog.text
    assert all(
        record.exc_info is None for record in caplog.records
        if record.name == "ai_karen_engine.api_routes.monitoring.performance"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/performance/dashboard", None),
        ("GET", "/api/performance/metrics", None),
        ("POST", "/api/performance/metrics", {
            "name": "requests", "value": 1.0, "service_name": "api",
            "metric_type": "counter",
        }),
    ],
)
async def test_performance_http_errors_redact_sql(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
    payload: dict | None,
) -> None:
    from ai_karen_engine.api_routes.monitoring import performance

    error = _private_error()
    system = SimpleNamespace(
        get_dashboard_data=AsyncMock(side_effect=error),
        storage=SimpleNamespace(
            get_metrics=AsyncMock(side_effect=error),
            store_metric=AsyncMock(side_effect=error),
        ),
    )
    monkeypatch.setattr(performance, "get_performance_monitoring_system", lambda: system)
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=_app(), raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            result = await client.request(method, path, json=payload)

    assert result.status_code == 500
    assert result.json()["detail"] == "Performance operation unavailable"
    _assert_no_secret(result, caplog)


def _optimized_module(monkeypatch: pytest.MonkeyPatch, **values: object) -> None:
    module = ModuleType("ai_karen_engine.server.optimized_startup")
    for key in (
        "get_lifecycle_manager",
        "get_resource_monitor",
        "get_performance_metrics",
        "get_lazy_controller",
        "get_task_orchestrator",
        "get_gpu_offloader",
        "get_classified_registry",
    ):
        setattr(module, key, values.get(key, lambda: None))
    monkeypatch.setitem(sys.modules, module.__name__, module)


@pytest.mark.asyncio
async def test_optimization_status_preserves_partial_failure_without_raw_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ai_karen_engine.api_routes.monitoring import performance
    from ai_karen_engine.config import performance_config

    _optimized_module(monkeypatch, get_resource_monitor=lambda: SimpleNamespace(
        get_current_metrics=lambda: (_ for _ in ()).throw(_private_error())
    ))
    config = SimpleNamespace(
        enable_performance_optimization=True,
        deployment_mode="production",
        to_dict=lambda: {"enabled": True},
    )
    monkeypatch.setattr(performance_config, "get_performance_config", lambda: config)
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=_app(), raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            result = await client.get("/api/performance/optimization/status")
    assert result.status_code == 200
    body = result.json()
    assert body["optimization_enabled"] is True
    assert body["resource_usage"] == {"error": "Performance operation unavailable"}
    _assert_no_secret(result, caplog)


@pytest.mark.asyncio
async def test_optimization_status_outer_failure_reports_unavailability_without_private_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    def raise_sql():
        raise _private_error()
    _optimized_module(monkeypatch, get_lifecycle_manager=raise_sql)
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=_app(), raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/performance/optimization/status")
    assert response.status_code == 200
    assert response.json() == {
        "error": "Performance operation unavailable",
        "optimization_enabled": False,
    }
    _assert_no_secret(response, caplog)


@pytest.mark.asyncio
async def test_partial_optimization_service_failure_does_not_leak_sql(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Registry:
        async def get_services_by_classification(self, classification: str):
            if classification == "optional":
                raise _private_error()
            return {"worker": SimpleNamespace(status="ready")}

    _optimized_module(monkeypatch, get_classified_registry=lambda: Registry())
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=_app(), raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/performance/optimization/services")
    assert response.status_code == 200
    assert response.json()["services_by_classification"]["optional"] == {
        "error": "Performance operation unavailable"
    }
    _assert_no_secret(response, caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "expected_status", "expected_detail"),
    [
        ("/api/performance/optimization/config", 503, "Performance configuration not loaded"),
        ("/api/performance/optimization/trigger", 503, "Performance optimization not enabled or not available"),
        ("/api/performance/optimization/services", 503, "Classified service registry not available"),
    ],
)
async def test_expected_unavailable_conditions_keep_http_503(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    expected_status: int,
    expected_detail: str,
) -> None:
    from ai_karen_engine.config import performance_config

    _optimized_module(monkeypatch)
    monkeypatch.setattr(performance_config, "get_performance_config", lambda: None)
    method = "POST" if endpoint.endswith("/trigger") else "GET"
    async with AsyncClient(
        transport=ASGITransport(app=_app(), raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        result = await client.request(method, endpoint)
    assert result.status_code == expected_status
    assert result.json()["detail"] == expected_detail


@pytest.mark.asyncio
async def test_invalid_optimization_config_keeps_http_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config import performance_config

    manager = SimpleNamespace(update_config=AsyncMock(return_value=False))
    monkeypatch.setattr(
        performance_config,
        "get_performance_config_manager",
        lambda: manager,
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(), raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/performance/optimization/config", json={"deployment_mode": "bad"}
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to update configuration - validation failed"
    manager.update_config.assert_awaited_once_with({"deployment_mode": "bad"})


def test_performance_ingress_contains_no_exception_string_transport() -> None:
    source = PERFORMANCE.read_text(encoding="utf-8")
    parsed = ast.parse(source, filename=str(PERFORMANCE))
    assert isinstance(parsed, ast.Module)
    assert "detail=str(e)" not in source
    assert '"error": str(e)' not in source
    assert 'logger.error(f"' not in source
    assert "traceback.format_exc" not in source
