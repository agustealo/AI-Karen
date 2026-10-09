from __future__ import annotations

import time
from typing import Optional

from ai_karen_engine.core.model_runtime.provider_policy import evaluate_provider_policy
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision, RuntimeExecutionMode

logger = get_logger(__name__)


async def build_runtime_fallback(
    *,
    runtime,
    request,
    failure: Exception,
    correlation_id: str,
    conversation_id: str,
    start_time: Optional[float] = None,
    decision: Optional[ExecutionDecision] = None,
) -> Optional[ChatExecutionResult]:
    """Unified runtime fallback path (RC1.4).

    Collapses fallback into one owner: the runtime delegates to the
    ExpressionGateway fallback chain, then reports a degraded/emergency result
    through the single ChatRuntimeMetadata normalizer.
    """
    ctx = request.context
    fallback_decision = decision or ExecutionDecision(
        execution_mode=RuntimeExecutionMode.DEGRADED,
        graph_required=False,
        intent="fallback",
    )
    plan = AuthorizedExecutionPlan(
        execution_id=f"fallback-{ctx.request_id}",
        policy_decision_id=fallback_decision.policy_decision_id or f"policy-{correlation_id}",
        topology=ExecutionTopology.DIRECT,
        budget=ExecutionBudget(
            max_duration_ms=fallback_decision.time_budget_ms,
            max_model_calls=1,
            max_output_tokens=request.max_tokens or 4096,
        ),
        degraded_allowed=True,
        degradation_state=DegradationState(
            degraded=True,
            reason_code="primary_failure",
            level=fallback_decision.risk_level.value if hasattr(fallback_decision.risk_level, "value") else str(fallback_decision.risk_level),
        ),
    )
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    try:
        # Preserve the already-authorized, scoped memory evidence across provider
        # recovery. Never perform a second, ungoverned recall in fallback.
        memory_recall_meta = {
            "memory_context": dict(
                (request.metadata or {}).get("memory_context") or {"recall": []}
            )
        }
        text, normalized = await runtime._run_simple(
            request, fallback_decision, plan, meter, memory_recall_meta
        )
    except Exception as fb_exc:  # pragma: no cover - defensive boundary
        logger.error(
            "Runtime fallback chain failed: %s",
            fb_exc,
            extra={"correlation_id": correlation_id},
        )
        text, normalized = "", {}

    if not (text and text.strip()):
        return None

    md = ChatRuntimeMetadata(
        correlation_id=correlation_id,
        latency_ms=(time.time() - (start_time or time.time())) * 1000.0,
        requested_provider=request.preferred_provider,
        requested_model=request.preferred_model,
        actual_provider=normalized.get("actual_provider"),
        actual_model=normalized.get("actual_model"),
        runtime_engine=normalized.get("runtime_engine"),
        response_source=normalized.get("response_source"),
        fallback_level=int(normalized.get("fallback_level") or 0) + 1,
        degraded_mode=True,
        degradation_reason=f"primary_failure:{type(failure).__name__}",
        mode="degraded",
        response_id=ctx.request_id,
        conversation_id=conversation_id,
    )
    md.extra["llm"] = {
        "requested_provider": md.requested_provider,
        "actual_provider": md.actual_provider,
        "requested_model": md.requested_model,
        "actual_model": md.actual_model,
    }
    # A recovered request is degraded because the primary execution failed,
    # not proof that the responding Ollama server is itself unhealthy.
    # Do not infer distinct backends from provider display-name differences.
    requested_policy = evaluate_provider_policy(md.requested_provider)
    actual_policy = evaluate_provider_policy(md.actual_provider)
    same_provider_family = (
        requested_policy.allowed
        and actual_policy.allowed
        and requested_policy.classification == actual_policy.classification
        and requested_policy.classification in {
            "local_openai_endpoint", "cloud_provider"
        }
    )
    # Canonical registry aliases are the only evidence of provider identity;
    # shared locality/provider family is not evidence of the same backend.
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )

    requested_canonical = ProviderRegistryService.canonicalize_provider_id(
        md.requested_provider
    )
    actual_canonical = ProviderRegistryService.canonicalize_provider_id(
        md.actual_provider
    )
    same_registered_provider = bool(
        requested_canonical
        and actual_canonical
        and requested_canonical == actual_canonical
    )
    provider_switched = (
        requested_canonical != actual_canonical
        if requested_canonical and actual_canonical
        else None
    )
    model_switched = (
        md.requested_model != md.actual_model
        if md.requested_model and md.actual_model
        else None
    )
    md.extra["recovery"] = {
        "occurred": True,
        "reason": "primary_execution_failed",
        "failure_type": type(failure).__name__,
        "provider_identity_verified": False,
        "same_provider_family": same_provider_family,
        "same_registered_provider": same_registered_provider,
        "provider_switched": provider_switched,
        "canonical_requested_provider": requested_canonical,
        "canonical_actual_provider": actual_canonical,
        "requested_provider_class": requested_policy.classification,
        "actual_provider_class": actual_policy.classification,
        "requested_provider": md.requested_provider,
        "actual_provider": md.actual_provider,
        "model_changed": model_switched,
        "actual_response_healthy": True,
    }
    return ChatExecutionResult(
        answer=text,
        status=ChatExecutionStatus.DEGRADED,
        metadata=md,
    )
