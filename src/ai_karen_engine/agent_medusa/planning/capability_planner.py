"""Capability-aware Medusa planner.

Replaces the simulated `MedusaPlanner.create_plan` (medusa_planner.py) which
unconditionally emitted [Analyst -> Researcher] for every request.

This planner is a PURE function of authorized inputs:

    ExecutionRequirements      (CORTEX-produced; decides multi-agent is warranted)
    AuthorizedExecutionPlan    (RuntimePolicy; decides what is allowed)
    MedusaRegistry             (registered agent capabilities)
    ExecutionBudget            (resource ceiling)
    current context            (query, previous steps, memory refs)

It does NOT decide topology (CORTEX) or authorization (RuntimePolicy). It only
plans among the capabilities RuntimePolicy already allowed.

The plan is then validated by PlanValidator before any side effect.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
)
from ..contracts.deep_execution_plan import (
    DeepExecutionPlan,
    PlanStep,
    StepInputContract,
    StepOutputContract,
)
from ..contracts.registration import AgentRegistration
from ..planning.plan_validator import PlanValidator

logger = logging.getLogger(__name__)


class CapabilityAwareMedusaPlanner:
    """Plans among authorized agent capabilities for a multi-agent request."""

    def __init__(self, registry: Any = None, validator: PlanValidator | None = None):
        self._registry = registry
        self._validator = validator or PlanValidator()

    async def create_plan(
        self,
        *,
        request_id: str,
        query: str,
        requirements: ExecutionRequirements,
        authorized_plan: AuthorizedExecutionPlan,
        registry: Any,
        budget: ExecutionBudget | None = None,
        context: dict[str, Any] | None = None,
    ) -> DeepExecutionPlan:
        """Produce a deterministic, validated DeepExecutionPlan.

        Steps are derived from the union of:
          - capabilities required by ExecutionRequirements
          - tool/plugin requirements
          - the allowed_agents in the AuthorizedExecutionPlan
        and ordered by a deterministic topo sort over declared agent
        dependencies.

        Each step receives only the tools/plugins it requires (least privilege).
        """
        budget = budget or authorized_plan.budget
        allowed_agents = set(authorized_plan.allowed_agents)
        if "*" in allowed_agents:
            all_agents = await registry.list_agents()
            allowed_agents = {a.agent_id for a in all_agents}

        registrations = await self._resolve_registrations(
            requirements=requirements,
            registry=registry,
            allowed_agents=allowed_agents,
        )

        if not registrations:
            raise ValueError("PLAN_UNSATISFIABLE: no eligible specialists after capability filtering")

        dependency_graph = self._build_dependency_graph(registrations, requirements)
        ordered_registrations = self._topological_sort(dependency_graph)

        steps = await self._build_steps(
            query=query,
            requirements=requirements,
            registry=registry,
            ordered_registrations=ordered_registrations,
            authorized_plan=authorized_plan,
            context=context or {},
            dependency_graph=dependency_graph,
        )

        plan = DeepExecutionPlan(
            request_id=request_id,
            steps=steps,
            metadata={
                "topology": "multi_agent",
                "policy_decision_id": authorized_plan.policy_decision_id,
                "budget": budget.__dict__ if hasattr(budget, "__dict__") else None,
                "dependency_graph": {k: v for k, v in dependency_graph.items()},
            },
        )

        report = self._validator.validate(
            plan,
            allowed_agents=allowed_agents,
            allowed_tools=set(authorized_plan.allowed_tools),
            allowed_plugins=set(authorized_plan.allowed_plugins),
            max_parallel_steps=budget.max_parallelism,
        )
        if not report.valid:
            raise ValueError(f"Medusa plan failed validation: {report.errors}")

        return plan

    async def _resolve_registrations(
        self,
        *,
        requirements: ExecutionRequirements,
        registry: Any,
        allowed_agents: set[str],
    ) -> list[AgentRegistration]:
        """Resolve and filter registrations based on capabilities and lifecycle."""
        candidate_ids: set[str] = set()
        for cap in list(requirements.required_capabilities) + list(requirements.tool_requirements):
            try:
                regs = await registry.find_agents_by_capability(cap)
                candidate_ids.update(r.agent_id for r in regs)
            except Exception:
                continue

        if not candidate_ids:
            required = list(requirements.required_capabilities) + list(requirements.tool_requirements)
            if required:
                raise ValueError("PLAN_UNSATISFIABLE: no specialists match required capabilities")
            authorized_candidates = allowed_agents
        else:
            authorized_candidates = candidate_ids & allowed_agents
            if not authorized_candidates:
                raise ValueError("PLAN_UNSATISFIABLE: no authorized specialists match required capabilities")

        registrations: list[AgentRegistration] = []
        for agent_id in sorted(authorized_candidates):
            reg = await _safe_get(registry, agent_id)
            if reg is None:
                continue
            if reg.lifecycle_state in ("disabled", "archived"):
                continue
            registrations.append(reg)

        if not registrations:
            raise ValueError("PLAN_UNSATISFIABLE: no eligible specialists after lifecycle filtering")

        healthy = [r for r in registrations if await _is_healthy(registry, r.agent_id)]
        return healthy if healthy else registrations

    def _build_dependency_graph(
        self,
        registrations: list[AgentRegistration],
        requirements: ExecutionRequirements,
    ) -> dict[str, list[str]]:
        """Build dependency graph from agent capability_dependencies and requirements."""
        registration_map = {reg.agent_id: reg for reg in registrations}
        dependency_graph: dict[str, list[str]] = {reg.agent_id: [] for reg in registrations}

        all_registered_agents = set(registration_map.keys())
        capability_to_agents: dict[str, list[str]] = {}

        for reg in registrations:
            for cap in reg.capabilities:
                cap_name = cap.name if hasattr(cap, 'name') else str(cap)
                capability_to_agents.setdefault(cap_name, []).append(reg.agent_id)

        unsatisfied: list[str] = []
        for reg in registrations:
            declared_deps = getattr(reg, 'capability_dependencies', [])
            if declared_deps:
                for dep_capability in declared_deps:
                    if dep_capability in capability_to_agents:
                        providers = capability_to_agents[dep_capability]
                        for provider_id in providers:
                            if provider_id in all_registered_agents and provider_id != reg.agent_id:
                                if provider_id not in dependency_graph[reg.agent_id]:
                                    dependency_graph[reg.agent_id].append(provider_id)
                    else:
                        unsatisfied.append(
                            f"{reg.agent_id} requires capability '{dep_capability}' which no specialist provides"
                        )

            for tool_req in requirements.tool_requirements:
                for other_reg in registrations:
                    if other_reg.agent_id != reg.agent_id:
                        other_tools = getattr(other_reg, 'allowed_tools', [])
                        if tool_req in other_tools:
                            if other_reg.agent_id not in dependency_graph[reg.agent_id]:
                                dependency_graph[reg.agent_id].append(other_reg.agent_id)

        if unsatisfied:
            raise ValueError("PLAN_UNSATISFIABLE: unsatisfied dependencies: " + "; ".join(unsatisfied))

        return dependency_graph

    def _topological_sort(self, dependency_graph: dict[str, list[str]]) -> list[str]:
        """Kahn's algorithm for topological sorting."""
        in_degree = {node: 0 for node in dependency_graph}
        for node in dependency_graph:
            for neighbor in dependency_graph[node]:
                if neighbor in in_degree:
                    in_degree[neighbor] += 1

        queue = [node for node in in_degree if in_degree[node] == 0]
        queue.sort()
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for neighbor in dependency_graph[node]:
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            queue.sort()

        if len(result) != len(dependency_graph):
            raise ValueError("PLAN_CYCLE: detected circular dependency in agent execution plan")

        return result

    async def _build_steps(
        self,
        *,
        query: str,
        requirements: ExecutionRequirements,
        registry: Any,
        ordered_registrations: list[str],
        authorized_plan: AuthorizedExecutionPlan,
        context: dict[str, Any],
        dependency_graph: dict[str, list[str]],
    ) -> list[PlanStep]:
        """Build PlanSteps with dependency ordering and scoped tools/plugins."""
        steps: list[PlanStep] = []
        agent_id_to_step_id: dict[str, str] = {}

        for idx, agent_id in enumerate(ordered_registrations):
            agent_id_to_step_id[agent_id] = f"step_{idx}"

        for idx, agent_id in enumerate(ordered_registrations):
            reg = await _safe_get(registry, agent_id)
            if reg is None:
                continue

            step_id = agent_id_to_step_id[agent_id]

            dependency_step_ids = []
            for dep_agent_id in dependency_graph[agent_id]:
                if dep_agent_id in agent_id_to_step_id:
                    dependency_step_ids.append(agent_id_to_step_id[dep_agent_id])

            agent_tools = set(getattr(reg, 'allowed_tools', []))
            agent_plugins = set(getattr(reg, 'allowed_plugins', []))
            required_tools_set = set(authorized_plan.allowed_tools) & agent_tools
            required_plugins_set = set(authorized_plan.allowed_plugins) & agent_plugins

            for tool_req in requirements.tool_requirements:
                if tool_req in set(authorized_plan.allowed_tools):
                    required_tools_set.add(tool_req)

            steps.append(
                PlanStep(
                    id=step_id,
                    description=f"Execute {reg.agent_id} for: {query[:120]}",
                    agent_specialist=reg.agent_id,
                    agent_version=reg.version,
                    input_data={"query": query, "context": context},
                    dependencies=dependency_step_ids,
                    required_tools=list(required_tools_set),
                    required_plugins=list(required_plugins_set),
                    prompt_contract_id=getattr(reg, "prompt_contract_id", None),
                    prompt_version=getattr(reg, "prompt_version", None),
                    input_contract=StepInputContract(
                        required_inputs=["analysis_result", "structured_output"] if dependency_step_ids else [],
                        optional_inputs=[],
                    ),
                    output_contract=StepOutputContract(
                        outputs_provided=["analysis_result", "structured_output"],
                    ),
                )
            )
        return steps


async def _safe_get(registry: Any, agent_id: str) -> AgentRegistration | None:
    try:
        return await registry.get_agent(agent_id)
    except Exception:
        return None


async def _is_healthy(registry: Any, agent_id: str) -> bool:
    try:
        health = await registry.get_agent_health(agent_id)
        return health.get("healthy", True)
    except Exception:
        return True
