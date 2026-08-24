import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.agent_medusa.contracts.capabilities import AgentCapability, AgentCapabilityType
from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration, AgentLifecycleState
from ai_karen_engine.agent_medusa.planning.capability_planner import CapabilityAwareMedusaPlanner
from ai_karen_engine.agent_medusa.registry import MedusaRegistry
from ai_karen_engine.agent_medusa.planning.plan_validator import PlanValidator
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
    ExecutionBudgetMeter,
)


def _make_budget():
    return ExecutionBudget(
        max_duration_ms=30000,
        max_model_calls=10,
        max_tool_calls=10,
        max_agent_turns=5,
        max_parallelism=4,
    )


def _make_requirements(*, required_capabilities=None, tool_requirements=None):
    return ExecutionRequirements(
        request_id="req-1",
        correlation_id="corr-1",
        required_capabilities=required_capabilities or [],
        tool_requirements=tool_requirements or [],
    )


def _make_authorized_plan(*, allowed_agents=None, allowed_tools=None, allowed_plugins=None):
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        allowed_agents=allowed_agents or ["analyst", "researcher"],
        allowed_tools=allowed_tools or [],
        allowed_plugins=allowed_plugins or [],
        budget=_make_budget(),
    )


class TestAsyncCapabilityLookup:
    @pytest.mark.asyncio
    async def test_planner_awaits_real_registry_lookup(self):
        registry = MedusaRegistry()
        await registry.initialize()

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["analyst"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test query",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].agent_specialist == "analyst"


class TestFailClosedOnUnsatisfiedCapability:
    @pytest.mark.asyncio
    async def test_raises_when_no_capability_match(self):
        registry = MedusaRegistry()
        await registry.initialize()

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["nonexistent_capability"])
        authorized_plan = _make_authorized_plan(allowed_agents=["analyst"])

        with pytest.raises(ValueError, match="PLAN_UNSATISFIABLE"):
            await planner.create_plan(
                request_id="req-1",
                query="test",
                requirements=requirements,
                authorized_plan=authorized_plan,
                registry=registry,
            )

    @pytest.mark.asyncio
    async def test_raises_when_no_authorized_match(self):
        registry = MedusaRegistry()
        await registry.initialize()

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["nonexistent_agent"])

        with pytest.raises(ValueError, match="PLAN_UNSATISFIABLE"):
            await planner.create_plan(
                request_id="req-1",
                query="test",
                requirements=requirements,
                authorized_plan=authorized_plan,
                registry=registry,
            )

    @pytest.mark.asyncio
    async def test_does_not_fallback_to_all_allowed_agents(self):
        registry = MedusaRegistry()
        await registry.initialize()

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["researcher"])

        with pytest.raises(ValueError, match="PLAN_UNSATISFIABLE"):
            await planner.create_plan(
                request_id="req-1",
                query="test",
                requirements=requirements,
                authorized_plan=authorized_plan,
                registry=registry,
            )


class TestIndependentParallelSteps:
    @pytest.mark.asyncio
    async def test_independent_capabilities_produce_no_dependencies(self):
        registry = MedusaRegistry()
        await registry.initialize()

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning", "research"])
        authorized_plan = _make_authorized_plan(allowed_agents=["analyst", "researcher"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert len(plan.steps) == 2
        for step in plan.steps:
            assert step.dependencies == []


class TestHealthAwarePlanning:
    @pytest.mark.asyncio
    async def test_excludes_unhealthy_when_healthy_alternative_exists(self):
        registry = MedusaRegistry()
        await registry.initialize()

        healthy_reg = AgentRegistration(
            agent_id="healthy_analyst",
            name="Healthy Analyst",
            description="Healthy Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        unhealthy_reg = AgentRegistration(
            agent_id="unhealthy_analyst",
            name="Unhealthy Analyst",
            description="Unhealthy Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        await registry.register_agent(healthy_reg)
        await registry.register_agent(unhealthy_reg)

        async def fake_health(agent_id):
            return {"exists": True, "healthy": agent_id == "healthy_analyst"}

        registry.get_agent_health = AsyncMock(side_effect=fake_health)

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["healthy_analyst", "unhealthy_analyst"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].agent_specialist == "healthy_analyst"

    @pytest.mark.asyncio
    async def test_uses_only_available_when_no_healthy_replacement(self):
        registry = MedusaRegistry()
        await registry.initialize()

        unhealthy_reg = AgentRegistration(
            agent_id="only_analyst",
            name="Only Analyst",
            description="Only Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        await registry.register_agent(unhealthy_reg)

        registry.get_agent_health = AsyncMock(return_value={"exists": True, "healthy": False})

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["only_analyst"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].agent_specialist == "only_analyst"


class TestLifecycleFiltering:
    @pytest.mark.asyncio
    async def test_excludes_disabled_and_archived_agents(self):
        registry = MedusaRegistry()
        await registry.initialize()

        active_reg = AgentRegistration(
            agent_id="active_analyst",
            name="Active Analyst",
            description="Active Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        disabled_reg = AgentRegistration(
            agent_id="disabled_analyst",
            name="Disabled Analyst",
            description="Disabled Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.DISABLED,
        )
        archived_reg = AgentRegistration(
            agent_id="archived_analyst",
            name="Archived Analyst",
            description="Archived Analyst",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ARCHIVED,
        )
        await registry.register_agent(active_reg)
        await registry.register_agent(disabled_reg)
        await registry.register_agent(archived_reg)

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["active_analyst", "disabled_analyst", "archived_analyst"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].agent_specialist == "active_analyst"


class TestWildcardPolicyBoundary:
    @pytest.mark.asyncio
    async def test_wildcard_expands_to_all_registered_agents(self):
        registry = MedusaRegistry()
        await registry.initialize()

        custom_reg = AgentRegistration(
            agent_id="custom_agent",
            name="Custom Agent",
            description="Custom Agent",
            capabilities=[AgentCapability(type=AgentCapabilityType.CODING, name="Coding", description="coding")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        await registry.register_agent(custom_reg)

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=[])
        authorized_plan = _make_authorized_plan(allowed_agents=["*"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        agent_ids = {s.agent_specialist for s in plan.steps}
        assert "analyst" in agent_ids
        assert "researcher" in agent_ids
        assert "custom_agent" in agent_ids


class TestExecutionBudgetMeterConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_reserve_model_call_is_atomic(self):
        meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=5))
        meter.start()

        results = await asyncio.gather(
            *[meter.reserve_model_call() for _ in range(10)],
            return_exceptions=True,
        )
        successes = [r for r in results if r is True]
        failures = [r for r in results if r is False]
        assert len(successes) == 5
        assert len(failures) == 5
        assert meter.exhausted is True

    @pytest.mark.asyncio
    async def test_check_duration_sets_exhaustion(self):
        meter = ExecutionBudgetMeter(ExecutionBudget(max_duration_ms=0))
        meter.start()

        result = await meter.check_duration()
        assert result is False
        assert meter.exhausted is True

    @pytest.mark.asyncio
    async def test_mixed_concurrent_reserves_are_atomic(self):
        meter = ExecutionBudgetMeter(ExecutionBudget(
            max_model_calls=3,
            max_tool_calls=3,
            max_agent_turns=2,
        ))
        meter.start()

        async def mixed_work():
            tasks = []
            for _ in range(3):
                tasks.append(meter.reserve_model_call())
                tasks.append(meter.reserve_tool_call())
                tasks.append(meter.reserve_agent_turn())
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = await mixed_work()
        successes = sum(1 for r in results if r is True)
        # 3 model + 3 tool + 2 agent = 8 max
        assert successes == 8
        assert meter.exhausted is True


class TestDeterministicSpecialistSelection:
    @pytest.mark.asyncio
    async def test_steps_sorted_by_agent_id(self):
        registry = MedusaRegistry()
        await registry.initialize()

        zebra_reg = AgentRegistration(
            agent_id="zebra",
            name="Zebra",
            description="Zebra",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        alpha_reg = AgentRegistration(
            agent_id="alpha",
            name="Alpha",
            description="Alpha",
            capabilities=[AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="analysis")],
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        await registry.register_agent(zebra_reg)
        await registry.register_agent(alpha_reg)

        planner = CapabilityAwareMedusaPlanner(registry=registry, validator=PlanValidator())
        requirements = _make_requirements(required_capabilities=["reasoning"])
        authorized_plan = _make_authorized_plan(allowed_agents=["zebra", "alpha"])

        plan = await planner.create_plan(
            request_id="req-1",
            query="test",
            requirements=requirements,
            authorized_plan=authorized_plan,
            registry=registry,
        )
        assert [s.agent_specialist for s in plan.steps] == ["alpha", "zebra"]
