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

        if max_steps < 1 or max_parallel_steps < 1:
            errors.append("plan limits must be positive")

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
        elif not errors:
            try:
                max_parallel = self._calculate_max_parallelism(plan)
            except PlanValidationError as exc:
                errors.append(str(exc))
            else:
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
        """Return maximum runnable frontier size without revisiting completed nodes."""
        remaining = {step.id: step for step in plan.steps}
        completed: set[str] = set()
        max_parallel = 0

        while remaining:
            ready = [
                step_id
                for step_id, step in remaining.items()
                if all(dep in completed for dep in step.dependencies)
            ]
            if not ready:
                raise PlanValidationError("dependency schedule cannot advance")
            max_parallel = max(max_parallel, len(ready))
            completed.update(ready)
            for step_id in ready:
                del remaining[step_id]

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
        """Require inputs from initial data or transitive upstream dependencies."""
        errors: list[str] = []
        steps = {step.id: step for step in plan.steps}

        def ancestor_ids(step_id: str, visited: set[str]) -> set[str]:
            if step_id in visited:
                return set()
            visited.add(step_id)
            ancestors: set[str] = set()
            for dependency in steps[step_id].dependencies:
                if dependency not in steps:
                    continue
                ancestors.add(dependency)
                ancestors.update(ancestor_ids(dependency, visited))
            return ancestors

        for step in plan.steps:
            if step.input_contract is None:
                continue
            available = set(step.input_data)
            for ancestor_id in ancestor_ids(step.id, set()):
                upstream = steps[ancestor_id]
                if upstream.output_contract is not None:
                    available.update(upstream.output_contract.outputs_provided or [])
            for required_input in step.input_contract.required_inputs:
                if required_input not in available:
                    errors.append(
                        f"step {step.id} requires input '{required_input}' "
                        "but no initial input or upstream dependency provides it"
                    )

        return errors
