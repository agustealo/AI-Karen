from __future__ import annotations

import time
from typing import Optional

from ai_karen_engine.core.expression.errors import EngineUnavailableError
from ai_karen_engine.core.model_runtime.provider_policy import evaluate_provider_policy
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudgetMeter,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision, RiskLevel
from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

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
    authorized_plan: Optional[AuthorizedExecutionPlan] = None,
    meter: Optional[ExecutionBudgetMeter] = None,
) -> Optional[ChatExecutionResult]:
    """Unified runtime fallback path (RC1.4).

    Collapses fallback into one owner: the runtime delegates to the
    ExpressionGateway fallback chain, then reports a degraded/emergency result
    through the single ChatRuntimeMetadata normalizer.
    """
    # Recovery is still part of the original authorized execution. It may
    # never mint a new plan, reset the execution budget or silently substitute
    # a generated answer for a failed governed tool/plugin/approval operation.
    if decision is None or authorized_plan is None or meter is None:
        return None
    ctx = request.context
    plan = authorized_plan
    if (
        isinstance(failure, (EngineUnavailableError, PermissionError, OutcomeStoreError))
        or decision.requires_human_gate
        or decision.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        or decision.tool_requirements
        or decision.plugin_candidates
        or plan.allowed_tools
        or plan.allowed_plugins
        or plan.approval_requirements
        or not plan.degraded_allowed
        or decision.max_model_calls <= 0
        or plan.budget.max_model_calls <= meter.model_calls
        or meter.exhausted
        or meter.budget is not plan.budget
        or not plan.matches_execution_scope(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=getattr(ctx, "session_id", None),
            policy_decision_id=decision.policy_decision_id,
        )
    ):
        return None
    if not await meter.check_duration():
        return None

    try:
        # Preserve the already-authorized, scoped memory evidence across provider
        # recovery. Never perform a second, ungoverned recall in fallback.
        memory_recall_meta = {
            "memory_context": dict(
                (request.metadata or {}).get("memory_context") or {"recall": []}
            )
        }
        text, normalized = await runtime._run_simple(
            request, decision, plan, meter, memory_recall_meta
        )
    except Exception as fb_exc:  # pragma: no cover - defensive boundary
        # Consent withdrawal is a terminal runtime policy denial, not a
        # recoverable provider failure. Preserve it for ChatRuntime's
        # canonical memory-denial response and stream error projection.
        if str(fb_exc) == "memory_source_revoked_or_unverifiable":
            raise
        logger.error(
            "Runtime fallback chain failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(fb_exc).__name__,
            },
        )
        text, normalized = "", {}

    if not isinstance(text, str) or not text.strip() or not isinstance(normalized, dict):
        return None
    if (
        not isinstance(normalized.get("actual_provider"), str)
        or not normalized["actual_provider"].strip()
        or not isinstance(normalized.get("actual_model"), str)
        or not normalized["actual_model"].strip()
        or normalized.get("response_source") not in {
            "model", "provider_runtime", "fallback_provider_runtime",
            "openai_compatible_engine",
        }
    ):
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
