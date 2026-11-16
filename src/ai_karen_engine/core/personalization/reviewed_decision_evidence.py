"""KCM-02B2: user-scoped, independently reviewed decision evidence.

This is an advisory, read-only projection of Karen's *existing* governed
verification-policy review receipts. It neither certifies a general skill nor
converts a reward, user preference, or runtime success into mastery.

Authority remains with the canonical runtime TrajectoryStore and OutcomeStore,
and the existing GovernedVerificationReviewEvidence reconciler verifies both
receipts against frozen decision-time evidence. No new evidence registry,
training worker, execution permission, or memory store is introduced.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    PolicyObservation,
)
from ai_karen_engine.core.intelligence.ml.verification_review_evidence import (
    GovernedVerificationReviewEvidence,
)
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)

_SCHEMA = "ml_verification_review_v1"
_MAX_CASES = 500


class KcmDecisionEvidenceHealth(str, Enum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KcmReviewedDecisionEvidence:
    """Only evaluated shadow-policy decisions, never cross-user Karen mastery."""

    tenant_id: str
    user_id: str
    health: KcmDecisionEvidenceHealth
    domain: str
    evaluation_mode: str
    decision_count: int
    reviewed_receipt_count: int
    distinct_reviewer_count: int
    mean_reviewed_reward: float | None
    judged_verification_needed_count: int
    evidence_sha256: str
    reason_codes: tuple[str, ...]
    scope: str = "user"
    capability_certified: bool = False
    execution_authorized: bool = False
    policy_activated: bool = False
    training_authorized: bool = False


class KcmReviewedDecisionProjector:
    """Read verified decision receipts with authenticated user and tenant scope.

    The supplied observations MUST originate from the trusted runtime lineage
    coordinator. The existing reconciler compares each observation with its
    persisted reviewer-issued receipts, so caller-provided rewards alone have
    no evidentiary value.

    The only verifier is Karen's canonical governed review authority. An
    optional store may be injected by trusted composition (in-memory in
    isolated tests); caller-supplied verification summaries are never trusted.
    """

    def __init__(
        self,
        *,
        store: OutcomeStore | None = None,
        max_decisions: int,
    ) -> None:
        if type(max_decisions) is not int or not 1 <= max_decisions <= _MAX_CASES:
            raise ValueError("KCM decision evidence budget must be 1-500")
        self._store = store
        self._max_decisions = max_decisions

    @staticmethod
    def _unavailable(
        *,
        tenant_id: str,
        user_id: str,
        reason: str,
    ) -> KcmReviewedDecisionEvidence:
        return KcmReviewedDecisionEvidence(
            tenant_id=tenant_id,
            user_id=user_id,
            health=KcmDecisionEvidenceHealth.UNAVAILABLE,
            domain="verification_policy",
            evaluation_mode="shadow",
            decision_count=0,
            reviewed_receipt_count=0,
            distinct_reviewer_count=0,
            mean_reviewed_reward=None,
            judged_verification_needed_count=0,
            evidence_sha256="",
            reason_codes=(reason,),
        )

    async def inspect(
        self,
        *,
        subject: AuthenticatedPrincipal,
        tenant_id: str,
        user_id: str,
        observations: Sequence[PolicyObservation],
    ) -> KcmReviewedDecisionEvidence:
        """Reconcile exact reviewed observations and return only bounded facts.

        Missing, stale, conflicting or tampered reviews never generate a
        partial-success capability claim. Credentials come from the trusted
        authentication runtime, not request payloads.
        """
        if not isinstance(subject, AuthenticatedPrincipal):
            raise PermissionError("Authenticated principal required for KCM read")
        if (
            subject.is_expired()
            or not isinstance(tenant_id, str)
            or not isinstance(user_id, str)
            or not tenant_id.strip()
            or tenant_id == "default"
            or not user_id.strip()
            or subject.tenant_id != tenant_id
            or subject.user_id != user_id
        ):
            raise PermissionError("KCM evidence principal scope mismatch")
        if (
            not isinstance(observations, (list, tuple))
            or not 1 <= len(observations) <= self._max_decisions
            or any(not isinstance(row, PolicyObservation) for row in observations)
        ):
            return self._unavailable(
                tenant_id=tenant_id,
                user_id=user_id,
                reason="decision_evidence_budget_or_type_invalid",
            )

        # Pin the caller's mutable objects *before* the awaited source read.
        # The canonical reconciler verifies this exact copy against immutable
        # stored labels and the original frozen decision feature digest.
        frozen = tuple(copy.deepcopy(row) for row in observations)
        authority = GovernedVerificationReviewEvidence(
            tenant_id=tenant_id,
            subject_user_id=user_id,
            store=self._store,
        )
        try:
            receipt = await authority.require_persisted_reviews(
                frozen, subject=subject,
            )
        except Exception as exc:
            logger.warning(
                "kcm.reviewed_decision_evidence_unavailable",
                extra={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "case_count": len(frozen),
                    "error_type": type(exc).__name__,
                },
            )
            return self._unavailable(
                tenant_id=tenant_id,
                user_id=user_id,
                reason="reviewed_decision_receipts_unavailable",
            )

        if (
            not isinstance(receipt, dict)
            or receipt.get("evidence_schema") != _SCHEMA
            or receipt.get("persisted_decision_count") != len(frozen)
            or receipt.get("persisted_receipt_count") != 2 * len(frozen)
            or type(receipt.get("receipt_scope_verified")) is not bool
            or receipt["receipt_scope_verified"] is not True
            or receipt.get("policy_activated") is not False
            or type(receipt.get("reviewer_count")) is not int
            or not 1 <= receipt["reviewer_count"] <= len(frozen)
        ):
            return self._unavailable(
                tenant_id=tenant_id,
                user_id=user_id,
                reason="reviewed_decision_proof_invalid",
            )

        # The validated reward is a *judged score for the frozen decision*,
        # not a success percentage, calibrated competence or training label.
        rewards: list[float] = []
        needed = 0
        lineage: list[dict[str, str]] = []
        seen_observations: set[str] = set()
        for row in frozen:
            if (
                not isinstance(row.observation_id, str)
                or not row.observation_id
                or row.observation_id in seen_observations
            ):
                return self._unavailable(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    reason="reviewed_decision_duplicate_observation",
                )
            seen_observations.add(row.observation_id)
            label = row.metadata["verification_needed"]
            if type(label) is not bool:
                return self._unavailable(
                    tenant_id=tenant_id, user_id=user_id,
                    reason="reviewed_decision_label_invalid",
                )
            rewards.append(float(row.reward))
            needed += int(label)
            lineage.append({
                "observation_id": row.observation_id,
                "reward_ref": row.metadata["reward_evidence_ref"],
                "need_ref": row.metadata["verification_label_ref"],
                "policy": row.behavior_policy_id,
                "policy_version": row.behavior_policy_version,
                "utility_policy_version": row.utility_policy_version,
            })

        lineage.sort(key=lambda item: item["observation_id"])
        digest = hashlib.sha256(
            json.dumps(
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "schema": _SCHEMA,
                    "observations": lineage,
                },
                sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return KcmReviewedDecisionEvidence(
            tenant_id=tenant_id,
            user_id=user_id,
            health=KcmDecisionEvidenceHealth.VERIFIED,
            domain="verification_policy",
            evaluation_mode="shadow",
            decision_count=len(frozen),
            reviewed_receipt_count=2 * len(frozen),
            distinct_reviewer_count=receipt["reviewer_count"],
            mean_reviewed_reward=sum(rewards) / len(rewards),
            judged_verification_needed_count=needed,
            evidence_sha256=digest,
            reason_codes=("task_specific_reviews_only", "not_skill_certification"),
        )


__all__ = [
    "KcmDecisionEvidenceHealth",
    "KcmReviewedDecisionEvidence",
    "KcmReviewedDecisionProjector",
]
