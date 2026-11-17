"""Authenticated reviewer admission over *durable runtime* decision lineage.

This service owns review admission only. The runtime's canonical TrajectoryStore
owns decision-time observations. OutcomeStore owns immutable review receipts.
The HTTP caller supplies only independently judged labels and a decision ID,
never the policy propensities, eligible actions or frozen feature snapshots.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
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
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore, get_outcome_store
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

        # B2C3A: a frozen OPE decision is not evidence that its selected
        # action actually executed or that its transcript was committed.
        # Load the existing runtime truth, in the same reviewer tenant,
        # before accepting any independently judged quality label.
        trajectory = await asyncio.to_thread(
            self._lineage_store.get,
            recorded.trajectory_id,
            tenant_id=reviewer.tenant_id,
        )
        if trajectory is None:
            raise ValueError("Selected runtime execution evidence is unavailable")
        if not (
            trajectory.trajectory_id == recorded.trajectory_id
            and trajectory.tenant_id == reviewer.tenant_id
            and trajectory.user_id == judgement.subject_user_id
            and trajectory.request_id
            and trajectory.request_id == features.request_id
            and trajectory.correlation_id
            and trajectory.correlation_id == features.correlation_id
            and trajectory.policy_decision_id
            and features.metadata.get("policy_decision_id")
            == trajectory.policy_decision_id
            and trajectory.execution_status == "success"
            and trajectory.completed_at is not None
            and trajectory.error_code is None
            and trajectory.actual_provider
            and trajectory.actual_model
            and trajectory.degraded_mode is False
            and trajectory.fallback_level == 0
            and not trajectory.plugin_actions
            and trajectory.executed_topology == (
                "direct" if recorded.chosen_action == "respond_direct"
                else "reasoning"
            )
        ):
            raise ValueError("Completed selected runtime trajectory is unverified")

        # Canonical OutcomeStore owns the immutable execution observation.
        # Neither caller metadata nor a generated model answer can stand in
        # for the original persisted outcome and typed gateway provenance.
        outcome_store = self._outcome_store or get_outcome_store()
        observed_outcomes = await asyncio.to_thread(
            outcome_store.get_for_trajectory,
            recorded.trajectory_id,
            tenant_id=reviewer.tenant_id,
        )
        if not isinstance(observed_outcomes, list):
            raise ValueError("Selected execution outcome readback is unavailable")
        matching = [
            row for row in observed_outcomes
            if isinstance(row, dict)
            and row.get("source") == "runtime.execution"
            and row.get("decision_observation_id")
            == recorded.decision_observation_id
        ]
        if len(matching) != 1:
            raise ValueError("Exactly one selected execution receipt is required")
        outcome = matching[0]
        outcome_meta = outcome.get("metadata")
        selected = (
            outcome_meta.get("selected_strategy_execution")
            if isinstance(outcome_meta, dict) else None
        )
        if not (
            outcome.get("trajectory_id") == recorded.trajectory_id
            and outcome.get("tenant_id") == reviewer.tenant_id
            and outcome.get("user_id") == judgement.subject_user_id
            and outcome.get("request_id") == trajectory.request_id
            and outcome.get("correlation_id") == trajectory.correlation_id
            and outcome.get("session_id") == trajectory.session_id
            and outcome.get("conversation_id") == trajectory.conversation_id
            and outcome.get("status") == "success"
            and outcome.get("response_completed") is True
            and outcome.get("persistence_success") is True
            and outcome.get("fallback_count") == 0
            and isinstance(outcome_meta, dict)
            and outcome_meta.get("transcript_persistence_status")
            in {"persisted", "already_persisted"}
            and outcome_meta.get("actual_provider") == trajectory.actual_provider
            and outcome_meta.get("actual_model") == trajectory.actual_model
            and type(outcome_meta.get("model_calls")) is int
            and outcome_meta["model_calls"] >= 1
            and outcome_meta.get("tool_calls") == 0
            and isinstance(selected, dict)
            and selected.get("schema_version") == "selected_strategy_execution_v1"
            and selected.get("selected_action") == recorded.chosen_action
            and selected.get("policy_decision_id") == trajectory.policy_decision_id
            and selected.get("policy_version") == recorded.behavior_policy_version
            and selected.get("status") == "selected_runtime_path_observed"
            and selected.get("provider_receipt_observed") is True
            and selected.get("response_completed") is True
            and selected.get("transcript_durable") is True
            and selected.get("actual_provider") == trajectory.actual_provider
            and selected.get("actual_model") == trajectory.actual_model
            and selected.get("execution_observation_only") is True
            and selected.get("independent_verification_proven") is False
            and selected.get("dual_action_eligibility_established") is False
            and selected.get("randomized_selection") is False
            and selected.get("ope_eligible") is False
        ):
            # This is not an outcome or reward, only a selected path
            # provenance gate. Independent accuracy remains the reviewer
            # judgement stored separately by the original receipt owner.
            raise ValueError("Durable selected execution receipt is unverified")

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

        # Stable, domain-separated IDs prevent different labels being
        # appended for the same decision after a replay or concurrent review.
        identity = "\\x1f".join(
            (reviewer.tenant_id, judgement.subject_user_id, recorded.decision_observation_id)
        )
        receipt_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        label_metadata = {
            "reward_evidence_type": "human_review",
            "reward_evidence_ref": f"review:v1:{receipt_key}:reward",
            "verification_label_source": "human_review",
            "verification_label_ref": f"review:v1:{receipt_key}:need",
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
