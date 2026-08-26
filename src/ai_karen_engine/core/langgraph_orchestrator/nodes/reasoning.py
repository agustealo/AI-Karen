import logging
from dataclasses import asdict
from typing import Any

from ai_karen_engine.core.cortex.contracts import (
    IntentSignal,
    KireSignal,
    PredictorSignal,
    ReasoningRequest,
    ReasoningResult,
    ReasoningDepth,
    UserContext,
)
from ai_karen_engine.core.reasoning.executor import get_reasoning_executor
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionBudget,
    ExecutionContext,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner
from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


def _should_run_reasoning(state: LangGraphOrchestrationState) -> bool:
    hints = state.get("reasoning_hints") or {}
    if not hints.get("requires_reasoning"):
        return False
    if not state.get("messages"):
        return False
    return True


def select_reasoning_branch(state: LangGraphOrchestrationState) -> str:
    return "reasoning" if _should_run_reasoning(state) else "skip"


def _authorized_plan_from_state(
    state: LangGraphOrchestrationState,
) -> AuthorizedExecutionPlan:
    """Deserialize Runtime's authorization without changing its permissions."""
    raw_plan = state.get("runtime_policy")
    if not isinstance(raw_plan, dict):
        raise PermissionError(
            "Reasoning stage requires AuthorizedExecutionPlan from RuntimePolicy"
        )

    plan_data = dict(raw_plan)
    budget_data = plan_data.get("budget")
    if isinstance(budget_data, dict):
        plan_data["budget"] = ExecutionBudget(**budget_data)

    topology = plan_data.get("topology")
    if isinstance(topology, str):
        plan_data["topology"] = ExecutionTopology(topology)

    degradation_state = plan_data.get("degradation_state")
    if isinstance(degradation_state, dict):
        plan_data["degradation_state"] = DegradationState(**degradation_state)

    try:
        plan = AuthorizedExecutionPlan(**plan_data)
    except (TypeError, ValueError) as exc:
        raise PermissionError(
            "Reasoning stage received invalid RuntimePolicy authorization"
        ) from exc

    request_config = state.get("request_config") or {}
    state_policy_id = (
        str(request_config.get("policy_decision_id") or "")
        if isinstance(request_config, dict)
        else ""
    )
    if state_policy_id and state_policy_id != plan.policy_decision_id:
        raise PermissionError(
            "Reasoning policy_decision_id does not match Runtime authorization"
        )
    return plan


class ReasoningNode:
    """Specialist reasoning stage inside an already-authorized workflow.

    This node builds reasoning input/context only. It cannot create or expand an
    AuthorizedExecutionPlan. The canonical ReasoningExecutor performs cognition.
    """

    def __init__(self, executor=None):
        self._executor = executor or get_reasoning_executor()
        self._safe_runner = get_safe_stage_runner()

    def _build_request(self, state: LangGraphOrchestrationState) -> ReasoningRequest:
        intent_name = state.get("detected_intent") or "general"
        analysis = state.get("intent_analysis") or {}
        metadata = analysis.get("metadata") or {}
        hints = state.get("reasoning_hints") or {}
        messages = state.get("messages") or []
        last_message = ""
        if messages:
            last = messages[-1]
            last_message = str(getattr(last, "content", last))

        intent = IntentSignal(
            primary_intent=str(intent_name),
            entities=[
                str(entity.get("value"))
                for entity in analysis.get("entities", [])
                if isinstance(entity, dict) and entity.get("value")
            ],
            confidence=float(
                state.get("intent_confidence") or analysis.get("confidence") or 0.0
            ),
            category=str(
                analysis.get("persona_recommendation")
                or analysis.get("category")
                or "general"
            ),
            requested_modality="text",
        )
        predictors = PredictorSignal(
            ambiguity_score=float(
                1.0 - min(1.0, float(analysis.get("confidence") or 0.0))
            ),
            complexity_score=float(metadata.get("quality_score") or 0.0),
            tool_likelihood=1.0 if state.get("tool_calls") else 0.0,
            memory_relevance=1.0 if state.get("memory_context") else 0.0,
            multi_step_likelihood=(
                1.0 if len(state.get("tool_calls") or []) > 1 else 0.0
            ),
            degraded_risk=0.5 if state.get("degraded_mode") else 0.0,
        )
        reasoning_depth = hints.get("reasoning_depth", "standard")
        if reasoning_depth == "deep":
            depth = ReasoningDepth.DEEP
        elif reasoning_depth == "light":
            depth = ReasoningDepth.LIGHT
        else:
            depth = ReasoningDepth.STANDARD

        kire = KireSignal(
            requires_reasoning=True,
            reasoning_depth=depth,
            reasoning_modes=list(hints.get("reasoning_modes") or []),
            should_use_memory=True,
            should_use_tools=bool(state.get("tool_calls")),
            should_use_retrieval_reasoning=bool(
                hints.get("should_use_retrieval_reasoning")
            ),
            should_use_causal_reasoning=bool(
                hints.get("should_use_causal_reasoning")
            ),
            should_use_graph_reasoning=bool(
                hints.get("should_use_graph_reasoning")
            ),
            should_self_refine=bool(hints.get("should_self_refine")),
            should_verify=bool(hints.get("should_verify")),
        )

        user = UserContext(
            user_id=str(state.get("user_id") or "anonymous"),
            tenant_id=state.get("tenant_id"),
            session_id=state.get("session_id"),
        )

        return ReasoningRequest(
            message=last_message,
            user=user,  # type: ignore[arg-type]
            memory_context=state.get("memory_context") or {},
            tool_context={
                "tool_calls": state.get("tool_calls") or [],
                "tool_results": state.get("tool_results") or [],
            },
            intent=intent,
            predictors=predictors,
            kire=kire,
            metadata={
                "conversation_history": state.get("conversation_history") or [],
                "ui_context": state.get("request_config") or {},
                "system_caps": state.get("request_config") or {},
                "config_ui": state.get("request_config") or {},
                "correlation_id": state.get("correlation_id"),
                "reasoning_hints": hints,
            },
        )

    def _build_context(
        self,
        state: LangGraphOrchestrationState,
        plan: AuthorizedExecutionPlan,
    ) -> ExecutionContext:
        return ExecutionContext(
            request_id=state.get("request_id", ""),
            correlation_id=state.get("correlation_id", ""),
            user_id=state.get("user_id", ""),
            tenant_id=state.get("tenant_id") or "default",
            session_id=state.get("session_id"),
            conversation_id=state.get("conversation_id"),
            policy_decision_id=plan.policy_decision_id,
            allowed_capabilities=list(plan.allowed_capabilities),
            resource_scope=dict(plan.resource_scope),
            budget=plan.budget,
            audit_context=dict(plan.audit_context),
        )

    async def _run_reasoning(
        self,
        request: ReasoningRequest,
        plan: AuthorizedExecutionPlan,
        context: ExecutionContext,
    ) -> ReasoningResult:
        return await self._executor.execute(request, plan, context)

    async def __call__(
        self,
        state: LangGraphOrchestrationState,
    ) -> LangGraphOrchestrationState:
        logger.info("Reasoning stage processing")

        if not _should_run_reasoning(state):
            state.setdefault("reasoning_metadata", {})
            state["reasoning_result"] = None
            state.setdefault("warnings", []).append("Reasoning stage skipped by policy")
            return state

        try:
            request = self._build_request(state)
            plan = _authorized_plan_from_state(state)
            context = self._build_context(state, plan)
            result = await self._safe_runner.run_stage(
                "reasoning_executor",
                "reasoning_enabled",
                self._run_reasoning,
                request,
                plan,
                context,
                tenant_id=state.get("tenant_id"),
                user_id=state.get("user_id"),
            )

            if isinstance(result, ReasoningResult):
                result_dict = (
                    result.__dict__ if hasattr(result, "__dict__") else asdict(result)
                )
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {
                    "summary": str(result),
                    "confidence": 0.0,
                    "evidence": [],
                    "hypotheses": [],
                    "verification_notes": ["Unexpected reasoning result type"],
                    "diagnostics": {},
                }

            state["reasoning_result"] = result_dict
            reasoning_type = result_dict.get("diagnostics", {}).get(
                "reasoning_type", "reasoning"
            )
            state["reasoning_metadata"] = {
                "reasoning_type": reasoning_type,
                "confidence": result_dict.get("confidence", 0.0),
                "verification_notes": result_dict.get("verification_notes", []),
                "fallback_used": result_dict.get("diagnostics", {}).get(
                    "degraded_mode", False
                ),
                "needs_human_confirmation": (
                    result_dict.get("status") == "needs_human_confirmation"
                ),
                "memory_ids": [],
                "graph_paths_used": [],
                "policy_decision_id": plan.policy_decision_id,
            }

            if result_dict.get("diagnostics", {}).get("degraded_mode"):
                state.setdefault("warnings", []).append(
                    "Reasoning stage ran in degraded mode"
                )

        except Exception as exc:
            logger.error("Reasoning stage error: %s", exc)
            state.setdefault("errors", []).append(f"Reasoning stage error: {exc}")
            state["reasoning_result"] = {
                "success": False,
                "reasoning_type": "reasoning",
                "confidence": 0.0,
                "summary": "Reasoning stage failed",
                "evidence": [],
                "hypotheses": [],
                "verification_notes": [str(exc)],
                "diagnostics": {"error": str(exc)},
            }

        return state


async def reasoning_node(
    state: LangGraphOrchestrationState,
    reasoning_executor=None,
) -> LangGraphOrchestrationState:
    node = ReasoningNode(reasoning_executor)
    return await node(state)
