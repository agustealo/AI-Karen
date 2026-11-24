"""KCHAT-SELF-01: Karen reports runtime-verified capabilities, not model guesses."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
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
from ai_karen_engine.core.runtime.direct_capability_executor import (
    DirectCapabilityExecutor,
)

USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def request(text: str, *, authenticated: bool = True) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": text}],
        context=ChatExecutionContext(
            user_id=USER,
            tenant_id=TENANT,
            session_id="capability-session",
            request_id="capability-request",
            correlation_id="capability-correlation",
            roles=["user"],
            authenticated_user=(
                UserData(user_id=USER, tenant_id=TENANT, roles=["user"])
                if authenticated else None
            ),
        ),
    )


def plan(
    *, granted: bool = True, tenant: str = TENANT,
    allowed_tools: list[str] | None = None,
) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="capability-inspection",
        policy_decision_id="policy-capability-inspection",
        authorized_user_id=USER,
        authorized_tenant_id=tenant,
        authorized_session_id="capability-session",
        allowed_capabilities=["runtime.inspect"] if granted else [],
        allowed_tools=allowed_tools or [],
        topology=ExecutionTopology.DIRECT,
        budget=ExecutionBudget(
            max_duration_ms=30000,
            max_tool_calls=3,
            max_model_calls=0,
        ),
    )


def meter(p: AuthorizedExecutionPlan) -> ExecutionBudgetMeter:
    m = ExecutionBudgetMeter(p.budget)
    m.start()
    return m


@pytest.mark.parametrize("text", [
    "First what are your unique capabilities?",
    "what tools do you currently have available?",
    "What can you actually do?",
    "Can you access tools?",
    "List your available tools.",
    "Which tools are currently available to you?",
])
def test_exact_questions_route_to_observation_not_generating_a_guess(text: str) -> None:
    parsed = resolve_capability_decision(text)
    assert parsed.intent == "runtime.inspect"
    assert parsed.capability == "runtime.inspect"
    assert parsed.requires_tool
    assert parsed.requires_live_data
    assert not parsed.allow_llm_only


@pytest.mark.parametrize("text", [
    "What tools does Python have for this task?",
    "Tell me everything you know about me",
    "Which plugins can you use?",
    "What are your capabilities and delete all files?",
    "Describe runtime introspection in an essay.",
    "Which model should we use for capability planning?",
])
def test_introspection_does_not_steal_other_intents(text: str) -> None:
    assert resolve_capability_decision(text).intent != "runtime.inspect"


@pytest.mark.asyncio
async def test_cortex_isolates_runtime_inspection_from_ml_tool_and_plugin_hints() -> None:
    cortex = CortexExecutionDecider(force_graph=False)
    cortex._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=SimpleNamespace(
            intent="general_assist", intent_confidence=0.93,
            task_complexity="simple", topics=[], memory_relevance=0,
            topology_signals={
                "tool_requirements": ["shell"],
                "plugin_candidates": ["untrusted-plugin"],
            },
            risk_signals={"score": 0, "categories": []},
            capability_hints={},
            reasoning_modes=[],
        )),
    )
    decided = await cortex.decide(request("what tools do you currently have available?"))
    assert decided.intent == "runtime.inspect"
    assert decided.topology is ExecutionTopology.DIRECT
    assert decided.graph_required is False
    assert decided.required_capabilities == ["runtime.inspect"]
    assert decided.tool_requirements == []
    assert decided.plugin_candidates == []
    assert decided.policy_constraints["direct_capability"] is True


@pytest.mark.asyncio
async def test_catalog_answer_reports_only_observed_registration_with_scope_limits() -> None:
    tool_catalog = SimpleNamespace(
        list_tools=lambda *, status: ["local_clock", "document_reader"],
    )
    core_catalog = SimpleNamespace(
        list=lambda: (
            SimpleNamespace(name="Text Generation"),
            SimpleNamespace(name="Text Summarization"),
        ),
    )
    plugin_catalog = SimpleNamespace(
        inspect_for_conversation=AsyncMock(return_value={
            "catalog_source": "plugin_kernel",
            "mutation_performed": False,
            "truncated": False,
            "matches": [
                {
                    "display_name": "Intelligent Search",
                    "registered": True,
                    "role_eligible": True,
                    "readiness": "ready",
                },
                {
                    "display_name": "Private Admin Tool",
                    "registered": True,
                    "role_eligible": False,
                    "readiness": "ready",
                },
                {
                    "display_name": "Broken Extension",
                    "registered": False,
                    "role_eligible": True,
                    "readiness": "ready",
                },
            ],
        }),
    )
    schedules = SimpleNamespace(
        cron_summary=AsyncMock(return_value={
            "total_cron_jobs": 3,
            "enabled_cron_jobs": 2,
        }),
    )
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
            return_value=tool_catalog,
        ),
        patch(
            "ai_karen_engine.core.ai_runtime.capability_registry.get_capability_registry",
            return_value=core_catalog,
        ),
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=plugin_catalog,
        ),
        patch(
            "ai_karen_engine.services.automation.definitions.get_automation_definition_service",
            return_value=schedules,
        ),
    ):
        p = plan()
        observed = await DirectCapabilityExecutor().execute(
            request=request("what tools do you currently have available?"),
            decision=SimpleNamespace(
                intent="runtime.inspect",
                is_graph_required=False,
                policy_constraints={"direct_capability": True},
            ),
            plan=p,
            meter=meter(p),
        )
    assert observed.success and not observed.degraded
    assert observed.source == "runtime_registry_observation"
    assert "local_clock" in observed.text
    assert "document_reader" in observed.text
    assert "Text Summarization" in observed.text
    assert "Registration is not a live health check" in observed.text
    assert "Tools allowed for this inspection request (0)" in observed.text
    assert observed.normalized_metadata()["actual_provider"] is None
    assert observed.normalized_metadata()["actual_model"] is None
    snapshot = observed.normalized_metadata()["structured_content"]["capability_snapshot"]
    assert snapshot["source"] == "authenticated_runtime_observation"
    assert snapshot["core"]["count"] == 2
    assert snapshot["tools"]["marked_available"] == 2
    assert snapshot["tools"]["allowed_for_inspection"] == []
    assert snapshot["tools"]["execution_verified"] is False
    assert snapshot["plugins"]["visible_entries"] == [
        {"name": "Intelligent Search", "configuration_ready": True},
    ]
    assert snapshot["plugins"]["execution_verified"] is False
    assert snapshot["automations"]["saved_count"] == 3
    assert snapshot["automations"]["enabled_count"] == 2
    assert snapshot["automations"]["notification_delivery_verified"] is False
    assert "Intelligent Search" in observed.text
    assert "Private Admin Tool" not in observed.text
    assert "Broken Extension" not in observed.text
    assert "3 total, 2 enabled" in observed.text
    assert "None of those execution paths was verified" in observed.text
    plugin_catalog.inspect_for_conversation.assert_awaited_once_with(
        tenant_id=TENANT, caller_roles=["user"], limit=16,
    )
    schedules.cron_summary.assert_awaited_once()
    assert schedules.cron_summary.await_args.kwargs["user"].tenant_id == TENANT


@pytest.mark.asyncio
@pytest.mark.parametrize("variation", ["no_capability", "foreign_tenant", "anonymous"])
async def test_denied_or_foreign_principal_never_sees_catalog(variation: str) -> None:
    p = plan(
        granted=variation != "no_capability",
        tenant="another-tenant" if variation == "foreign_tenant" else TENANT,
    )
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service"
    ) as catalog:
        actual = await DirectCapabilityExecutor().execute(
            request=request("what tools do you have?", authenticated=variation != "anonymous"),
            decision=SimpleNamespace(
                intent="runtime.inspect",
                is_graph_required=False,
                policy_constraints={"direct_capability": True},
            ),
            plan=p,
            meter=meter(p),
        )
        catalog.assert_not_called()
    assert actual.degraded and not actual.success
    assert actual.source == "capability_unavailable"


@pytest.mark.asyncio
async def test_registry_failure_does_not_trigger_model_fallback_or_fake_tools() -> None:
    p = plan()
    with patch(
        "ai_karen_engine.core.ai_runtime.capability_registry.get_capability_registry",
        side_effect=RuntimeError("sensitive provider token"),
    ):
        actual = await DirectCapabilityExecutor().execute(
            request=request("What are your unique capabilities?"),
            decision=SimpleNamespace(
                intent="runtime.inspect",
                is_graph_required=False,
                policy_constraints={"direct_capability": True},
            ),
            plan=p,
            meter=meter(p),
        )
    assert actual.degraded
    assert actual.error == "runtime_registry_unavailable"
    assert "sensitive provider token" not in actual.text
    assert "won't guess" in actual.text


@pytest.mark.asyncio
async def test_partial_catalog_failures_do_not_fabricate_readiness_or_hide_core_tools() -> None:
    core_catalog = SimpleNamespace(
        list=lambda: (SimpleNamespace(name="Text Generation"),),
    )
    tool_catalog = SimpleNamespace(
        list_tools=lambda *, status: ["local_clock"],
    )
    plugin_catalog = SimpleNamespace(
        inspect_for_conversation=AsyncMock(side_effect=RuntimeError("secret-value")),
    )
    schedules = SimpleNamespace(
        cron_summary=AsyncMock(return_value={
            "total_cron_jobs": 8,
            "enabled_cron_jobs": 1,
        }),
    )
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
            return_value=tool_catalog,
        ),
        patch(
            "ai_karen_engine.core.ai_runtime.capability_registry.get_capability_registry",
            return_value=core_catalog,
        ),
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=plugin_catalog,
        ),
        patch(
            "ai_karen_engine.services.automation.definitions.get_automation_definition_service",
            return_value=schedules,
        ),
    ):
        p = plan()
        observed = await DirectCapabilityExecutor().execute(
            request=request("List your available tools."),
            decision=SimpleNamespace(intent="runtime.inspect"),
            plan=p,
            meter=meter(p),
        )
    assert observed.success
    assert observed.source == "runtime_registry_observation"
    assert "local_clock" in observed.text
    assert "secret-value" not in observed.text
    snapshot = observed.payload["capability_snapshot"]
    assert snapshot["plugins"]["status"] == "unverified"
    assert snapshot["automations"]["status"] == "stored_schedule_observed"
    assert snapshot["automations"]["saved_count"] == 8


@pytest.mark.asyncio
async def test_malformed_catalog_and_schedule_receipts_fail_closed_independently() -> None:
    plugin_catalog = SimpleNamespace(
        inspect_for_conversation=AsyncMock(return_value={
            "catalog_source": "plugin_kernel",
            "mutation_performed": True,
            "matches": [{"display_name": "Fake ready", "registered": True,
                         "role_eligible": True, "readiness": "ready"}],
        }),
    )
    schedules = SimpleNamespace(
        cron_summary=AsyncMock(return_value={
            "total_cron_jobs": 0,
            "enabled_cron_jobs": 9,
        }),
    )
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=plugin_catalog,
        ),
        patch(
            "ai_karen_engine.services.automation.definitions.get_automation_definition_service",
            return_value=schedules,
        ),
    ):
        p = plan()
        observed = await DirectCapabilityExecutor().execute(
            request=request("What can you actually do?"),
            decision=SimpleNamespace(intent="runtime.inspect"),
            plan=p, meter=meter(p),
        )
    assert observed.success
    assert "Fake ready" not in observed.text
    assert "9 enabled" not in observed.text
    snapshot = observed.payload["capability_snapshot"]
    assert snapshot["plugins"]["status"] == "unverified"
    assert snapshot["automations"]["status"] == "unverified"
    assert snapshot["agents"]["status"] == "requires_task_specific_policy"
    assert snapshot["providers"]["status"] == "requires_verified_model_selection"
    assert snapshot["voice"]["status"] == "requires_engine_health_check"
