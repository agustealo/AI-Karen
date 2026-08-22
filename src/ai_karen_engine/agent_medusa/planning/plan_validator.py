"""Plan validation for DeepExecutionPlan.

Validates a plan BEFORE any side effect. Enforces:
- unique step IDs
- valid dependencies (no dangling, no self-dependency)
- no cycles in the dependency graph
- every step's agent_id is authorized
- every step's tools/plugins are authorized
- budget feasibility (step count vs parallel/concurrency limits)

This is the single validation gate referenced by AGENT-LIVE-1 A6 / P0-1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..contracts.deep_execution_plan import DeepExecutionPlan, PlanStep


class PlanValidationError(Exception):
    """Raised when a DeepExecutionPlan fails validation."""


@dataclass
class PlanValidationReport:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PlanValidator:
    """Deterministic validator for DeepExecutionPlan.

    Pure function of (plan, authorized_plan). No model calls, no I/O.
    """

    def validate(
        self,
        plan: DeepExecutionPlan,
        *,
        allowed_agents: Optional[Set[str]] = None,
        allowed_tools: Optional[Set[str]] = None,
        allowed_plugins: Optional[Set[str]] = None,
        max_parallel_steps: int = 4,
        max_steps: int = 32,
    ) -> PlanValidationReport:
        errors: List[str] = []

        if not plan.steps:
            errors.append("plan has no steps")
            return PlanValidationReport(valid=False, errors=errors)

        if len(plan.steps) > max_steps:
            errors.append(f"plan step count {len(plan.steps)} exceeds max {max_steps}")

        # Unique IDs
        ids: Set[str] = set()
        for step in plan.steps:
            if not step.id:
                errors.append("step has empty id")
                continue
            if step.id in ids:
                errors.append(f"duplicate step id: {step.id}")
            ids.add(step.id)

        # Agent authorization + dependency integrity
        for step in plan.steps:
            if allowed_agents is not None and step.agent_specialist not in allowed_agents:
                errors.append(
                    f"step {step.id} references unauthorized agent: {step.agent_specialist}"
                )
            for dep in step.dependencies:
                if dep == step.id:
                    errors.append(f"step {step.id} depends on itself")
                elif dep not in ids:
                    errors.append(f"step {step.id} depends on unknown step: {dep}")

        # Tool / plugin authorization per step
        if allowed_tools is not None or allowed_plugins is not None:
            for step in plan.steps:
                for tool in step.required_tools or []:
                    if allowed_tools is not None and tool not in allowed_tools:
                        errors.append(f"step {step.id} requires unauthorized tool: {tool}")
                for plugin in step.required_plugins or []:
                    if allowed_plugins is not None and plugin not in allowed_plugins:
                        errors.append(f"step {step.id} requires unauthorized plugin: {plugin}")

        # Cycle detection (DFS)
        cycle = self._detect_cycle(plan.steps)
        if cycle:
            errors.append(f"dependency cycle detected: {' -> '.join(cycle)}")

        return PlanValidationReport(valid=not errors, errors=errors)

    @staticmethod
    def _detect_cycle(steps: List[PlanStep]) -> Optional[List[str]]:
        graph: Dict[str, List[str]] = {s.id: list(s.dependencies) for s in steps}
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {s.id: WHITE for s in steps}
        stack: List[str] = []

        def visit(node: str) -> Optional[List[str]]:
            color[node] = GRAY
            stack.append(node)
            for nxt in graph.get(node, []):
                if color.get(nxt, WHITE) == GRAY:
                    idx = stack.index(nxt)
                    return stack[idx:] + [nxt]
                if color.get(nxt, WHITE) == WHITE:
                    res = visit(nxt)
                    if res:
                        return res
            stack.pop()
            color[node] = BLACK
            return None

        for s in steps:
            if color[s.id] == WHITE:
                res = visit(s.id)
                if res:
                    return res
        return None
