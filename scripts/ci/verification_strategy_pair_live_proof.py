"""KCOG-01C1B2B2: real, independently authorized response execution proof.

Run ONLY inside the ephemeral production Ollama CI container, after the
authenticated Settings -> installed-model live proof. This deliberately
exercises the existing RuntimePolicy -> ChatRuntime -> ExpressionGateway and
ReasoningExecutor paths. No user-facing route or experiment selector is added.

The proof establishes operational execution, NOT answer correctness, live
consumer readiness, a viable unselected candidate, randomized overlap, or
off-policy evaluation eligibility. Nothing is written to a learning policy.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.expression.gateway import MODEL_GENERATION_RESPONSE_SOURCES
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudgetMeter,
    ExecutionTopology,
    ResponseProvenance,
    ResponseSource,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RiskLevel,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)


class LiveStrategyProofError(RuntimeError):
    """A required observed, authorized execution receipt is absent."""


@dataclass(frozen=True)
class MeasuredPath:
    action: str
    policy_decision_id: str
    correlation_id: str
    provider: str
    model: str
    model_calls: int
    reasoning_steps: int
    duration_ms: float
    reasoning_status: str
    stream_execution_path: bool

    def public_result(self) -> dict[str, Any]:
        # Do not emit prompt text, identity, correlation/policy IDs, tokens,
        # raw provider payloads or conversation content into CI logs.
        return {
            "action": self.action,
            "model_calls": self.model_calls,
            "reasoning_steps": self.reasoning_steps,
            "reasoning_status": self.reasoning_status,
            "stream_execution_path": self.stream_execution_path,
            "duration_ms": round(self.duration_ms, 2),
        }


def require_authorized_execution(
    policy: Any,
    *,
    expected_action: str,
    context: ChatExecutionContext,
) -> AuthorizedExecutionPlan:
    """Reject a denied, drifted, cross-tenant or capability-widened plan."""
    modes = ["verification"] if expected_action == "verify_then_respond" else []
    topology = (
        ExecutionTopology.REASONING if modes else ExecutionTopology.DIRECT
    )
    expected = (
        isinstance(policy.allowed, bool) and policy.allowed
        and not policy.requires_human_gate
        and policy.risk_level in {"low", "medium"}
        and not policy.denied_reasoning_modes
        and policy.allowed_reasoning_modes == modes
        and policy.runtime_constraints.get("authorized_user_id") == context.user_id
        and policy.runtime_constraints.get("authorized_tenant_id") == context.tenant_id
        and policy.runtime_constraints.get("authorized_session_id") == context.session_id
        and policy.runtime_constraints.get("correlation_id") == context.correlation_id
        and isinstance(policy.decision_id, str) and bool(policy.decision_id)
        and isinstance(policy.policy_version, str) and bool(policy.policy_version)
    )
    if not expected:
        raise LiveStrategyProofError("policy_scope_or_reasoning_authorization_denied")

    plan = policy.to_authorized_plan()
    if not (
        isinstance(plan, AuthorizedExecutionPlan)
        and plan.policy_decision_id == policy.decision_id
        and plan.topology == topology
        and plan.reasoning_modes == modes
        and plan.matches_execution_scope(
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            session_id=context.session_id,
            policy_decision_id=policy.decision_id,
        )
        and plan.budget.max_model_calls == 2
        and plan.budget.max_reasoning_steps >= 2
        and plan.budget.max_duration_ms > 0
        and plan.budget.max_output_tokens > 0
        and not plan.allowed_tools
        and not plan.allowed_plugins
        and not plan.allowed_agents
        and not plan.approval_requirements
    ):
        raise LiveStrategyProofError("canonical_execution_plan_not_equivalent")
    return plan


def require_gateway_receipt(
    *,
    metadata: dict[str, Any],
    text: str,
    decision: ExecutionDecision,
    request: ChatExecutionRequest,
    meter: ExecutionBudgetMeter,
    expected_model: str,
    verification: bool,
) -> None:
    """Require real provider-owned provenance, never strategy guesses."""
    provenance = metadata.get("provenance")
    source = metadata.get("response_source")
    provider = metadata.get("actual_provider")
    model = metadata.get("actual_model")
    if not isinstance(text, str) or not text.strip():
        raise LiveStrategyProofError("gateway_response_missing")
    if (
        not isinstance(provenance, ResponseProvenance)
        or provenance.response_source != ResponseSource.MODEL
    ):
        raise LiveStrategyProofError("gateway_provenance_unverified")
    if (
        provenance.decision_id != decision.policy_decision_id
        or provenance.correlation_id != request.context.correlation_id
    ):
        raise LiveStrategyProofError("gateway_policy_or_correlation_mismatch")
    if provider not in {"ollama", "ollama-local"}:
        raise LiveStrategyProofError("gateway_provider_unexpected")
    if (
        model != expected_model
        or request.preferred_model != expected_model
        or request.preferred_provider not in {"ollama", "ollama-local"}
    ):
        raise LiveStrategyProofError("gateway_selected_model_mismatch")
    if provenance.provider != provider or provenance.model != model:
        raise LiveStrategyProofError("gateway_provenance_identity_mismatch")
    if source not in (MODEL_GENERATION_RESPONSE_SOURCES - {"fallback_provider_runtime"}):
        raise LiveStrategyProofError("gateway_response_source_unverified")
    if (
        metadata.get("fallback_level") != 0
        or metadata.get("degraded_mode") is not False
        or metadata.get("used_fallback") is True
        or metadata.get("generation_error") is True
        or provenance.fallback_level != 0
        or bool(provenance.degradation_reason)
    ):
        raise LiveStrategyProofError("gateway_degraded_or_fallback")
    if meter.model_calls != 1 or meter.exhausted:
        raise LiveStrategyProofError("gateway_model_budget_mismatch")
    if verification:
        if not (
            metadata.get("reasoning_generation_mode")
            == "model_after_authorized_reasoning"
            and metadata.get("reasoning_activation") == "core_defaults"
            and metadata.get("reasoning_status")
            in {"success", "completed", "partial", "abstained"}
            and isinstance(metadata.get("reasoning_id"), str)
            and bool(metadata["reasoning_id"])
            and metadata.get("reasoning_model_calls") == 0
            and isinstance(metadata.get("reasoning_steps"), int)
            and not isinstance(metadata["reasoning_steps"], bool)
            and metadata["reasoning_steps"] >= 1
            and metadata.get("reasoning_model_attribution_status")
            == "not_executed"
            and metadata.get("verification_strategy_executed") is True
            and "verification" in (metadata.get("reasoning_modes") or [])
            and meter.reasoning_steps >= 1
            and meter.reasoning_steps <= decision.max_steps
        ):
            raise LiveStrategyProofError("verifier_execution_receipt_missing")
    elif meter.reasoning_steps:
        raise LiveStrategyProofError("direct_path_executed_unrequested_reasoning")


async def run_pair(
    *,
    user_id: str,
    tenant_id: str,
    model: str,
    provider: str = "ollama",
) -> dict[str, Any]:
    """Execute independently selected plans; do not run a second model in chat."""
    if not (
        user_id and tenant_id and model
        and provider in {"ollama", "ollama-local"}
        and os.environ.get("KAREN_CI_DUAL_STRATEGY_PROOF") == "enabled"
    ):
        raise LiveStrategyProofError("isolated_ci_approval_or_identity_missing")

    # Authenticated bootstrap identity is obtained from /api/auth/me by the
    # existing production first-boot harness; never create this principal
    # from a user prompt or expose this test through an API endpoint.
    principal = UserData(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=["admin", "user"],
        is_active=True,
        is_verified=True,
    )
    runtime = get_chat_runtime()
    enforcer = RuntimePolicyEnforcer()
    session = f"kcog-b2b2-{uuid.uuid4().hex}"
    statement = (
        "In one concise sentence, describe the purpose of a lighthouse "
        "for ships navigating at night."
    )
    observed: list[MeasuredPath] = []

    for action, stream in (
        ("respond_direct", False),
        ("verify_then_respond", False),
        ("verify_then_respond", True),
    ):
        context = ChatExecutionContext(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session,
            request_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            authenticated_user=principal,
        )
        modes = ["verification"] if action == "verify_then_respond" else []
        policy = await enforcer.evaluate(
            PolicyEvaluationRequest(
                user_id=context.user_id,
                tenant_id=context.tenant_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                roles=list(principal.roles),
                permissions=list(principal.permissions),
                requested_reasoning_modes=modes,
                max_model_calls=2,
                risk_signals={"score": 0.0, "categories": []},
                execution_topology={
                    "reasoning_modes": modes,
                    "max_steps": 6,
                },
            )
        )
        plan = require_authorized_execution(
            policy,
            expected_action=action,
            context=context,
        )
        decision = ExecutionDecision(
            topology=plan.topology,
            policy_decision_id=policy.decision_id,
            policy_version=policy.policy_version,
            reasoning_modes=list(plan.reasoning_modes),
            risk_level=RiskLevel.LOW,
            max_steps=plan.budget.max_reasoning_steps,
            max_model_calls=plan.budget.max_model_calls,
            time_budget_ms=plan.budget.max_duration_ms,
            token_budget=4096,
        )
        request = ChatExecutionRequest(
            messages=[{"role": "user", "content": statement}],
            context=context,
            preferred_provider=provider,
            preferred_model=model,
            temperature=0.0,
            max_tokens=512,
            stream=stream,
            metadata={"transport": "ci_independent_execution_proof"},
        )
        runtime._bind_observability_context(context)
        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        started = time.perf_counter()
        if action == "respond_direct":
            text, metadata = await runtime._run_simple(
                request, decision, plan, meter
            )
        elif stream:
            metadata = {}
            chunks = [
                part.content
                async for part in runtime._run_reasoning_stream(
                    request, decision, plan, meter, _meta=metadata,
                )
                if part.type == "content"
            ]
            text = "".join(chunks)
        else:
            text, metadata = await runtime._run_reasoning_with_model_synthesis(
                request, decision, plan, meter
            )
        duration_ms = (time.perf_counter() - started) * 1000.0

        try:
            require_gateway_receipt(
                metadata=metadata,
                text=text,
                decision=decision,
                request=request,
                meter=meter,
                expected_model=model,
                verification=action == "verify_then_respond",
            )
        except LiveStrategyProofError as exc:
            # No input text or identifiers enter this fixed stage label.
            stage = (
                "stream_verification" if stream
                else "reasoned_response" if action == "verify_then_respond"
                else "direct_response"
            )
            raise LiveStrategyProofError(f"{stage}:{exc}") from None

        # B2B1 cannot label an acceptance run with no canonical transcript
        # as "selected_runtime_path_observed". Retain this negative proof.
        diagnostic = runtime._inspect_selected_strategy_execution(
            decision,
            metadata,
            response_completed=bool(text),
            success=True,
            transcript_status="skipped",
            observed_model_calls=meter.model_calls,
            correlation_id=context.correlation_id,
        )
        if not (
            isinstance(diagnostic, dict)
            and diagnostic["status"] == "unverified"
            and diagnostic["provider_receipt_observed"] is True
            and diagnostic["transcript_durable"] is False
            and diagnostic["independent_verification_proven"] is False
            and diagnostic["dual_action_eligibility_established"] is False
            and diagnostic["randomized_selection"] is False
            and diagnostic["ope_eligible"] is False
        ):
            raise LiveStrategyProofError("nonpersisted_strategy_receipt_was_promoted")

        observed.append(
            MeasuredPath(
                action=action,
                policy_decision_id=policy.decision_id,
                correlation_id=context.correlation_id,
                provider=metadata["actual_provider"],
                model=metadata["actual_model"],
                model_calls=meter.model_calls,
                reasoning_steps=meter.reasoning_steps,
                duration_ms=duration_ms,
                reasoning_status=(
                    str(metadata["reasoning_status"])
                    if action == "verify_then_respond" else "not_applicable"
                ),
                stream_execution_path=stream,
            )
        )

    direct, reasoned, streamed = observed
    if not (
        len({row.policy_decision_id for row in observed}) == 3
        and len({row.correlation_id for row in observed}) == 3
        and len({row.provider for row in observed}) == 1
        and len({row.model for row in observed}) == 1
        and direct.action == "respond_direct"
        and direct.reasoning_steps == 0
        and reasoned.action == streamed.action == "verify_then_respond"
        and reasoned.reasoning_steps > 0
        and streamed.reasoning_steps > 0
    ):
        raise LiveStrategyProofError("independent_strategy_execution_not_equivalent")

    return {
        "status": "passed",
        "proof_scope": "isolated_real_provider_policy_authorized_executor_paths",
        "independent_execution_count": len(observed),
        "executions": [row.public_result() for row in observed],
        "transcript_persistence": "not_attempted",
        "independent_verification_proven": False,
        "dual_action_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }


def main() -> int:
    try:
        result = asyncio.run(
            run_pair(
                user_id=os.environ.get("KAREN_CI_DUAL_USER_ID", ""),
                tenant_id=os.environ.get("KAREN_CI_DUAL_TENANT_ID", ""),
                model=os.environ.get("KAREN_CI_DUAL_MODEL", ""),
            )
        )
    except Exception as exc:
        # These exact constant diagnostic codes originate solely in the
        # audited acceptance script, not user/model/provider text. Unknown
        # exception messages never reach CI logs.
        public_codes = frozenset({
            "isolated_ci_approval_or_identity_missing",
            "policy_scope_or_reasoning_authorization_denied",
            "canonical_execution_plan_not_equivalent",
            "gateway_response_missing",
            "gateway_provenance_unverified",
            "gateway_policy_or_correlation_mismatch",
            "gateway_provider_unexpected",
            "gateway_selected_model_mismatch",
            "gateway_provenance_identity_mismatch",
            "gateway_response_source_unverified",
            "gateway_degraded_or_fallback",
            "gateway_model_budget_mismatch",
            "verifier_execution_receipt_missing",
            "direct_path_executed_unrequested_reasoning",
            "nonpersisted_strategy_receipt_was_promoted",
            "independent_strategy_execution_not_equivalent",
        })
        reported = str(exc) if isinstance(exc, LiveStrategyProofError) else ""
        parts = reported.split(":", 1)
        stage = (
            parts[0]
            if len(parts) == 2
            and parts[0] in {"direct_response", "reasoned_response", "stream_verification"}
            else "unclassified"
        )
        code = parts[-1] if parts[-1] in public_codes else "unclassified"
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_code": code,
                    "execution_stage": stage,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
