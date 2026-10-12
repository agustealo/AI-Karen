"""Registry readiness must not equate absence of evidence with healthy."""

import pytest

from ai_karen_engine.agent_medusa.contracts.registration import (
    AgentLifecycleState,
    AgentRegistration,
)
from ai_karen_engine.agent_medusa.registry import MedusaRegistry


async def _registry(*, dependencies=None, lifecycle=AgentLifecycleState.ACTIVE):
    registry = MedusaRegistry()
    await registry.register_agent(
        AgentRegistration(
            agent_id="readiness_probe",
            name="Readiness Probe",
            description="Validates dependencies",
            capability_dependencies=dependencies or [],
            lifecycle_state=lifecycle,
        )
    )
    return registry


@pytest.mark.asyncio
async def test_missing_dependency_checker_is_not_healthy():
    registry = await _registry(dependencies=["search.api"])
    health = await registry.get_agent_health("readiness_probe")
    assert health["healthy"] is False
    assert health["unknown_dependencies"] == ["search.api"]
    assert health["readiness_reason"] == "dependencies_unverified"


@pytest.mark.asyncio
async def test_missing_dependency_is_not_healthy():
    registry = await _registry(dependencies=["search.api"])
    health = await registry.get_agent_health("readiness_probe", lambda _: False)
    assert health["healthy"] is False
    assert health["missing_dependencies"] == ["search.api"]
    assert health["readiness_reason"] == "dependencies_unavailable"


@pytest.mark.asyncio
async def test_dependency_checker_error_fails_closed():
    registry = await _registry(dependencies=["search.api"])

    def broken(_: str) -> bool:
        raise RuntimeError("dependency lookup unavailable")

    health = await registry.get_agent_health("readiness_probe", broken)
    assert health["healthy"] is False
    assert health["unknown_dependencies"] == ["search.api"]


@pytest.mark.asyncio
async def test_verified_dependencies_are_healthy():
    registry = await _registry(dependencies=["search.api", "storage"])
    health = await registry.get_agent_health("readiness_probe", lambda _: True)
    assert health["healthy"] is True
    assert health["readiness_reason"] == "ready"


@pytest.mark.asyncio
async def test_inactive_agent_cannot_be_healthy():
    registry = await _registry(lifecycle=AgentLifecycleState.DISABLED)
    health = await registry.get_agent_health("readiness_probe")
    assert health["healthy"] is False
    assert health["readiness_reason"] == "inactive"


@pytest.mark.asyncio
async def test_dependency_free_active_registration_is_ready():
    registry = await _registry()
    health = await registry.get_agent_health("readiness_probe")
    assert health["healthy"] is True


@pytest.mark.asyncio
async def test_unregistered_agent_is_not_present():
    registry = MedusaRegistry()
    assert await registry.get_agent_health("missing") == {"exists": False}


@pytest.mark.asyncio
async def test_reregister_replaces_capability_and_task_indices():
    from ai_karen_engine.agent_medusa.contracts.capabilities import (
        AgentCapability,
        AgentCapabilityType,
    )

    registry = MedusaRegistry()
    await registry.register_agent(
        AgentRegistration(
            agent_id="replaced_agent",
            name="Original",
            description="First definition",
            capabilities=[AgentCapability(
                type=AgentCapabilityType.RESEARCH,
                name="research",
                description="Research",
            )],
            task_signatures=["old_task"],
        )
    )
    assert len(await registry.find_agents_by_capability(AgentCapabilityType.RESEARCH)) == 1

    await registry.register_agent(
        AgentRegistration(
            agent_id="replaced_agent",
            name="Replacement",
            description="Updated definition",
            capabilities=[AgentCapability(
                type=AgentCapabilityType.REASONING,
                name="reasoning",
                description="Reasoning",
            )],
            task_signatures=["new_task"],
        )
    )
    assert await registry.find_agents_by_capability(AgentCapabilityType.RESEARCH) == []
    assert len(await registry.find_agents_by_capability(AgentCapabilityType.REASONING)) == 1
    assert "old_task" not in registry._task_signature_index
    assert registry._task_signature_index["new_task"] == ["replaced_agent"]


@pytest.mark.asyncio
async def test_planner_keeps_valid_dependency_graph_without_false_health_claim():
    from ai_karen_engine.agent_medusa.contracts.capabilities import (
        AgentCapability,
        AgentCapabilityType,
    )
    from ai_karen_engine.agent_medusa.planning.capability_planner import (
        CapabilityAwareMedusaPlanner,
    )
    from ai_karen_engine.core.runtime.contracts import (
        AuthorizedExecutionPlan,
        ExecutionRequirements,
        ExecutionTopology,
    )

    registry = MedusaRegistry()
    for agent_id, provided, dependencies in (
        ("upstream", "Evidence", []),
        ("downstream", "Synthesis", ["Evidence"]),
    ):
        await registry.register_agent(
            AgentRegistration(
                agent_id=agent_id,
                name=agent_id,
                description=agent_id,
                capabilities=[
                    AgentCapability(
                        type=AgentCapabilityType.REASONING,
                        name=provided,
                        description=provided,
                    )
                ],
                capability_dependencies=dependencies,
                lifecycle_state=AgentLifecycleState.ACTIVE,
            )
        )
    health = await registry.get_agent_health("downstream")
    assert health["healthy"] is False
    assert health["readiness_reason"] == "dependencies_unverified"

    plan = await CapabilityAwareMedusaPlanner().create_plan(
        request_id="req-readiness",
        query="evaluate",
        requirements=ExecutionRequirements(
            request_id="req-readiness",
            correlation_id="corr-readiness",
            requires_agent_delegation=True,
        ),
        authorized_plan=AuthorizedExecutionPlan(
            execution_id="exec-readiness",
            policy_decision_id="policy-readiness",
            topology=ExecutionTopology.MULTI_AGENT,
            allowed_agents=["upstream", "downstream"],
        ),
        registry=registry,
    )
    assert [step.agent_specialist for step in plan.steps] == [
        "upstream", "downstream"
    ]
    assert plan.steps[1].dependencies == [plan.steps[0].id]


@pytest.mark.asyncio
async def test_planner_health_probe_never_fails_open():
    from unittest.mock import AsyncMock, Mock
    from ai_karen_engine.agent_medusa.planning.capability_planner import _is_healthy

    unknown = Mock(get_agent_health=AsyncMock(return_value={"exists": True}))
    assert await _is_healthy(unknown, "agent-1") is False

    broken = Mock(get_agent_health=AsyncMock(side_effect=RuntimeError("offline")))
    assert await _is_healthy(broken, "agent-1") is False

    ready = Mock(get_agent_health=AsyncMock(return_value={"healthy": True}))
    assert await _is_healthy(ready, "agent-1") is True
