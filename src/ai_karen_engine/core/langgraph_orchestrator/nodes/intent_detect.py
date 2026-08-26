import logging
from typing import Any, Dict, List

from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


class IntentDetectNode:
    """Compatibility checkpoint that consumes Runtime-propagated CORTEX intent.

    LangGraph must not classify intent, infer reasoning requirements, or expand
    tool eligibility. Runtime/CORTEX already decided those values before graph
    execution.
    """

    def __init__(self, decision_engine: Any = None) -> None:
        self._compat_decision_engine = decision_engine

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        logger.info("Runtime intent checkpoint processing")

        requirements = state.get("execution_requirements")
        request_config = state.get("request_config") or {}
        runtime_policy = state.get("runtime_policy")

        if not isinstance(requirements, dict):
            raise PermissionError(
                "Workflow intent requires Runtime-propagated execution requirements"
            )
        if not isinstance(runtime_policy, dict):
            raise PermissionError(
                "Workflow intent requires AuthorizedExecutionPlan from RuntimePolicy"
            )

        intent = requirements.get("intent")
        if not intent:
            raise PermissionError("Runtime execution requirements are missing intent")

        confidence = float(requirements.get("intent_confidence") or 0.0)
        required_tools = [str(value) for value in requirements.get("tool_requirements") or []]
        allowed_tools = {str(value) for value in runtime_policy.get("allowed_tools") or []}

        unauthorized_tools = [tool for tool in required_tools if tool not in allowed_tools]
        if unauthorized_tools:
            raise PermissionError(
                "Runtime requested tools outside AuthorizedExecutionPlan: "
                + ", ".join(sorted(unauthorized_tools))
            )

        state["detected_intent"] = str(intent)
        state["intent_confidence"] = confidence
        state["intent_analysis"] = {
            "source": "runtime_cortex_decision",
            "primary_intent": str(intent),
            "confidence": confidence,
            "policy_decision_id": runtime_policy.get("policy_decision_id"),
        }

        tool_parameters = request_config.get("tool_parameters")
        parameter_map = tool_parameters if isinstance(tool_parameters, dict) else {}
        tool_calls: List[Dict[str, Any]] = [
            {
                "tool": tool,
                "parameters": dict(parameter_map.get(tool) or {}),
            }
            for tool in required_tools
        ]
        state["tool_calls"] = tool_calls or None

        # Reasoning is authorized by RuntimePolicy. This compatibility field is
        # descriptive only and must never expand allowed reasoning modes.
        authorized_modes = [
            str(value) for value in runtime_policy.get("reasoning_modes") or []
        ]
        state["reasoning_hints"] = {
            "source": "runtime_policy",
            "requires_reasoning": bool(authorized_modes),
            "reasoning_depth": requirements.get("reasoning_depth") or "standard",
            "reasoning_modes": authorized_modes,
        }
        return state


async def intent_detect_node(
    state: LangGraphOrchestrationState,
    decision_engine: Any = None,
) -> LangGraphOrchestrationState:
    """Compatibility wrapper for the Runtime intent checkpoint."""

    node = IntentDetectNode(decision_engine)
    return await node(state)
