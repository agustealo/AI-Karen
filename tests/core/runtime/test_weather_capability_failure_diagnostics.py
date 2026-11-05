"""Direct live capability failures must be truthful and diagnosable."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def test_weather_plan_denial_does_not_claim_provider_outage():
    result = DirectCapabilityExecutor()._unavailable(
        0.0,
        "web.search",
        "web_search",
        "not_in_authorized_plan",
        [{"type": "tool", "id": "web_search", "status": "skipped", "error": "not_in_authorized_plan"}],
    )
    assert not result.success
    assert result.degraded
    assert "not authorized" in result.text
    assert result.payload["next_action"] == "inspect_authorized_execution_plan"
    assert result.attempts[0]["error"] == "not_in_authorized_plan"


def test_weather_provider_failure_does_not_blame_permissions():
    result = DirectCapabilityExecutor()._unavailable(
        0.0,
        "web.search",
        "web_search",
        "capability_returned_no_live_data",
        [{"type": "tool", "id": "web_search", "status": "failed", "error": "capability_returned_no_live_data"}],
    )
    assert "provider failed or returned no usable result" in result.text
    assert result.payload["next_action"] == "inspect_provider_attempts"
    assert not result.success


def test_weather_unconfigured_path_is_distinct_from_denial():
    result = DirectCapabilityExecutor()._unavailable(
        0.0, "web.search", "web_search", "not available", [],
    )
    assert "No executable live capability" in result.text
    assert result.payload["next_action"] == "inspect_capability_registration"



def _weather_execution_context():
    """Only runtime ownership; no real network or user data."""
    request = SimpleNamespace(
        context=SimpleNamespace(
            request_id="req-weather-failure", correlation_id="corr-weather-failure",
            user_id="user-a", tenant_id="tenant-a", session_id="session-a",
            conversation_id="conversation-a", roles=[], permissions=[],
        ),
        metadata={},
        messages=[{"role": "user", "content": "What's the weather in Detroit?"}],
    )
    decision = SimpleNamespace(intent="search.weather")
    plan = SimpleNamespace(
        policy_decision_id="policy-decision-a",
        allowed_tools=["web_search"],
        allowed_plugins=["intelligent-search"],
        allowed_capabilities=["web.search"],
    )
    meter = SimpleNamespace(consume_tool_call=AsyncMock(return_value=True))
    return request, decision, plan, meter


@pytest.mark.asyncio
async def test_weather_tool_exception_falls_back_only_to_authorized_plugin(monkeypatch, caplog):
    from ai_karen_engine.core.runtime import direct_capability_executor as module

    request, decision, plan, meter = _weather_execution_context()
    monkeypatch.setattr(
        module.ActionExecutionGate, "authorize", AsyncMock(return_value=True),
    )
    tool = SimpleNamespace(execute_tool=AsyncMock(side_effect=RuntimeError("PRIVATE PROVIDER TOKEN")))
    plugin = SimpleNamespace(execute_plugin=AsyncMock(return_value=SimpleNamespace(
        status=module.ExecutionStatus.COMPLETED,
        error=None,
        result={
            "status": "ok",
            "extractedData": {
                "location": "Detroit, Michigan",
                "temperature": "58 °F",
                "observed_at": "2026-11-04T10:00",
            },
        },
    )))
    monkeypatch.setattr(module, "get_tool_service", lambda: tool)
    monkeypatch.setattr(module, "get_plugin_service", lambda: plugin)

    result = await DirectCapabilityExecutor().execute(
        request=request, decision=decision, plan=plan, meter=meter,
    )
    assert result.success
    assert result.source == "plugin"
    assert result.source_id == "intelligent-search"
    assert [(x["type"], x["status"]) for x in result.attempts] == [
        ("tool", "failed"), ("plugin", "success"),
    ]
    assert result.attempts[0]["error"] == "tool_execution_failed"
    assert result.normalized_metadata()["actual_model"] is None
    assert tool.execute_tool.await_count == 1
    assert plugin.execute_plugin.await_count == 1
    assert "PRIVATE PROVIDER TOKEN" not in caplog.text


@pytest.mark.asyncio
async def test_weather_tool_and_plugin_exceptions_return_explicit_degradation(monkeypatch, caplog):
    from ai_karen_engine.core.runtime import direct_capability_executor as module

    request, decision, plan, meter = _weather_execution_context()
    monkeypatch.setattr(
        module.ActionExecutionGate, "authorize", AsyncMock(return_value=True),
    )
    tool = SimpleNamespace(execute_tool=AsyncMock(side_effect=ConnectionError("PRIVATE SECRET")))
    plugin = SimpleNamespace(execute_plugin=AsyncMock(side_effect=TimeoutError("PRIVATE SECRET")))
    monkeypatch.setattr(module, "get_tool_service", lambda: tool)
    monkeypatch.setattr(module, "get_plugin_service", lambda: plugin)

    result = await DirectCapabilityExecutor().execute(
        request=request, decision=decision, plan=plan, meter=meter,
    )
    assert result.handled
    assert result.degraded
    assert not result.success
    assert len(result.attempts) == 2
    assert all(x["status"] == "failed" for x in result.attempts)
    assert {x["error"] for x in result.attempts} == {
        "tool_execution_failed", "plugin_execution_failed",
    }
    assert result.normalized_metadata()["actual_provider"] is None
    assert "PRIVATE SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_weather_exception_never_tries_unauthorized_plugin(monkeypatch):
    from ai_karen_engine.core.runtime import direct_capability_executor as module

    request, decision, plan, meter = _weather_execution_context()
    plan.allowed_plugins = []
    monkeypatch.setattr(
        module.ActionExecutionGate, "authorize", AsyncMock(return_value=True),
    )
    tool = SimpleNamespace(execute_tool=AsyncMock(side_effect=RuntimeError("bad service")))
    plugin = SimpleNamespace(execute_plugin=AsyncMock())
    monkeypatch.setattr(module, "get_tool_service", lambda: tool)
    monkeypatch.setattr(module, "get_plugin_service", lambda: plugin)

    result = await DirectCapabilityExecutor().execute(
        request=request, decision=decision, plan=plan, meter=meter,
    )
    assert not result.success
    assert result.degraded
    assert result.attempts[0]["error"] == "tool_execution_failed"
    assert result.attempts[1]["status"] == "skipped"
    plugin.execute_plugin.assert_not_awaited()
