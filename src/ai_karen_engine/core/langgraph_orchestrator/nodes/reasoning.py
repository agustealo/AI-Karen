import logging
from dataclasses import asdict
from typing import Any, Dict, Optional

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
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyRegistry
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionContext
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


class ReasoningNode:
    """Optional specialist reasoning stage for LangGraph.

    Uses the canonical ReasoningExecutor instead of calling KRO directly.
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
            entities=[str(entity.get("value")) for entity in analysis.get("entities", []) if isinstance(entity, dict) and entity.get("value")],
            confidence=float(state.get("intent_confidence") or analysis.get("confidence") or 0.0),
            category=str(analysis.get("persona_recommendation") or analysis.get("category") or "general"),
            requested_modality="text",
        )
        predictors = PredictorSignal(
            ambiguity_score=float(1.0 - min(1.0, float(analysis.get("confidence") or 0.0))),
            complexity_score=float(metadata.get("quality_score") or 0.0),
            tool_likelihood=1.0 if state.get("tool_calls") else 0.0,
            memory_relevance=1.0 if state.get("memory_context") else 0.0,
            multi_step_likelihood=1.0 if len(state.get("tool_calls") or []) > 1 else 0.0,
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
            should_use_retrieval_reasoning=bool(hints.get("should_use_retrieval_reasoning")),
            should_use_causal_reasoning=bool(hints.get("should_use_causal_reasoning")),
            should_use_graph_reasoning=bool(hints.get("should_use_graph_reasoning")),
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
                "correlation_id": state.get("request_config", {}).get("correlation_id")
                if isinstance(state.get("request_config"), dict)
                else None,
                "reasoning_hints": hints,
            },
        )

    def _build_plan(self, state: LangGraphOrchestrationState) -> AuthorizedExecutionPlan:
        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan,
            ExecutionBudget,
            ExecutionTopology,
        )
        hints = state.get("reasoning_hints") or {}
        reasoning_depth = hints.get("reasoning_depth", "standard")
        max_steps = 5 if reasoning_depth == "deep" else 3

        return AuthorizedExecutionPlan(
            execution_id=f"reasoning-{state.get('correlation_id', '')}",
            policy_decision_id=state.get("policy_decision_id", ""),
            topology=ExecutionTopology.REASONING,
            allowed_capabilities=["memory.read", "reasoning.causal", "reasoning.verify", "model.generate"],
            allowed_tools=[],
            allowed_plugins=[],
            memory_scope="tenant + conversation",
            budget=ExecutionBudget(
                max_reasoning_steps=max_steps,
                max_model_calls=3,
                max_tool_calls=2,
                max_duration_ms=20000,
            ),
            reasoning_modes=list(hints.get("reasoning_modes") or []),
        )

    def _build_context(self, state: LangGraphOrchestrationState) -> ExecutionContext:
        return ExecutionContext(
            request_id=state.get("request_id", ""),
            correlation_id=state.get("correlation_id", ""),
            user_id=state.get("user_id", ""),
            tenant_id=state.get("tenant_id", "default"),
            session_id=state.get("session_id"),
            conversation_id=state.get("conversation_id"),
            policy_decision_id=state.get("policy_decision_id"),
            budget=None,
        )

    async def _run_reasoning(self, request: ReasoningRequest, plan: AuthorizedExecutionPlan, context: ExecutionContext) -> ReasoningResult:
        result = await self._executor.execute(request, plan, context)
        return result

    async def __call__(self, state: LangGraphOrchestrationState) -> LangGraphOrchestrationState:
        logger.info("Reasoning stage processing")

        if not _should_run_reasoning(state):
            state.setdefault("reasoning_metadata", {})
            state["reasoning_result"] = None
            state.setdefault("warnings", []).append("Reasoning stage skipped by policy")
            return state

        try:
            request = self._build_request(state)
            plan = self._build_plan(state)
            context = self._build_context(state)
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
                result_dict = result.__dict__ if hasattr(result, "__dict__") else asdict(result)
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
            reasoning_type = result_dict.get("diagnostics", {}).get("reasoning_type", "reasoning")
            state["reasoning_metadata"] = {
                "reasoning_type": reasoning_type,
                "confidence": result_dict.get("confidence", 0.0),
                "verification_notes": result_dict.get("verification_notes", []),
                "fallback_used": result_dict.get("diagnostics", {}).get("degraded_mode", False),
                "needs_human_confirmation": result_dict.get("status") == "needs_human_confirmation",
                "memory_ids": [],
                "graph_paths_used": [],
            }

            if result_dict.get("diagnostics", {}).get("degraded_mode"):
                state.setdefault("warnings", []).append("Reasoning stage ran in degraded mode")

        except Exception as e:
            logger.error("Reasoning stage error: %s", e)
            state.setdefault("errors", []).append(f"Reasoning stage error: {e}")
            state["reasoning_result"] = {
                "success": False,
                "reasoning_type": "reasoning",
                "confidence": 0.0,
                "summary": "Reasoning stage failed",
                "evidence": [],
                "hypotheses": [],
                "verification_notes": [str(e)],
                "diagnostics": {"error": str(e)},
            }

        return state


async def reasoning_node(
    state: LangGraphOrchestrationState,
    reasoning_executor=None,
) -> LangGraphOrchestrationState:
    node = ReasoningNode(reasoning_executor)
    return await node(state)
