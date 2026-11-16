"""Governed model-routing policy evaluation using Karen's existing OPE owner.

This adapter does not implement another estimator, choose providers, or
promote an active model. It refuses to interpret completion-only outcomes or
deterministic routes with unknown propensities as improvement evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    PolicyObservation,
    PromotionDecision,
)

from ai_karen_engine.core.intelligence.ml.policy_evaluation.validation import (
    validate_evaluated_policy_observations,
)

_MODEL_POLICY_VERSION = "model_operational_outcome_v1"
_MIN_OFF_POLICY_OBSERVATIONS = 100


def evaluate_model_routing_candidate(
    observations: Sequence[PolicyObservation], *,
    tenant_id: str,
    baseline_policy: Any,
    candidate_policy: Any,
    min_samples: int = _MIN_OFF_POLICY_OBSERVATIONS,
) -> dict[str, Any]:
    """Delegate real model-selection OPE to the canonical offline evaluator.

    Observations must be evaluated model-choice decisions, not merely
    generated text, provider health or self-rated output. We do not synthesize
    behavior propensities. A caller cannot turn missing labels or cross-tenant
    evidence into a misleading positive OPE report.
    """
    if not isinstance(tenant_id, str) or not tenant_id or tenant_id == "default":
        raise ValueError("A verified tenant scope is required for model policy evaluation")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 100:
        raise ValueError("Model policy evaluation requires at least 100 observations")
    if not observations:
        return {
            "policy_version": _MODEL_POLICY_VERSION,
            "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
            "reason_codes": ["empty_verified_model_decisions"],
            "eligible_count": 0,
        }
    validate_evaluated_policy_observations(
        observations,
        tenant_id=tenant_id,
        decision_type=DecisionType.MODEL_SELECTION,
        domain="model",
    )
    if len(observations) < min_samples:
        return {
            "policy_version": _MODEL_POLICY_VERSION,
            "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
            "reason_codes": ["insufficient_verified_model_decisions"],
            "eligible_count": len(observations),
        }

    # Reuse the existing OPE and promotion service. This report is evidence
    # for a separate, authorized policy-promotion decision, NOT a switch.
    evaluation = OfflinePolicyEvaluator(
        baseline_policy=baseline_policy,
        ope_min_samples=min_samples,
    ).evaluate(list(observations), candidate_policy=candidate_policy)
    return {
        "policy_version": _MODEL_POLICY_VERSION,
        "evaluation_id": evaluation.get("evaluation_id"),
        "promotion_decision": evaluation.get(
            "promotion_decision", PromotionDecision.INSUFFICIENT_EVIDENCE.value
        ),
        "reason_codes": list(evaluation.get("reason_codes") or []),
        "eligible_count": len(observations),
        "estimates": evaluation.get("estimates") or {},
        "overlap_diagnostics": evaluation.get("overlap_diagnostics"),
        "segment_metrics": evaluation.get("segment_metrics") or {},
        "drift_status": evaluation.get("drift_status"),
        "policy_activated": False,
    }
