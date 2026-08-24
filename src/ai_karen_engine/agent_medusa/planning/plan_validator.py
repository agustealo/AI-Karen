"""Plan validation for DeepExecutionPlan.

Validates a plan BEFORE any side effect. Enforces:
- unique step IDs
- valid dependencies (no dangling, no self-dependency)
- no cycles in the dependency graph
- every step's agent_id is authorized
- every step's tools/plugins are authorized
- budget feasibility (step count vs parallel/concurrency limits)
- dependency chain validation
- capability satisfaction
- impossible execution chain detection

This is the single validation gate referenced by AGENT-LIVE-1 A6 / P0-1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.deep_execution_plan import DeepExecutionPlan, PlanStep


class PlanValidationError(Exception):
    """Raised when a DeepExecutionPlan fails validation."""


@dataclass
class PlanValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PlanValidator:
    """Deterministic validator for DeepExecutionPlan.

    Pure function of (plan, authorized_plan). No model calls, no I/O.
    """

    def validate(
        self,
        plan: DeepExecutionPlan,
        *,
        allowed_agents: set[str] | None = None,
        allowed_tools: set[str] | None = None,
        allowed_plugins: set[str] | None = None,
        max_parallel_steps: int = 4,
        max_steps: int = 32,
    ) -> PlanValidationReport:
        errors: list[str] = []

        if not plan.steps:
            errors.append("plan has no steps")
            return PlanValidationReport(valid=False, errors=errors)

        if len(plan.steps) > max_steps:
            errors.append(f"plan step count {len(plan.steps)} exceeds max {max_steps}")

        ids: set[str] = set()
        for step in plan.steps:
            if not step.id:
                errors.append("step has empty id")
                continue
            if step.id in ids:
                errors.append(f"duplicate step id: {step.id}")
            ids.add(step.id)

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

        if allowed_tools is not None or allowed_plugins is not None:
            for step in plan.steps:
                for tool in step.required_tools or []:
                    if allowed_tools is not None and tool not in allowed_tools:
                        errors.append(f"step {step.id} requires unauthorized tool: {tool}")
                for plugin in step.required_plugins or []:
                    if allowed_plugins is not None and plugin not in allowed_plugins:
                        errors.append(f"step {step.id} requires unauthorized plugin: {plugin}")

        cycle = self._detect_cycle(plan.steps)
        if cycle:
            errors.append(f"dependency cycle detected: {' -> '.join(cycle)}")

        max_parallel = self._calculate_max_parallelism(plan)
        if max_parallel > max_parallel_steps:
            errors.append(
                f"plan requires {max_parallel} parallel steps but max_parallelism is {max_parallel_steps}"
            )

        capability_errors = self._validate_capability_chains(plan)
        errors.extend(capability_errors)

        unsatisfied_inputs = self._validate_input_satisfaction(plan)
        errors.extend(unsatisfied_inputs)

        return PlanValidationReport(valid=not errors, errors=errors)

    @staticmethod
    def _detect_cycle(steps: list[PlanStep]) -> list[str] | None:
        graph: dict[str, list[str]] = {s.id: list(s.dependencies) for s in steps}
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {s.id: WHITE for s in steps}
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
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

    def _calculate_max_parallelism(self, plan: DeepExecutionPlan) -> int:
        """Calculate maximum parallel steps based on dependency constraints."""
        step_map = {step.id: step for step in plan.steps}
        completed: set[str] = set()
        max_parallel = 0

        while len(completed) < len(plan.steps):
            ready = [
                step for step in plan.steps
                if step.status.value == "pending" and
                all(dep in completed for dep in step.dependencies)
            ]
            max_parallel = max(max_parallel, len(ready))
            for step in ready:
                completed.add(step.id)

        return max_parallel

    def _validate_capability_chains(self, plan: DeepExecutionPlan) -> list[str]:
        """Validate that dependency chains are well-formed."""
        errors: list[str] = []
        step_map = {step.id: step for step in plan.steps}

        for step in plan.steps:
            for dep_id in step.dependencies:
                if dep_id not in step_map:
                    errors.append(f"step {step.id} depends on unknown step: {dep_id}")
                else:
                    dep_step = step_map[dep_id]
                    if dep_step.output_contract:
                        provided_outputs = set(dep_step.output_contract.outputs_provided or [])
                        if not provided_outputs:
                            errors.append(
                                f"step {dep_id} provides no outputs but is required by {step.id}"
                            )

        return errors

    def _validate_input_satisfaction(self, plan: DeepExecutionPlan) -> list[str]:
        """Validate that all required inputs will be satisfied by some step."""
        errors: list[str] = []
        step_map = {step.id: step for step in plan.steps}
        all_provided_outputs: set[str] = set()

        for step in plan.steps:
            if step.output_contract:
                all_provided_outputs.update(step.output_contract.outputs_provided or [])

        for step in plan.steps:
            if step.input_contract:
                for required_input in step.input_contract.required_inputs:
                    if required_input not in all_provided_outputs:
                        errors.append(
                            f"step {step.id} requires input '{required_input}' but no step provides it"
                        )

        return errors
