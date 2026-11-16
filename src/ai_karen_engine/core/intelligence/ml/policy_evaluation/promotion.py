"""Evidence-based promotion gate for evaluated decision policies.

This gate consumes off-policy estimates and diagnostics. It recommends whether
a candidate policy has sufficient evidence for promotion; it does not activate
policies, authorize runtime behavior, or bypass RuntimePolicy/CORTEX.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from datetime import datetime, timezone
from typing import Any

from .contracts import PolicyEstimate, PromotionBlockReason, PromotionDecision


@dataclass(slots=True)
class PromotionConfig:
    min_samples: int = 100
    min_confidence: float = 0.95
    require_dr: bool = True
    require_snips: bool = True
    max_importance_weight: float = 100.0
    min_gain: float = 0.0
    max_segment_regression: float = 0.05
    max_estimator_disagreement: float = 0.1


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

    # A missing overlap report is missing evidence, not positive support.
    # An eligible policy must have actual target-action overlap and a
    # nonzero effective sample, including for deterministic targets.
    overlap = evidence.overlap_diagnostics
    if overlap is None:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("overlap diagnostics missing")
    elif (
        not overlap.is_supported
        or not math.isfinite(overlap.effective_sample_size)
        or overlap.effective_sample_size <= 0
        or not math.isfinite(overlap.coverage)
        or overlap.coverage < 1.0
        or bool(overlap.unsupported_actions)
        or not math.isfinite(overlap.minimum_propensity)
        or overlap.minimum_propensity <= 0
        or not math.isfinite(overlap.maximum_importance_weight)
        or overlap.maximum_importance_weight > config.max_importance_weight
    ):
        reasons.append(PromotionBlockReason.POOR_OVERLAP)
        messages.append("overlap diagnostics unsupported")

    if evidence.drift_status == "critical":
        reasons.append(PromotionBlockReason.DRIFT_DETECTED)
        messages.append("critical drift detected during evaluation window")

    if evidence.safety_regression:
        reasons.append(PromotionBlockReason.SAFETY_REVIEW_REQUIRED)
        messages.append("safety regression detected")

    candidate_estimates = {
        name: estimate
        for name, estimate in evidence.estimates.items()
        if "baseline" not in name
    }
    if not candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("no candidate estimates available")

    if config.require_dr and "dr" not in candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("doubly robust estimate missing")

    if config.require_snips and "snips" not in candidate_estimates:
        reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
        messages.append("snips estimate missing")

    # A positive candidate policy value is NOT proof of gain over the
    # active baseline. Require the same estimator on the same logged sample
    # window and a conservative separation of reported confidence bounds.
    # This is a screening rule, not a formal paired-difference confidence
    # interval. The runtime still owns any activation decision.
    for name, estimate in candidate_estimates.items():
        baseline = evidence.estimates.get(f"baseline_{name}")
        if baseline is None:
            reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
            messages.append(f"{name} baseline-relative estimate missing")
        else:
            fields = (
                estimate.estimate, estimate.lower_bound, estimate.upper_bound,
                estimate.confidence_level, estimate.effective_sample_size,
                baseline.estimate, baseline.lower_bound, baseline.upper_bound,
                baseline.confidence_level, baseline.effective_sample_size,
            )
            if (
                any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in fields
                )
                or estimate.lower_bound > estimate.upper_bound
                or baseline.lower_bound > baseline.upper_bound
                or not estimate.lower_bound <= estimate.estimate <= estimate.upper_bound
                or not baseline.lower_bound <= baseline.estimate <= baseline.upper_bound
                or estimate.sample_count != evidence.sample_count
                or baseline.sample_count != evidence.sample_count
                or estimate.effective_sample_size <= 0
                or baseline.effective_sample_size <= 0
                or baseline.confidence_level < config.min_confidence
            ):
                reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
                messages.append(f"{name} baseline comparison is unverified or invalid")
            elif estimate.lower_bound - baseline.upper_bound <= config.min_gain:
                reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
                messages.append(
                    f"{name} conservative gain lower bound does not beat baseline"
                )

        if estimate.confidence_level < config.min_confidence:
            reasons.append(PromotionBlockReason.CONFIDENCE_TOO_LOW)
            messages.append(
                f"{name} confidence={estimate.confidence_level:.3f} < {config.min_confidence:.3f}"
            )
        if estimate.lower_bound < config.min_gain:
            reasons.append(PromotionBlockReason.INSUFFICIENT_EVIDENCE)
            messages.append(
                f"{name} lower_bound={estimate.lower_bound:.4f} < min_gain={config.min_gain:.4f}"
            )
        if estimate.clipped_weight_rate > 0.25:
            reasons.append(PromotionBlockReason.POOR_OVERLAP)
            messages.append(
                f"{name} clipped_weight_rate={estimate.clipped_weight_rate:.3f} is too high"
            )

    if len(candidate_estimates) >= 2:
        values = [estimate.estimate for estimate in candidate_estimates.values()]
        if max(values) - min(values) > config.max_estimator_disagreement:
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
            reason_codes=list(dict.fromkeys(reasons)),
            messages=messages,
            evidence=evidence,
        )

    return PolicyPromotionDecision(
        decision=PromotionDecision.PROMOTION_ELIGIBLE,
        evidence=evidence,
    )
