from __future__ import annotations

import pytest

from ai_karen_engine.agent_medusa.planning.capability_planner import (
    CapabilityAwareMedusaPlanner,
)
from ai_karen_engine.agent_medusa.registry import MedusaRegistry
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
    ExecutionTopology,
)


def _plan(*, allowed_agents: list[str], allowed_tools: list[str]) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id="tenant-1",
        authorized_session_id="session-1",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_capabilities=["research", "web_browsing"],
        allowed_tools=allowed_tools,
        allowed_plugins=[],
        allowed_agents=allowed_agents,
        provider_constraints={},
        memory_scope="session",
        resource_scope={},
        budget=ExecutionBudget(
            max_duration_ms=30_000,
            max_model_calls=4,
            max_tool_calls=4,
            max_reasoning_steps=4,
            max_output_tokens=4096,
            max_parallelism=2,
        ),
        approval_requirements=[],
        reasoning_modes=[],
        workflow_id=None,
        agent_topology=None,
        degraded_allowed=True,
        degradation_state=None,
        audit_context={},
        provenance=None,
    )


@pytest.mark.asyncio
async def test_capability_planner_matches_string_capabilities_and_tools() -> None:
    registry = MedusaRegistry()
    await registry.initialize()
    planner = CapabilityAwareMedusaPlanner()

    requirements = ExecutionRequirements(
        request_id="req-1",
        correlation_id="corr-1",
        intent="research",
        required_capabilities=["research"],
        tool_requirements=["web_search"],
        requires_agent_delegation=True,
    )
    authorized = _plan(
        allowed_agents=["researcher"],
        allowed_tools=["web_search"],
    )

    result = await planner.create_plan(
        request_id="req-1",
        query="Find current evidence",
        requirements=requirements,
        authorized_plan=authorized,
        registry=registry,
        budget=authorized.budget,
        context={},
    )

    assert [step.agent_specialist for step in result.steps] == ["researcher"]
    assert result.steps[0].required_tools == ["web_search"]


def test_dependency_sort_orders_dependencies_before_dependents() -> None:
    planner = CapabilityAwareMedusaPlanner()

    ordered = planner._topological_sort(
        {
            "researcher": ["analyst"],
            "analyst": [],
        }
    )

    assert ordered == ["analyst", "researcher"]


def test_dependency_sort_rejects_cycles() -> None:
    planner = CapabilityAwareMedusaPlanner()

    with pytest.raises(ValueError, match="PLAN_CYCLE"):
        planner._topological_sort(
            {
                "researcher": ["analyst"],
                "analyst": ["researcher"],
            }
        )


@pytest.mark.asyncio
async def test_planner_never_selects_draft_or_retired_definitions() -> None:
    """Listing an agent must not confer execution eligibility."""
    from types import SimpleNamespace

    from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration

    registrations = [
        AgentRegistration(
            agent_id=state,
            name=state,
            description=state,
            lifecycle_state=state,
        )
        for state in ("draft", "disabled", "archived", "active")
    ]
    registry = SimpleNamespace(
        list_agents=lambda: None,
    )

    async def list_agents():
        return registrations

    registry.list_agents = list_agents
    planner = CapabilityAwareMedusaPlanner()
    selected = await planner._resolve_registrations(
        requirements=ExecutionRequirements(
            request_id="req-lifecycle",
            correlation_id="corr-lifecycle",
            requires_agent_delegation=True,
        ),
        registry=registry,
        allowed_agents={registration.agent_id for registration in registrations},
    )

    assert [registration.agent_id for registration in selected] == ["active"]
