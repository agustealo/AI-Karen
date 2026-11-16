"""Shadow evaluation of verification effort through canonical OPE.

Verification is a response strategy, not a new provider router, cognitive
executive, or RuntimePolicy authority. This is observational research only:
the evaluation requires externally assessed outcomes and logged action
propensities. It does not promote or authorize a candidate strategy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_karen_engine.auth.principal import AuthenticatedPrincipal
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore
from ai_karen_engine.core.intelligence.ml.verification_review_evidence import (
    GovernedVerificationReviewEvidence,
)

from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyObservation,
    PromotionDecision,
    VerificationAction,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.validation import (
    validate_evaluated_policy_observations,
)

_POLICY_VERSION = "kcog_verification_effort_ope_v1"
_MIN_VERIFIED_SAMPLES = 100
_ACTIONS = frozenset(action.value for action in VerificationAction)
_LABEL_SOURCES = frozenset({"human_review", "independent_test"})


def evaluate_verification_effort_candidate(
    observations: Sequence[PolicyObservation],
    *,
    tenant_id: str,
    baseline_policy: Any,
    candidate_policy: Any,
    min_samples: int = _MIN_VERIFIED_SAMPLES,
) -> dict[str, Any]:
    """Score verification-vs-direct decisions using the existing OPE owner.

    This is strictly shadow-only. No exposure to high-risk/forbidden
    decisions, no inferred propensities, no automatic escalation changes, and
    no claims that a calibration score measures cognitive correctness.

    A reward receipt and *separate* verification-need judgement are required.
    Reported oververification/missed-verification rates describe logged
    choices, not a counterfactual effect of candidate policy deployment.
    """
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 100:
        raise ValueError("Verification policy evaluation requires at least 100 observations")

    # Authenticate/validate the principal even if the evidence is empty.
    validate_evaluated_policy_observations(
        observations,
        tenant_id=tenant_id,
        decision_type=DecisionType.RESPOND_STRATEGY,
        domain="verification",
    )
    if not observations:
        return {
            "policy_version": _POLICY_VERSION,
            "evaluation_mode": "shadow",
            "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
            "reason_codes": ["empty_verified_verification_decisions"],
            "eligible_count": 0,
            "policy_activated": False,
            "durable_review_receipts_verified": False,
        }

    verified_labels: set[str] = set()
    oververification_count = 0
    missed_verification_count = 0
    chosen_verification_count = 0
    for item in observations:
        if set(item.eligible_actions) != _ACTIONS:
            raise ValueError("Verification evaluation requires both authorized strategy alternatives")
        if item.context.risk_class not in {
            ActionRiskClass.LOW, ActionRiskClass.MODERATE,
        }:
            raise ValueError("High-risk verification must remain RuntimePolicy-governed")
        if not isinstance(item.utility_policy_version, str) or not item.utility_policy_version:
            raise ValueError("A versioned independent reward/utility policy is required")
        metadata = item.metadata
        label = metadata.get("verification_needed")
        label_source = metadata.get("verification_label_source")
        label_ref = metadata.get("verification_label_ref")
        if (
            not isinstance(label, bool)
            or label_source not in _LABEL_SOURCES
            or not isinstance(label_ref, str)
            or not 1 <= len(label_ref) <= 256
            or not label_ref.isascii()
            or not all(ch.isalnum() or ch in "-._:/" for ch in label_ref)
        ):
            raise ValueError("An independently evaluated verification-need label is required")
        if label_ref == metadata["reward_evidence_ref"]:
            raise ValueError("Verification label and reward require distinct evidence receipts")
        if label_ref in verified_labels:
            raise ValueError("Duplicate verification-need label is not independent evidence")
        verified_labels.add(label_ref)
        if item.chosen_action == VerificationAction.VERIFY_THEN_RESPOND.value:
            chosen_verification_count += 1
            if label is False:
                oververification_count += 1
        elif label is True:
            missed_verification_count += 1

    count = len(observations)
    observed = {
        "logged_verification_rate": chosen_verification_count / count,
        "logged_unnecessary_verification_rate": oververification_count / count,
        "logged_missed_verification_rate": missed_verification_count / count,
        "count": count,
    }
    if count < min_samples:
        return {
            "policy_version": _POLICY_VERSION,
            "evaluation_mode": "shadow",
            "promotion_decision": PromotionDecision.INSUFFICIENT_EVIDENCE.value,
            "reason_codes": ["insufficient_verified_verification_decisions"],
            "eligible_count": count,
            "observed_descriptive_rates": observed,
            "policy_activated": False,
        }

    # This analysis still requires logged policy propensities, overlap and
    # sensitivity review. Reuse the canonical IPS/SNIPS/DR and promotion
    # evaluation; never infer benefit from response completion alone.
    report = OfflinePolicyEvaluator(
        baseline_policy=baseline_policy,
        ope_min_samples=min_samples,
    ).evaluate(list(observations), candidate_policy=candidate_policy)
    # The original shadow entrypoint validates only caller-supplied labels.
    # It may compute descriptive OPE diagnostics, but a missing durable
    # independent review MUST NOT become policy-promotion evidence.
    unverified_decision = report.get(
        "promotion_decision", PromotionDecision.INSUFFICIENT_EVIDENCE.value,
    )
    authentic_decision = (
        PromotionDecision.INSUFFICIENT_EVIDENCE.value
        if unverified_decision == PromotionDecision.PROMOTION_ELIGIBLE.value
        else unverified_decision
    )
    reasons = list(report.get("reason_codes") or [])
    if unverified_decision == PromotionDecision.PROMOTION_ELIGIBLE.value:
        reasons.append("durable_review_receipts_missing")
    return {
        "policy_version": _POLICY_VERSION,
        "evaluation_mode": "shadow",
        "evaluation_id": report.get("evaluation_id"),
        "promotion_decision": authentic_decision,
        "reason_codes": reasons,
        "eligible_count": count,
        "durable_review_receipts_verified": False,
        "observed_descriptive_rates": observed,
        "estimates": report.get("estimates") or {},
        "overlap_diagnostics": report.get("overlap_diagnostics"),
        "segment_metrics": report.get("segment_metrics") or {},
        "drift_status": report.get("drift_status"),
        "policy_activated": False,
        "runtime_policy_approval_required": True,
    }


async def evaluate_verification_effort_with_durable_reviews(
    observations: Sequence[PolicyObservation],
    *,
    subject: AuthenticatedPrincipal,
    baseline_policy: Any,
    candidate_policy: Any,
    min_samples: int = _MIN_VERIFIED_SAMPLES,
    store: OutcomeStore | None = None,
) -> dict[str, Any]:
    """Shadow comparison only after both exact, durable review receipts match.

    Authenticated subject scope comes from the existing authorization
    boundary. A separate reviewer needs an independent permission to issue
    the receipts. No proxy identity, cache fallback or runtime activation.
    """
    if not isinstance(subject, AuthenticatedPrincipal) or subject.is_expired():
        raise PermissionError("Trusted, current subject principal is required")
    reviewed = GovernedVerificationReviewEvidence(
        tenant_id=subject.tenant_id,
        subject_user_id=subject.user_id,
        store=store,
    )
    evidence = await reviewed.require_persisted_reviews(
        observations, subject=subject,
    )
    result = evaluate_verification_effort_candidate(
        observations,
        tenant_id=subject.tenant_id,
        baseline_policy=baseline_policy,
        candidate_policy=candidate_policy,
        min_samples=min_samples,
    )
    result["durable_review_receipts_verified"] = True
    result["durable_review_provenance"] = evidence
    # An authenticated receipt pair alone is not an independently established
    # causal gain or an authorization to switch response strategies.
    result["policy_activated"] = False
    result["runtime_policy_approval_required"] = True
    return result
