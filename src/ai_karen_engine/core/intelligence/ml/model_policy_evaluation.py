"""Governed model-routing policy evaluation using Karen's existing OPE owner.

This adapter does not implement another estimator, choose providers, or
promote an active model. It refuses to interpret completion-only outcomes or
deterministic routes with unknown propensities as improvement evidence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    PolicyObservation,
    PromotionDecision,
    validate_probability_distribution,
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
    seen: set[str] = set()
    for item in observations:
        if not isinstance(item, PolicyObservation):
            raise TypeError("Only canonical typed policy observations may be evaluated")
        if item.context.decision_type != DecisionType.MODEL_SELECTION:
            raise ValueError("Non-model decisions cannot prove model-routing improvement")
        if item.context.tenant_scope != tenant_id:
            raise PermissionError("Cross-tenant model evidence is forbidden")
        if not isinstance(item.observation_id, str) or not item.observation_id:
            raise ValueError("Model decision identity is required")
        if item.observation_id in seen:
            raise ValueError("Duplicate model decision is not independent evidence")
        seen.add(item.observation_id)
        if not item.context.feature_snapshot_id:
            raise ValueError("Decision-time feature snapshot is required")
        if (
            not isinstance(item.metadata, dict)
            or item.metadata.get("reward_evidence_type") not in {
                "independent_test", "human_review",
            }
            or not isinstance(item.metadata.get("reward_evidence_ref"), str)
            or not item.metadata["reward_evidence_ref"]
        ):
            raise ValueError("Independent evaluation or human review is required")
        if (
            isinstance(item.reward, bool)
            or not isinstance(item.reward, (int, float))
            or not math.isfinite(item.reward)
            or not 0 <= item.reward <= 1
        ):
            raise ValueError("Model policy reward must be finite and verified")
        if not item.eligible_actions or item.chosen_action not in item.eligible_actions:
            raise ValueError("Actual chosen model is not in the eligible set")
        if (
            not item.behavior_policy_id or not item.behavior_policy_version
            or not item.candidate_policy_id or not item.candidate_policy_version
        ):
            raise ValueError("Versioned behavior and candidate policy provenance is required")
        if (
            any(
                isinstance(p, bool)
                or not isinstance(p, (int, float))
                or not math.isfinite(p)
                for distribution in (
                    item.behavior_probabilities,
                    item.candidate_probabilities,
                )
                for p in distribution.values()
            )
        ):
            raise ValueError("Action probabilities must be finite numeric values")
        if (
            validate_probability_distribution(
                item.behavior_probabilities, item.eligible_actions
            ) is not None
            or validate_probability_distribution(
                item.candidate_probabilities, item.eligible_actions
            ) is not None
        ):
            raise ValueError("Real behavior and candidate action distributions are required")
        if (
            not isinstance(item.chosen_probability, (int, float))
            or not math.isfinite(item.chosen_probability)
            or not 0 < item.chosen_probability <= 1
            or abs(
                item.behavior_probabilities[item.chosen_action]
                - item.chosen_probability
            ) > 1e-6
        ):
            raise ValueError("Chosen-model propensity must match the logged behavior policy")
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
