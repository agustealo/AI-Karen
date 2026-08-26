"""Authorized specialist-reasoning adapter for LangGraph workflows."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningRequest,
    ReasoningResult,
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

_MODE_ALIASES = {
    "verify": "verification",
    "refine": "refinement",
    "causal": "causal",
    "counterfactual": "counterfactual",
    "evidence_synthesis": "evidence_synthesis",
    "hypothesis_comparison": "hypothesis_comparison",
    "soft_exploration": "soft_exploration",
    "metacognition": "metacognition",
}


def _authorized_plan_from_state(
    state: LangGraphOrchestrationState,
) -> AuthorizedExecutionPlan:
    """Decode Runtime's plan without granting or widening any permission."""
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
    expected_policy_id = (
        str(request_config.get("policy_decision_id") or "")
        if isinstance(request_config, dict)
        else ""
    )
    if expected_policy_id and expected_policy_id != plan.policy_decision_id:
        raise PermissionError(
            "Reasoning policy_decision_id does not match Runtime authorization"
        )
    return plan


def _authorized_reasoning_modes(plan: AuthorizedExecutionPlan) -> list[str]:
    """Resolve modes only from Runtime-authorized plan fields."""
    modes: list[str] = []
    seen: set[str] = set()

    for raw_mode in plan.reasoning_modes:
        mode = str(raw_mode).strip().lower()
        if mode and mode not in seen:
            modes.append(mode)
            seen.add(mode)

    for capability in plan.allowed_capabilities:
        value = str(capability).strip().lower()
        if not value.startswith("reasoning."):
            continue
        suffix = value.split(".", 1)[1]
        mode = _MODE_ALIASES.get(suffix, suffix)
        if mode and mode not in seen:
            modes.append(mode)
            seen.add(mode)

    return modes


def _should_run_reasoning(state: LangGraphOrchestrationState) -> bool:
    if not state.get("messages"):
        return False
    try:
        plan = _authorized_plan_from_state(state)
    except PermissionError:
        return False
    return bool(_authorized_reasoning_modes(plan))


def select_reasoning_branch(state: LangGraphOrchestrationState) -> str:
    return "reasoning" if _should_run_reasoning(state) else "skip"


def _string_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("content", "text", "summary", "output", "value"):
            candidate = value.get(key)
            if candidate is not None:
                return str(candidate).strip()
    return str(value).strip()


def _build_evidence(
    state: LangGraphOrchestrationState,
    *,
    tenant_id: str,
) -> list[ReasoningEvidence]:
    """Adapt already-retrieved workflow context into typed reasoning evidence.

    This adapter performs no recall and no persistence. It only converts evidence
    already supplied to the authorized workflow by Runtime/canonical services.
    """
    evidence: list[ReasoningEvidence] = []

    memory_context = state.get("memory_context") or {}
    memories = memory_context.get("memories", []) if isinstance(memory_context, dict) else []
    if isinstance(memories, list):
        for index, item in enumerate(memories[:20]):
            content = _string_content(item)
            if not content:
                continue
            item_id = (
                str(item.get("id") or item.get("memory_id") or f"{index}")
                if isinstance(item, dict)
                else str(index)
            )
            evidence.append(
                ReasoningEvidence(
                    evidence_id=f"memory-{item_id}",
                    type="memory",
                    source="runtime_memory_context",
                    source_ref=item_id,
                    content=content,
                    tenant_id=tenant_id,
                    summary=(
                        str(item.get("summary") or "")
                        if isinstance(item, dict)
                        else ""
                    ),
                    relevance=(
                        float(item.get("relevance") or item.get("score") or 0.0)
                        if isinstance(item, dict)
                        else 0.0
                    ),
                    confidence=(
                        float(item.get("confidence") or 0.0)
                        if isinstance(item, dict)
                        else 0.0
                    ),
                    provenance="runtime_memory_context",
                )
            )

    tool_results = state.get("tool_results") or []
    if isinstance(tool_results, list):
        for index, item in enumerate(tool_results[:20]):
            content = _string_content(item)
            if not content:
                continue
            tool_name = (
                str(item.get("tool_name") or item.get("tool") or "tool")
                if isinstance(item, dict)
                else "tool"
            )
            evidence.append(
                ReasoningEvidence(
                    evidence_id=f"tool-{index}",
                    type="tool_result",
                    source=tool_name,
                    source_ref=f"tool-result-{index}",
                    content=content,
                    tenant_id=tenant_id,
                    provenance="workflow_tool_result",
                )
            )

    return evidence


class ReasoningNode:
    """Bridge an authorized workflow stage into canonical ReasoningExecutor."""

    def __init__(self, executor=None):
        self._executor = executor or get_reasoning_executor()
        self._safe_runner = get_safe_stage_runner()

    def _build_request(
        self,
        state: LangGraphOrchestrationState,
        plan: AuthorizedExecutionPlan,
    ) -> ReasoningRequest:
        messages = state.get("messages") or []
        last_message = ""
        if messages:
            last = messages[-1]
            last_message = str(getattr(last, "content", last)).strip()

        tenant_id = str(state.get("tenant_id") or "").strip()
        user_id = str(state.get("user_id") or "").strip()
        if not tenant_id or tenant_id == "default":
            raise PermissionError("Reasoning requires explicit non-default tenant_id")
        if not user_id:
            raise PermissionError("Reasoning requires user_id")

        budget = plan.budget
        request_budget = ReasoningBudget(
            max_reasoning_steps=budget.max_reasoning_steps,
            max_model_calls=budget.max_model_calls,
            max_tool_requests=budget.max_tool_calls,
            max_duration_ms=budget.max_duration_ms,
            max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
        )
        reasoning_modes = _authorized_reasoning_modes(plan)

        return ReasoningRequest(
            request_id=str(state.get("request_id") or ""),
            correlation_id=str(state.get("correlation_id") or ""),
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=state.get("conversation_id") or state.get("session_id"),
            objective=last_message,
            reasoning_modes=reasoning_modes,
            evidence=_build_evidence(state, tenant_id=tenant_id),
            constraints={
                "execution_plan": state.get("execution_plan") or {},
                "reasoning_hints": state.get("reasoning_hints") or {},
                "intent": state.get("detected_intent"),
            },
            policy_decision_id=plan.policy_decision_id,
            budget=request_budget,
            metadata={
                "source": "langgraph_authorized_reasoning_stage",
                "workflow_id": plan.workflow_id,
                "execution_id": plan.execution_id,
            },
        )

    def _build_context(
        self,
        state: LangGraphOrchestrationState,
        plan: AuthorizedExecutionPlan,
    ) -> ExecutionContext:
        return ExecutionContext(
            request_id=str(state.get("request_id") or ""),
            correlation_id=str(state.get("correlation_id") or ""),
            user_id=str(state.get("user_id") or ""),
            tenant_id=str(state.get("tenant_id") or ""),
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
            state["reasoning_result"] = None
            state["reasoning_metadata"] = {
                "skipped": True,
                "reason": "not_authorized_or_no_reasoning_modes",
            }
            return state

        try:
            plan = _authorized_plan_from_state(state)
            request = self._build_request(state, plan)
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
                result_dict = asdict(result)
            elif isinstance(result, dict):
                result_dict = result
            else:
                raise TypeError(
                    f"ReasoningExecutor returned unsupported type: {type(result).__name__}"
                )

            state["reasoning_result"] = result_dict
            assessment = result_dict.get("assessment") or {}
            confidence = (
                assessment.get("confidence", 0.0)
                if isinstance(assessment, dict)
                else 0.0
            )
            state["reasoning_metadata"] = {
                "reasoning_modes": list(request.reasoning_modes),
                "confidence": confidence,
                "disposition": result_dict.get("disposition"),
                "status": result_dict.get("status"),
                "error_code": result_dict.get("error_code"),
                "evidence_count": len(result_dict.get("evidence") or []),
                "hypothesis_count": len(result_dict.get("hypotheses") or []),
                "contradiction_count": len(result_dict.get("contradictions") or []),
                "policy_decision_id": plan.policy_decision_id,
            }
        except Exception as exc:
            logger.error("Reasoning stage error: %s", exc)
            state.setdefault("errors", []).append(f"Reasoning stage error: {exc}")
            state["reasoning_result"] = {
                "success": False,
                "conclusion": "Reasoning stage failed",
                "status": "failed",
                "error_code": "workflow_reasoning_adapter_failure",
                "diagnostics": {"error": str(exc)},
            }
            state["reasoning_metadata"] = {
                "status": "failed",
                "error": str(exc),
            }

        return state


async def reasoning_node(
    state: LangGraphOrchestrationState,
    reasoning_executor=None,
) -> LangGraphOrchestrationState:
    node = ReasoningNode(reasoning_executor)
    return await node(state)
