"""System-wide governed conversational plugin read-action acceptance contracts.

The first installed real action uses Time Query's own manifest declaration.
The runtime contains no Time Query or Telegram special cases.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.cortex.routing_intents import (
    parse_plugin_inspection_request,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.services.plugin_service import (
    ExecutionStatus,
    PluginExecutionResult,
    PluginService,
)


TENANT = "11111111-2222-4333-8444-555555555555"
USER = "66666666-7777-4888-9999-aaaaaaaaaaaa"


def _installed_clock_manifest() -> ExtensionManifest:
    path = PluginKernel.canonical_extensions_root() / "time-query" / "plugin_manifest.json"
    return ExtensionManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _service() -> PluginService:
    manifest = _installed_clock_manifest()
    record = {
        "manifest": manifest, "status": "enabled",
        "is_valid": True, "error_message": None,
    }
    service = object.__new__(PluginService)
    service._get_kernel = lambda: SimpleNamespace(
        get_record=lambda plugin_id: record if plugin_id == "time-query" else None,
        get_channel_activation_manifest=lambda plugin_id: None,
    )
    service.list_plugins = AsyncMock(return_value=[record])
    service._execution_configuration_readiness = AsyncMock(return_value=None)
    service.execute_plugin = AsyncMock()
    return service


def _request(phrase: str = "Use my Time Query plugin to tell me the time") -> ChatExecutionRequest:
    principal = UserData(user_id=USER, tenant_id=TENANT, roles=["user"], permissions=[])
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": phrase}],
        context=ChatExecutionContext(
            user_id=USER, tenant_id=TENANT, session_id="plugin-session",
            request_id="request-action", correlation_id="correlation-action",
            roles=["user"], permissions=[],
            authenticated_user=principal,
        ),
    )


def _plan() -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-inspect", policy_decision_id="policy-inspect",
        authorized_user_id=USER, authorized_tenant_id=TENANT,
        authorized_session_id="plugin-session",
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=["plugin.inspect"],
        budget=ExecutionBudget(
            max_duration_ms=30000, max_tool_calls=4, max_model_calls=0,
        ),
    )


def _meter(plan: AuthorizedExecutionPlan) -> ExecutionBudgetMeter:
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    return meter


def _receipt(request: ChatExecutionRequest) -> PluginExecutionResult:
    return PluginExecutionResult(
        request_id="plugin-request-verified", plugin_name="time-query",
        plugin_id="time-query", status=ExecutionStatus.COMPLETED,
        result={"status": "success", "formatted": "4:21 PM EDT"},
        user_id=USER, tenant_id=TENANT, session_id="plugin-session",
        conversation_id=request.context.conversation_id or "",
        correlation_id="correlation-action",
        policy_decision_id="policy-fresh-plugin-execution",
    )


def test_installed_time_plugin_opts_in_from_its_canonical_manifest():
    manifest = _installed_clock_manifest()
    actions = manifest.governance["conversational_actions"]
    assert actions["version"] == 1
    assert actions["actions"][0]["side_effect_level"] == "none"
    assert actions["actions"][0]["requires_confirmation"] is False
    assert actions["actions"][0]["parameters"] == {"mode": "datetime"}


def test_cortex_keeps_untrusted_goal_separate_from_plugin_parameters():
    parsed = parse_plugin_inspection_request(
        "Use my Time Query plugin to tell me the time"
    )
    assert parsed is not None
    assert parsed.operation == "use"
    assert parsed.target == "Time Query"
    assert parsed.goal == "tell me the time"
    assert parsed.requested_action == "execute"


def test_generic_manifest_read_action_matching_and_unknown_goal():
    service = _service()
    found = service.resolve_conversational_read_action(
        plugin_id="time-query", goal="tell me the time", caller_roles=["user"],
    )
    assert found == {
        "action_id": "clock.current_datetime",
        "parameters": {"mode": "datetime"},
        "authorization_required": "fresh_plugin_execution_policy",
        "manifest_source": "plugin_kernel",
    }
    assert service.resolve_conversational_read_action(
        plugin_id="time-query", goal="publish an article", caller_roles=["user"],
    ) is None
    assert service.resolve_conversational_read_action(
        plugin_id="time-query", goal="tell me the time", caller_roles=["guest"],
    ) is None
    assert service.resolve_conversational_read_action(
        plugin_id="no-such-plugin", goal="tell me the time", caller_roles=["user"],
    ) is None


@pytest.mark.parametrize("invalid", [
    {"side_effect_level": "external"},
    {"requires_confirmation": True},
    {"parameters": {"api_key": "not-allowed"}},
    {"parameters": {"mode": ["datetime"]}},
    {"parameters": {"mode": "x" * 161}},
    {"utterances": []},
    {"side_effect_level": "write"},
])
def test_generic_action_contract_fails_closed_on_unsafe_manifest(invalid):
    service = _service()
    manifest = deepcopy(_installed_clock_manifest())
    action = manifest.governance["conversational_actions"]["actions"][0]
    action.update(invalid)
    service._get_kernel = lambda: SimpleNamespace(
        get_record=lambda plugin_id: {
            "manifest": manifest, "status": "enabled", "is_valid": True,
        },
    )
    assert service.resolve_conversational_read_action(
        plugin_id="time-query", goal="tell me the time", caller_roles=["user"],
    ) is None


def test_duplicate_declared_utterances_do_not_pick_arbitrary_plugin_action():
    service = _service()
    manifest = deepcopy(_installed_clock_manifest())
    actions = manifest.governance["conversational_actions"]["actions"]
    duplicate = deepcopy(actions[0])
    duplicate["id"] = "clock.second"
    actions.append(duplicate)
    service._get_kernel = lambda: SimpleNamespace(
        get_record=lambda plugin_id: {
            "manifest": manifest, "status": "enabled", "is_valid": True,
        },
    )
    assert service.resolve_conversational_read_action(
        plugin_id="time-query", goal="tell me the time", caller_roles=["user"],
    ) is None


@pytest.mark.asyncio
async def test_chat_executes_declared_read_action_via_fresh_plugin_policy_not_inspection_plan():
    service = _service()
    request = _request()
    service.execute_plugin.return_value = _receipt(request)
    rbac = SimpleNamespace(get_user_permissions=lambda principal: {Permission.READ})
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=service,
        ),
        patch(
            "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
            return_value=rbac,
        ),
    ):
        plan = _plan()
        response = await DirectCapabilityExecutor().execute(
            request=request, decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )

    assert response.handled is True and response.success is True
    assert response.source == "plugin_execution"
    assert response.source_id == "time-query"
    assert "4:21 PM EDT" in response.text
    assert response.payload["requested_action_executed"] is True
    receipt = response.payload["plugin_action_receipt"]
    assert receipt["execution_owner"] == "PluginService"
    assert receipt["policy_decision_id"] == "policy-fresh-plugin-execution"
    assert receipt["request_id"] == "plugin-request-verified"
    assert receipt["provider_delivery_verified"] is False
    assert response.normalized_metadata()["structured_content"]["plugin_action_receipt"] == receipt

    service.execute_plugin.assert_awaited_once()
    call = service.execute_plugin.await_args.kwargs
    assert call["plugin_name"] == "time-query"
    assert call["parameters"] == {"mode": "datetime"}
    assert call["authorized_plan"] is None
    assert call["user_id"] == USER and call["tenant_id"] == TENANT
    assert call["session_id"] == "plugin-session"
    assert call["conversation_id"] == request.context.conversation_id
    assert call["correlation_id"] == "correlation-action"
    assert call["roles"] == ["user"]
    assert call["permissions"] == ["read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"status": ExecutionStatus.FAILED, "error": "permission_denied"},
    {"policy_decision_id": ""},
    {"tenant_id": "another-tenant"},
    {"user_id": "another-user"},
    {"session_id": "different-session"},
    {"correlation_id": "unrelated"},
    {"plugin_id": "another-plugin"},
    {"result": {"status": "error", "formatted": "fake"}},
    {"result": None},
])
async def test_unverified_plugin_result_never_claims_execution(mutation):
    service = _service()
    request = _request()
    executed = _receipt(request)
    for key, value in mutation.items():
        setattr(executed, key, value)
    service.execute_plugin.return_value = executed
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=service,
        ),
        patch(
            "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
            return_value=SimpleNamespace(
                get_user_permissions=lambda principal: {Permission.READ},
            ),
        ),
    ):
        plan = _plan()
        result = await DirectCapabilityExecutor().execute(
            request=request, decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert not result.success and result.degraded is True
    assert result.payload["requested_action_executed"] is False
    assert "cannot claim" in result.text


@pytest.mark.asyncio
async def test_unmatched_goal_does_not_execute_generic_plugin():
    service = _service()
    request = _request("Use my Time Query plugin to publish an article")
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        plan = _plan()
        result = await DirectCapabilityExecutor().execute(
            request=request, decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success is True
    assert result.source == "plugin_catalog"
    assert result.payload["requested_action_executed"] is False
    service.execute_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_and_management_are_not_plugin_execution_grants():
    service = _service()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        for phrase in (
            "Set up my Time Query plugin",
            "Enable my Time Query plugin",
            "Disable my Time Query plugin",
        ):
            plan = _plan()
            response = await DirectCapabilityExecutor().execute(
                request=_request(phrase),
                decision=SimpleNamespace(intent="plugin.inspect"),
                plan=plan, meter=_meter(plan),
            )
            assert response.payload["requested_action_executed"] is False
    service.execute_plugin.assert_not_awaited()
