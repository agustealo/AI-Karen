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
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
            return_value=tool_catalog,
        ),
        patch(
            "ai_karen_engine.core.ai_runtime.capability_registry.get_capability_registry",
            return_value=core_catalog,
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
