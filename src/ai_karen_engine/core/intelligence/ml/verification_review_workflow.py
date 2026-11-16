"""Authenticated reviewer admission over *durable runtime* decision lineage.

This service owns review admission only. The runtime's canonical TrajectoryStore
owns decision-time observations. OutcomeStore owns immutable review receipts.
The HTTP caller supplies only independently judged labels and a decision ID,
never the policy propensities, eligible actions or frozen feature snapshots.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyObservation,
    VerificationAction,
)
from ai_karen_engine.core.intelligence.ml.verification_review_evidence import (
    GovernedVerificationReviewEvidence,
)
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore
from ai_karen_engine.core.runtime.trajectory.store import (
    TrajectoryStore,
    get_trajectory_store,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = logging.getLogger(__name__)

_SNAPSHOT_VERSION = "verification_policy_snapshot_v1"
_REVIEW_PERMISSION = "intelligence.ml.verification_review"
_ALLOWED_ACTIONS = frozenset(action.value for action in VerificationAction)


@dataclass(frozen=True, slots=True)
class ReviewJudgement:
    decision_observation_id: str
    subject_user_id: str
    reward: float
    verification_needed: bool

    def validate(self) -> None:
        if (
            not isinstance(self.decision_observation_id, str)
            or not 1 <= len(self.decision_observation_id) <= 256
            or not self.decision_observation_id.isascii()
            or any(ch not in "-._:/" and not ch.isalnum()
                   for ch in self.decision_observation_id)
        ):
            raise ValueError("Exact recorded decision identity is required")
        if not isinstance(self.subject_user_id, str) or not self.subject_user_id:
            raise ValueError("Subject identity is required")
        if (
            isinstance(self.reward, bool)
            or not isinstance(self.reward, (float, int))
            or not math.isfinite(self.reward)
            or not 0 <= self.reward <= 1
        ):
            raise ValueError("Reward must be a finite reviewed value between zero and one")
        if not isinstance(self.verification_needed, bool):
            raise ValueError("A boolean independent verification judgement is required")


class VerificationReviewWorkflow:
    """Resolve immutable recorded choices before admitting independent labels."""

    def __init__(
        self,
        *,
        lineage_store: TrajectoryStore | None = None,
        outcome_store: OutcomeStore | None = None,
    ) -> None:
        self._lineage_store = lineage_store if lineage_store is not None else get_trajectory_store()
        self._outcome_store = outcome_store

    async def submit(
        self,
        judgement: ReviewJudgement,
        *,
        reviewer: AuthenticatedPrincipal,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        judgement.validate()
        if not isinstance(reviewer, AuthenticatedPrincipal):
            raise PermissionError("Trusted reviewer identity required")
        if (
            reviewer.is_expired()
            or not reviewer.tenant_id
            or reviewer.tenant_id == "default"
            or reviewer.user_id == judgement.subject_user_id
            or not reviewer.has_permission(_REVIEW_PERMISSION)
        ):
            raise PermissionError("Independent review authorization denied")

        recorded = await asyncio.to_thread(
            self._lineage_store.get_decision_observation,
            judgement.decision_observation_id,
            tenant_id=reviewer.tenant_id,
        )
        if recorded is None:
            raise LookupError("No eligible recorded decision in this tenant")
        if (
            recorded.tenant_id != reviewer.tenant_id
            or recorded.user_id != judgement.subject_user_id
            or recorded.decision_observation_id != judgement.decision_observation_id
        ):
            raise LookupError("No eligible recorded decision for this subject")
        if (
            recorded.decision_type != DecisionType.RESPOND_STRATEGY.value
            or not recorded.ope_eligible
            or set(recorded.eligible_actions) != _ALLOWED_ACTIONS
            or set(recorded.candidate_actions) != _ALLOWED_ACTIONS
            or recorded.chosen_action not in _ALLOWED_ACTIONS
            or not recorded.trajectory_id
            or not recorded.feature_snapshot_id
        ):
            raise ValueError("Recorded decision is not verification-OPE eligible")

        features = await asyncio.to_thread(
            self._lineage_store.get_feature_snapshot,
            recorded.feature_snapshot_id,
            tenant_id=reviewer.tenant_id,
        )
        if features is None:
            raise ValueError("Decision-time feature snapshot is unavailable")
        if (
            features.tenant_id != reviewer.tenant_id
            or features.user_id != judgement.subject_user_id
            or features.trajectory_id != recorded.trajectory_id
            or features.feature_snapshot_id != recorded.feature_snapshot_id
        ):
            raise PermissionError("Decision feature snapshot provenance mismatch")

        snapshot = recorded.metadata.get("verification_policy_snapshot")
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {
                "schema_version", "candidate_policy_id", "candidate_policy_version",
                "candidate_probabilities", "risk_class", "utility_policy_version",
            }
            or snapshot.get("schema_version") != _SNAPSHOT_VERSION
            or not all(isinstance(snapshot.get(key), str) and snapshot[key].strip()
                       for key in (
                           "candidate_policy_id", "candidate_policy_version",
                           "utility_policy_version",
                       ))
            or not isinstance(snapshot.get("candidate_probabilities"), dict)
        ):
            # Never ask a mutable policy to rescore historical decisions.
            raise ValueError("Pinned decision-time candidate-policy evidence is missing")

        try:
            risk = ActionRiskClass(snapshot["risk_class"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Pinned risk classification is invalid") from exc
        if risk not in {ActionRiskClass.LOW, ActionRiskClass.MODERATE}:
            raise PermissionError("Review cannot weaken high-risk runtime policy")

        nonce = uuid.uuid4().hex
        label_metadata = {
            "reward_evidence_type": "human_review",
            "reward_evidence_ref": f"review:{nonce}:reward",
            "verification_label_source": "human_review",
            "verification_label_ref": f"review:{nonce}:need",
            "verification_needed": judgement.verification_needed,
        }
        observed = PolicyObservation(
            observation_id=recorded.decision_observation_id,
            context=PolicyContext(
                feature_snapshot_id=features.feature_snapshot_id,
                decision_type=DecisionType.RESPOND_STRATEGY,
                eligible_actions=list(recorded.eligible_actions),
                tenant_scope=reviewer.tenant_id,
                risk_class=risk,
                normalized_features={},
            ),
            eligible_actions=list(recorded.eligible_actions),
            chosen_action=recorded.chosen_action,
            behavior_policy_id=recorded.behavior_policy_id,
            behavior_policy_version=recorded.behavior_policy_version,
            behavior_probabilities=dict(recorded.action_probabilities),
            chosen_probability=recorded.chosen_probability,
            reward=float(judgement.reward),
            utility_policy_version=snapshot["utility_policy_version"],
            candidate_policy_id=snapshot["candidate_policy_id"],
            candidate_policy_version=snapshot["candidate_policy_version"],
            candidate_probabilities=dict(snapshot["candidate_probabilities"]),
            metadata=label_metadata,
        )
        owner = GovernedVerificationReviewEvidence(
            tenant_id=reviewer.tenant_id,
            subject_user_id=judgement.subject_user_id,
            store=self._outcome_store,
        )
        receipt = await owner.record_review(observed, reviewer=reviewer)

        # Durable, independently signed? No. The committed two-receipt
        # OutcomeStore ledger carries the reviewer ID and immutable fingerprint.
        # The standard audit logger records sanitized operational context.
        try:
            get_audit_logger().log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.SECURITY_EVENT,
                    severity=AuditSeverity.INFO,
                    message="verification_review_receipts_committed",
                    user_id=reviewer.user_id,
                    tenant_id=reviewer.tenant_id,
                    correlation_id=correlation_id,
                    metadata={
                        "decision_observation_id": judgement.decision_observation_id,
                        "subject_user_id": judgement.subject_user_id,
                        "receipt_count": 2,
                        "review_source": "human_review",
                        "policy_activated": False,
                    },
                )
            )
        except Exception:
            logger.exception(
                "verification_review.audit_logging_failed",
                extra={
                    "tenant_id": reviewer.tenant_id,
                    "decision_observation_id": judgement.decision_observation_id,
                },
            )
        return {
            **receipt,
            "evaluation_mode": "shadow",
            "policy_activated": False,
            "decision_provenance": "durable_runtime_lineage",
        }


__all__ = ["ReviewJudgement", "VerificationReviewWorkflow"]
