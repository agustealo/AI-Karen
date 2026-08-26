import logging
from typing import Any, Dict, List, Optional

from ..contracts.orchestration_state import LangGraphOrchestrationState
from ..contracts.workflow_plan import WorkflowPlan, validate_workflow_plan_subset

logger = logging.getLogger(__name__)


def _compose_execution_plan(
    intent: str,
    analysis: Optional[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
    safety_status: str,
    execution_requirements: Dict[str, Any],
    runtime_policy: Dict[str, Any],
) -> WorkflowPlan:
    """Compose workflow-local steps without expanding Runtime authorization."""

    analysis = analysis or {}
    tools_required = [str(call["tool"]) for call in tool_calls if call.get("tool")]
    authorized_reasoning_modes = [
        str(value) for value in runtime_policy.get("reasoning_modes") or []
    ]

    steps: List[str]
    complexity = "low"
    estimated_time_seconds = 2

    if intent in {"code_generation", "email_compose"}:
        steps = ["understand_requirements", "draft_solution", "review_and_refine"]
        complexity = "medium"
        estimated_time_seconds = 6
    elif intent in {"time_query", "information_retrieval", "book_query"}:
        steps = [
            "gather_context",
            "invoke_tools" if tools_required else "use_runtime_context",
            "synthesize_answer",
        ]
        estimated_time_seconds = 4
    else:
        steps = ["use_runtime_context", "compose_response"]

    max_steps = max(0, int(execution_requirements.get("max_steps") or len(steps)))
    if len(steps) > max_steps:
        steps = steps[:max_steps]

    return WorkflowPlan(
        intent=intent,
        steps=steps,
        required_capabilities=[
            str(value)
            for value in execution_requirements.get("required_capabilities") or []
        ],
        tools_required=tools_required,
        reasoning_modes=authorized_reasoning_modes,
        estimated_time_seconds=estimated_time_seconds,
        complexity=complexity,
        requires_human_review=bool(runtime_policy.get("approval_requirements") or []),
        metadata={
            "confidence": float(analysis.get("confidence") or 0.0),
            "safety_status": safety_status,
            "policy_decision_id": runtime_policy.get("policy_decision_id"),
            "source": "langgraph_workflow_planner",
        },
    )


class PlannerNode:
    """Plan workflow steps inside the immutable Runtime authorization envelope."""

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        logger.info("Workflow planning processing")

        execution_requirements = state.get("execution_requirements")
        runtime_policy = state.get("runtime_policy")
        if not isinstance(execution_requirements, dict):
            raise PermissionError("Workflow planning requires Runtime execution requirements")
        if not isinstance(runtime_policy, dict):
            raise PermissionError("Workflow planning requires AuthorizedExecutionPlan")

        intent = state.get("detected_intent") or execution_requirements.get("intent")
        if not intent:
            raise PermissionError("Workflow planning requires Runtime-propagated intent")

        workflow_plan = _compose_execution_plan(
            str(intent),
            state.get("intent_analysis") or {},
            state.get("tool_calls") or [],
            state.get("safety_status") or "safe",
            execution_requirements,
            runtime_policy,
        )
        validate_workflow_plan_subset(
            workflow_plan,
            runtime_policy,
            max_steps=int(execution_requirements.get("max_steps") or 0),
        )
        state["execution_plan"] = workflow_plan.to_dict()
        return state


async def planner_node(
    state: LangGraphOrchestrationState,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for PlannerNode."""

    return await PlannerNode()(state)
