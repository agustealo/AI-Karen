"""Policy promotion gates and rollback.

Evidence-based promotion decisions with atomic promotion/rollback contracts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    PromotionBlockReason,
    PromotionDecision,
    PolicyEstimate,
    PolicyObservation,
    PolicyStatus,
)

logger = logging.getLogger(__name__)


class PromotionConfig:
    def __init__(
        self,
        min_samples: int = 100,
        min_confidence: float = 0.95,
        require_dr: bool = True,
        require_snips: bool = True,
        max_importance_weight: float = 100.0,
        min_gain: float = 0.0,
        max_segment_regression: float = 0.05,
        max_estimator_disagreement: float = 0.1,
    ) -> None:
        self.min_samples = min_samples
        self.min_confidence = min_confidence
        self.require_dr = require_dr
        self.require_snips = require_snips
        self.max_importance_weight = max_importance_weight
        self.min_gain = min_gain
        self.max_segment_regression = max_segment_regression
        self.max_estimator_disagreement = max_estimator_disagreement


@dataclass(slots=True)
class PromotionEvidence:
    evaluation_id: str
    policy_id: str
    policy_version: str
    baseline_policy_id: str
    baseline_policy_version: str
    estimates: dict[str, PolicyEstimate] = field(default_factory=dict)
    overlap_diagnostics: Any = None
    sample_count: int = 0
    segment_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    drift_status: str = "none"
    latency_regression: float = 0.0
    cost_regression: float = 0.0
    fallback_regression: float = 0.0
    safety_regression: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyPromotionDecision:
    decision: PromotionDecision
    reason_codes: list[PromotionBlockReason] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    promotion_id: str | None = None
    evidence: PromotionEvidence | None = None


def evaluate_promotion(
    evidence: PromotionEvidence,
    config: PromotionConfig,
) -> PolicyPromotionDecision:
    reasons: list[PromotionBlockReason] = []
    messages: list[str] = []

    if evidence.sample_count < config.min_samples:
        reasons.append(PromotionBlockReason.INSUFFICIENT_SAMPLES)
        messages.append(f"sample_count={evidence.sample_count} < {config.min_samples}")

    if evidence.overlap_diagnostics and not evidence.overlap_diagnostics.is_supported:
        reasons.append(PromotionBlockReason.POOR_OVERLAP)
        messages.append("overlap diagnostics unsupported")

    if evidence.drift_status == "critical":
        reasons.append(PromotionBlockReason.DRIFT_DETECTED)
        messages.append("critical drift detected during evaluation window")

    if evidence.safety_regression:
        reasons.append(PromotionBlockReason.SAFETY_REVIEW_REQUIRED)
        messages.append("safety regression detected")

    baseline_estimates = {k: v for k, v in evidence.estimates.items() if "baseline" in k}
    candidate_estimates = {k: v for k, v in evidence.estimates.items() if "baseline" not in k}

    if not candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("no candidate estimates available")

    for name, est in candidate_estimates.items():
        if est.lower_bound < config.min_gain:
            pass

    if config.require_dr and "dr" not in candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("doubly robust estimate missing")

    if config.require_snips and "snips" not in candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("snips estimate missing")

    if len(candidate_estimates) >= 2:
        vals = [e.estimate for e in candidate_estimates.values()]
        if max(vals) - min(vals) > config.max_estimator_disagreement:
            reasons.append(PromotionBlockReason.ESTIMATOR_DISAGREEMENT)
            messages.append("estimator disagreement exceeds threshold")

    for segment, metrics in evidence.segment_metrics.items():
        regression = metrics.get("regression", 0.0)
        if regression > config.max_segment_regression:
            reasons.append(PromotionBlockReason.SEGMENT_REGRESSION)
            messages.append(f"segment regression in {segment}")
            break

    if evidence.latency_regression > config.max_segment_regression:
        reasons.append(PromotionBlockReason.LATENCY_REGRESSION)
        messages.append("latency regression detected")

    if evidence.cost_regression > config.max_segment_regression:
        reasons.append(PromotionBlockReason.COST_REGRESSION)
        messages.append("cost regression detected")

    if evidence.fallback_regression > config.max_segment_regression:
        reasons.append(PromotionBlockReason.FALLBACK_REGRESSION)
        messages.append("fallback regression detected")

    if reasons:
        return PolicyPromotionDecision(
            decision=PromotionDecision.PROMOTION_BLOCKED,
            reason_codes=reasons,
            messages=messages,
            evidence=evidence,
        )

    return PolicyPromotionDecision(
        decision=PromotionDecision.PROMOTION_ELIGIBLE,
        reason_codes=[],
        messages=[],
        evidence=evidence,
    )
