"""Planner direct execution must not read private records without runtime authority."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def _request(authenticated=True):
    principal = UserData(user_id="user-a", tenant_id="tenant-a", roles=["user"]) if authenticated else None
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "list my tasks"}],
        context=ChatExecutionContext(
            user_id="user-a", tenant_id="tenant-a", request_id="request-1",
            correlation_id="corr-1", authenticated_user=principal,
        ),
    )


@pytest.mark.asyncio
async def test_planner_denied_plan_cannot_call_service(monkeypatch):
    import ai_karen_engine.config.runtime as settings_module
    import ai_karen_engine.services.personal_planner as planner_module

    monkeypatch.setattr(settings_module, "get_runtime_settings",
                        lambda: SimpleNamespace(enable_personal_planner_read_api=True))
    service = AsyncMock()
    monkeypatch.setattr(planner_module, "PersonalPlannerService", lambda: service)
    result = await DirectCapabilityExecutor().execute(
        request=_request(),
        decision=SimpleNamespace(intent="planner.read"),
        plan=SimpleNamespace(allowed_capabilities=[]),
        meter=SimpleNamespace(consume_tool_call=AsyncMock(return_value=True)),
    )
    assert not result.success
    assert result.error == "planner_read_not_authorized"
    service.list_presentation.assert_not_awaited()


@pytest.mark.asyncio
async def test_planner_missing_principal_denied_before_read(monkeypatch):
    import ai_karen_engine.config.runtime as settings_module
    import ai_karen_engine.services.personal_planner as planner_module

    monkeypatch.setattr(settings_module, "get_runtime_settings",
                        lambda: SimpleNamespace(enable_personal_planner_read_api=True))
    service = AsyncMock()
    monkeypatch.setattr(planner_module, "PersonalPlannerService", lambda: service)
    result = await DirectCapabilityExecutor().execute(
        request=_request(authenticated=False),
        decision=SimpleNamespace(intent="planner.read"),
        plan=SimpleNamespace(allowed_capabilities=["planner.read"]),
        meter=SimpleNamespace(consume_tool_call=AsyncMock(return_value=True)),
    )
    assert not result.success
    assert result.error == "PermissionError"
    service.list_presentation.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorized_planner_read_returns_real_service_envelope(monkeypatch):
    import ai_karen_engine.config.runtime as settings_module
    import ai_karen_engine.services.personal_planner as planner_module

    monkeypatch.setattr(settings_module, "get_runtime_settings",
                        lambda: SimpleNamespace(enable_personal_planner_read_api=True))
    envelope = {
        "schema_version": 1, "presentation_id": "planner-corr-1",
        "component_type": "planner.task_list",
        "evidence_ref": "planner-owned-read:corr-1",
        "data": {"tasks": [{"id": "id-1", "title": "Review release", "status": "todo"}]},
    }
    service = SimpleNamespace(list_presentation=AsyncMock(
        return_value={"presentation": envelope, "empty": False},
    ))
    monkeypatch.setattr(planner_module, "PersonalPlannerService", lambda: service)
    result = await DirectCapabilityExecutor().execute(
        request=_request(),
        decision=SimpleNamespace(intent="planner.read"),
        plan=SimpleNamespace(allowed_capabilities=["planner.read"]),
        meter=SimpleNamespace(consume_tool_call=AsyncMock(return_value=True)),
    )
    assert result.success
    assert result.source == "planner"
    assert result.payload["presentation"] == envelope
    assert "Review release" not in result.text
    service.list_presentation.assert_awaited_once()
