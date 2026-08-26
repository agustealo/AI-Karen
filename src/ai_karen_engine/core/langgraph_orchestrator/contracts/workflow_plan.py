"""LangGraph workflow-plan contract and authorization-subset validation.

A WorkflowPlan describes orchestration choices only. It may narrow an
AuthorizedExecutionPlan but can never expand it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping


class WorkflowPlanAuthorizationError(PermissionError):
    """Raised when a workflow plan attempts to exceed Runtime authorization."""


@dataclass(slots=True)
class WorkflowPlan:
    """Framework-local execution plan constrained by RuntimePolicy authority."""

    intent: str
    steps: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    plugins_required: list[str] = field(default_factory=list)
    agents_required: list[str] = field(default_factory=list)
    reasoning_modes: list[str] = field(default_factory=list)
    estimated_time_seconds: int = 0
    complexity: str = "low"
    requires_human_review: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "steps": list(self.steps),
            "required_capabilities": list(self.required_capabilities),
            "tools_required": list(self.tools_required),
            "plugins_required": list(self.plugins_required),
            "agents_required": list(self.agents_required),
            "reasoning_modes": list(self.reasoning_modes),
            "estimated_time_seconds": self.estimated_time_seconds,
            "complexity": self.complexity,
            "requires_human_review": self.requires_human_review,
            "metadata": dict(self.metadata),
        }


def _normalized(values: Iterable[Any]) -> set[str]:
    return {str(value) for value in values if value is not None and str(value)}


def _require_subset(
    *,
    label: str,
    requested: Iterable[Any],
    allowed: Iterable[Any],
) -> None:
    requested_set = _normalized(requested)
    allowed_set = _normalized(allowed)
    excess = requested_set - allowed_set
    if excess:
        raise WorkflowPlanAuthorizationError(
            f"WorkflowPlan exceeds AuthorizedExecutionPlan {label}: "
            + ", ".join(sorted(excess))
        )


def validate_workflow_plan_subset(
    workflow_plan: WorkflowPlan,
    authorized_plan: Mapping[str, Any],
    *,
    max_steps: int | None = None,
) -> None:
    """Prove ``WorkflowPlan ⊆ AuthorizedExecutionPlan`` or fail closed."""

    if not authorized_plan.get("policy_decision_id"):
        raise WorkflowPlanAuthorizationError(
            "WorkflowPlan requires RuntimePolicy policy_decision_id"
        )

    _require_subset(
        label="capabilities",
        requested=workflow_plan.required_capabilities,
        allowed=authorized_plan.get("allowed_capabilities") or [],
    )
    _require_subset(
        label="tools",
        requested=workflow_plan.tools_required,
        allowed=authorized_plan.get("allowed_tools") or [],
    )
    _require_subset(
        label="plugins",
        requested=workflow_plan.plugins_required,
        allowed=authorized_plan.get("allowed_plugins") or [],
    )
    _require_subset(
        label="agents",
        requested=workflow_plan.agents_required,
        allowed=authorized_plan.get("allowed_agents") or [],
    )
    _require_subset(
        label="reasoning modes",
        requested=workflow_plan.reasoning_modes,
        allowed=authorized_plan.get("reasoning_modes") or [],
    )

    if max_steps is not None and len(workflow_plan.steps) > max(0, int(max_steps)):
        raise WorkflowPlanAuthorizationError(
            "WorkflowPlan exceeds Runtime execution step budget"
        )

    if workflow_plan.requires_human_review and not (
        authorized_plan.get("approval_requirements") or []
    ):
        raise WorkflowPlanAuthorizationError(
            "WorkflowPlan requires human review without RuntimePolicy approval requirement"
        )
