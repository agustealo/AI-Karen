"""Time Query consumer API ingress contract using real extension handlers.

This tests API response mapping and request identity propagation. It does not
claim browser verification or replace runtime-policy authorization tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request

from ai_karen_engine.api_routes.plugins import plugins as routes
from ai_karen_engine.extensions.platform.core.host.loader import ExtensionLoader
from ai_karen_engine.services.plugin_service import ExecutionStatus


def _request() -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/plugins/time-query/execute",
        "raw_path": b"/api/plugins/time-query/execute",
        "query_string": b"",
        "headers": [(b"x-request-id", b"request-clock-1"),
                    (b"x-correlation-id", b"correlation-clock-1")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "result_field"),
    [
        ({"mode": "multi_clock", "action": "list"}, "clocks"),
        ({"mode": "alarm", "action": "list"}, "alarms"),
    ],
)
async def test_time_query_execute_ingress_returns_real_handler_payload(
    monkeypatch: pytest.MonkeyPatch,
    parameters: dict[str, str],
    result_field: str,
) -> None:
    import ai_karen_engine.extensions.plugin_kernel as kernel

    directory = Path(kernel.__file__).resolve().parent / "plugins" / "time-query"
    handler_module = ExtensionLoader._import_handler(directory)
    seen: list[dict] = []

    class RecordingService:
        async def execute_plugin(self, **kwargs):
            seen.append(kwargs)
            payload = await handler_module.TimeQueryExtension.run(
                None, kwargs["parameters"]
            )
            return SimpleNamespace(
                status=ExecutionStatus.COMPLETED,
                result=payload,
                error=None,
                execution_time=0.0,
                completed_at=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(routes, "_permission_values", lambda user: ["read"])
    response = await routes._execute(
        "time-query",
        routes.ExecutePluginRequest(
            plugin_name="time-query", parameters=parameters
        ),
        _request(),
        {
            "user_id": "user-time-query",
            "tenant_id": "tenant-time-query",
            "roles": ["user"],
        },
        RecordingService(),
    )
    assert response.success is True
    assert response.plugin_name == "time-query"
    assert response.result["status"] == "success"
    assert isinstance(response.result[result_field], list)
    assert len(seen) == 1
    assert seen[0]["parameters"] == parameters
    assert seen[0]["user_id"] == "user-time-query"
    assert seen[0]["tenant_id"] == "tenant-time-query"
    assert seen[0]["correlation_id"] == "correlation-clock-1"
