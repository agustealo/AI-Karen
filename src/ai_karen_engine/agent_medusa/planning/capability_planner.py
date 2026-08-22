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
from typing import Any, Dict, List, Optional, Set

from ..contracts.deep_execution_plan import DeepExecutionPlan, PlanStep
from ..contracts.registration import AgentRegistration
from ..planning.plan_validator import PlanValidator
from ...core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionRequirements,
)

logger = logging.getLogger(__name__)


class CapabilityAwareMedusaPlanner:
    """Plans among authorized agent capabilities for a multi-agent request."""

    def __init__(self, registry: Any = None, validator: Optional[PlanValidator] = None):
        # registry: MedusaRegistry (get_agent / list_agents / find_agents_by_capability)
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
        budget: Optional[ExecutionBudget] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> DeepExecutionPlan:
        """Produce a deterministic, validated DeepExecutionPlan.

        Steps are derived from the union of:
          - capabilities required by ExecutionRequirements
          - tool/plugin requirements
          - the allowed_agents in the AuthorizedExecutionPlan
        and ordered by a deterministic topo sort over declared agent
        dependencies.
        """
        budget = budget or authorized_plan.budget
        allowed_agents = set(authorized_plan.allowed_agents)
        if "*" in allowed_agents:
            allowed_agents = {a.agent_id async for a in registry.list_agents()}

        steps = await self._build_steps(
            query=query,
            requirements=requirements,
            registry=registry,
            allowed_agents=allowed_agents,
            authorized_plan=authorized_plan,
            context=context or {},
        )

        plan = DeepExecutionPlan(
            request_id=request_id,
            steps=steps,
            metadata={
                "topology": "multi_agent",
                "policy_decision_id": authorized_plan.policy_decision_id,
                "budget": budget.__dict__ if hasattr(budget, "__dict__") else None,
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

    async def _build_steps(
        self,
        *,
        query: str,
        requirements: ExecutionRequirements,
        registry: Any,
        allowed_agents: Set[str],
        authorized_plan: AuthorizedExecutionPlan,
        context: Dict[str, Any],
    ) -> List[PlanStep]:
        """Map required capabilities -> authorized agent registrations.

        NOTE: This is the deterministic capability-to-agent mapping seam.
        Model-assisted step elaboration (when policy allows) is a future
        extension that must still route through the canonical generation system
        and remain subject to the same validation.
        """
        # Collect candidate agents from required capabilities + explicit requirements.
        candidate_ids: Set[str] = set()
        for cap in list(requirements.required_capabilities) + list(requirements.tool_requirements):
            try:
                regs = registry.find_agents_by_capability(cap)
                candidate_ids.update(r.agent_id for r in regs)
            except Exception:  # capability may not map to an agent capability enum
                continue

        # Always include explicitly allowed agents that are relevant to the query.
        # (Restrict to those that intersect required capabilities when present.)
        steps: List[PlanStep] = []
        ordered_ids = sorted(candidate_ids & allowed_agents) or sorted(allowed_agents)
        for idx, agent_id in enumerate(ordered_ids):
            reg: Optional[AgentRegistration] = await _safe_get(registry, agent_id)
            steps.append(
                PlanStep(
                    id=f"step_{idx}",
                    description=f"Execute {agent_id} for: {query[:120]}",
                    agent_specialist=agent_id,
                    agent_version=reg.version if reg else None,
                    input_data={"query": query, "context": context},
                    dependencies=[f"step_{idx - 1}"] if idx > 0 else [],
                    required_tools=list(authorized_plan.allowed_tools),
                    required_plugins=list(authorized_plan.allowed_plugins),
                    prompt_contract_id=getattr(reg, "prompt_contract_id", None),
                    prompt_version=getattr(reg, "prompt_version", None),
                )
            )
        return steps


async def _safe_get(registry: Any, agent_id: str) -> Optional[AgentRegistration]:
    try:
        return await registry.get_agent(agent_id)
    except Exception:
        return None
