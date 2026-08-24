"""Offline policy evaluation facade.

Real OPE using IPS, SNIPS, and Doubly Robust estimators with overlap diagnostics,
segment analysis, and promotion recommendations.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ai_karen_engine.core.adaptive.learning.estimators import (
    DoublyRobustEstimator,
    IPSEstimator,
    SNIPSEstimator,
    compute_overlap_diagnostics,
)
from ai_karen_engine.core.adaptive.drift import DriftStatus
from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    OPEIneligibilityReason,
    OverlapDiagnostics,
    PolicyContext,
    PolicyDecision,
    PolicyEstimate,
    PolicyObservation,
    PromotionBlockReason,
    PromotionDecision,
    UtilityComponents,
    UtilityPolicy,
    validate_probability_distribution,
)
from ai_karen_engine.core.adaptive.learning.promotion import (
    PromotionConfig,
    PromotionEvidence,
    evaluate_promotion,
)

logger = logging.getLogger(__name__)


class OfflinePolicyEvaluator:
    def __init__(
        self,
        baseline_policy: Any = None,
        utility_policy: UtilityPolicy | None = None,
        max_importance_weight: float = 100.0,
        ope_min_samples: int = 100,
    ) -> None:
        self._baseline_policy = baseline_policy
        self._utility_policy = utility_policy or UtilityPolicy()
        self._max_importance_weight = max_importance_weight
        self._ope_min_samples = ope_min_samples
        self._evaluations: list[dict[str, Any]] = []

    def evaluate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any = None,
    ) -> dict[str, Any]:
        evaluation_id = f"eval-{uuid.uuid4().hex}"
        candidate_id = getattr(candidate_policy, "policy_id", "unknown")
        candidate_version = getattr(candidate_policy, "policy_version", "unknown")
        baseline_id = getattr(self._baseline_policy, "policy_id", "baseline") if self._baseline_policy else "baseline"
        baseline_version = getattr(self._baseline_policy, "policy_version", "v1") if self._baseline_policy else "v1"

        if not observations:
            result = {
                "evaluation_id": evaluation_id,
                "policy_id": candidate_id,
                "policy_version": candidate_version,
                "baseline_policy_id": baseline_id,
                "baseline_policy_version": baseline_version,
                "utility_policy_version": self._utility_policy.utility_policy_version,
                "sample_count": 0,
                "estimates": {},
                "overlap_diagnostics": None,
                "segment_metrics": {},
                "drift_status": "none",
                "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
                "reason_codes": [PromotionBlockReason.INSUFFICIENT_SAMPLES.value],
                "messages": ["empty observations"],
            }
            self._evaluations.append(result)
            return result

        if isinstance(observations[0], dict):
            baseline_success = sum(1 for o in observations if o.get("execution_status") == "success")
            baseline_success_rate = baseline_success / len(observations)
            result = {
                "evaluation_id": evaluation_id,
                "policy_id": candidate_id,
                "policy_version": candidate_version,
                "baseline_policy_id": baseline_id,
                "baseline_policy_version": baseline_version,
                "utility_policy_version": self._utility_policy.utility_policy_version,
                "sample_count": len(observations),
                "baseline_success_rate": baseline_success_rate,
                "candidate_success_rate": baseline_success_rate,
                "estimates": {},
                "overlap_diagnostics": None,
                "segment_metrics": {},
                "drift_status": "none",
                "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
                "reason_codes": [PromotionBlockReason.INSUFFICIENT_EVIDENCE.value],
                "messages": ["legacy dict observations"],
            }
            self._evaluations.append(result)
            return result

        for obs in observations:
            if not obs.candidate_probabilities:
                try:
                    decision = candidate_policy.score_actions(obs.context, obs.context.eligible_actions)
                    obs.candidate_probabilities = dict(decision.probabilities)
                    obs.candidate_policy_id = decision.policy_id
                    obs.candidate_policy_version = decision.policy_version
                except Exception:
                    pass

        estimates: dict[str, PolicyEstimate] = {}
        try:
            ips = IPSEstimator(max_importance_weight=self._max_importance_weight)
            estimates["ips"] = ips.estimate(observations, candidate_policy)
        except Exception as exc:
            logger.warning("IPS estimator failed: %s", exc)

        try:
            snips = SNIPSEstimator(max_importance_weight=self._max_importance_weight)
            estimates["snips"] = snips.estimate(observations, candidate_policy)
        except Exception as exc:
            logger.warning("SNIPS estimator failed: %s", exc)

        try:
            dr = DoublyRobustEstimator(max_importance_weight=self._max_importance_weight)
            estimates["dr"] = dr.estimate(observations, candidate_policy)
        except Exception as exc:
            logger.warning("DR estimator failed: %s", exc)

        overlap = compute_overlap_diagnostics(observations, candidate_policy, self._max_importance_weight)

        segment_metrics = self._compute_segment_metrics(observations)
        drift_status = self._check_drift(observations)

        evidence = PromotionEvidence(
            evaluation_id=evaluation_id,
            policy_id=candidate_id,
            policy_version=candidate_version,
            baseline_policy_id=baseline_id,
            baseline_policy_version=baseline_version,
            estimates=estimates,
            overlap_diagnostics=overlap,
            sample_count=len(observations),
            segment_metrics=segment_metrics,
            drift_status=drift_status.value if isinstance(drift_status, DriftStatus) else str(drift_status),
        )

        config = PromotionConfig(min_samples=self._ope_min_samples)
        promotion = evaluate_promotion(evidence, config)

        baseline_success = sum(
            1 for o in observations if o.behavior_policy_id == baseline_id and o.reward >= 0.5
        )
        baseline_success_rate = baseline_success / len(observations)

        candidate_success = sum(1 for o in observations if o.reward >= 0.5)
        candidate_success_rate = candidate_success / len(observations)

        result = {
            "evaluation_id": evaluation_id,
            "policy_id": candidate_id,
            "policy_version": candidate_version,
            "baseline_policy_id": baseline_id,
            "baseline_policy_version": baseline_version,
            "utility_policy_version": self._utility_policy.utility_policy_version,
            "sample_count": len(observations),
            "baseline_success_rate": baseline_success_rate,
            "candidate_success_rate": candidate_success_rate,
            "estimates": {
                name: {
                    "estimator_name": est.estimator_name,
                    "estimate": est.estimate,
                    "lower_bound": est.lower_bound,
                    "upper_bound": est.upper_bound,
                    "confidence_level": est.confidence_level,
                    "sample_count": est.sample_count,
                    "effective_sample_size": est.effective_sample_size,
                    "clipped_weight_count": est.clipped_weight_count,
                    "clipped_weight_rate": est.clipped_weight_rate,
                }
                for name, est in estimates.items()
            },
            "overlap_diagnostics": {
                "effective_sample_size": overlap.effective_sample_size,
                "minimum_propensity": overlap.minimum_propensity,
                "maximum_importance_weight": overlap.maximum_importance_weight,
                "coverage": overlap.coverage,
                "action_support": dict(overlap.action_support),
                "is_supported": overlap.is_supported,
                "unsupported_actions": list(overlap.unsupported_actions),
            },
            "segment_metrics": segment_metrics,
            "drift_status": evidence.drift_status,
            "promotion_decision": promotion.decision.value,
            "reason_codes": [r.value for r in promotion.reason_codes],
            "messages": list(promotion.messages),
        }
        self._evaluations.append(result)
        return result

    def last_evaluation(self) -> dict[str, Any] | None:
        if self._evaluations:
            return self._evaluations[-1]
        return None

    def _compute_segment_metrics(self, observations: list[PolicyObservation]) -> dict[str, dict[str, float]]:
        segments: dict[str, list[float]] = {}
        for obs in observations:
            action = obs.chosen_action
            segments.setdefault(action, []).append(obs.reward)
            for seg_key, seg_val in obs.segment_labels.items():
                key = f"{seg_key}:{seg_val}"
                segments.setdefault(key, []).append(obs.reward)
            risk = obs.context.risk_class.value if hasattr(obs.context.risk_class, "value") else str(obs.context.risk_class)
            key = f"risk:{risk}"
            segments.setdefault(key, []).append(obs.reward)

        metrics: dict[str, dict[str, float]] = {}
        for key, rewards in segments.items():
            arr = np.array(rewards, dtype=np.float64)
            metrics[key] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
                "count": float(len(arr)),
            }
        return metrics

    def _check_drift(self, observations: list[PolicyObservation]) -> str:
        if len(observations) < 10:
            return "none"
        rewards = [o.reward for o in observations[-20:]]
        arr = np.array(rewards, dtype=np.float64)
        if len(arr) > 1 and float(np.std(arr, ddof=1)) > 0.5:
            return "critical"
        return "none"
