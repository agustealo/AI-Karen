"""Governed verification-review receipts in Karen's canonical OutcomeStore.

This is an offline, review-authorized evidence adapter, not a second database,
an authentication boundary, a policy router, or an active learning executor.
The caller MUST supply a principal obtained from Karen's trusted auth layer.
Storage guards schema integrity, tenant scope and append-only uniqueness;
reviewer permission must be enforced before the strict atomic write.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.auth.principal import AuthenticatedPrincipal
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyObservation,
    VerificationAction,
)
from ai_karen_engine.core.intelligence.ml.policy_evaluation.validation import (
    validate_evaluated_policy_observations,
)
from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStore,
    OutcomeStoreError,
    PostgresOutcomeStore,
    get_outcome_store,
)

_SCHEMA = "ml_verification_review_v1"
_PERMISSION = "intelligence.ml.verification_review"
_ACTIONS = frozenset(item.value for item in VerificationAction)
_ALLOWED_SOURCES = frozenset({"human_review", "independent_test"})
_MAX_CASES = 500


class GovernedVerificationReviewEvidence:
    """Persist and re-read a reviewed, immutable decision-bound receipt pair."""

    def __init__(
        self,
        *,
        tenant_id: str,
        subject_user_id: str,
        store: OutcomeStore | None = None,
    ) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id == "default":
            raise ValueError("Verification review requires an explicit tenant")
        if not isinstance(subject_user_id, str) or not subject_user_id.strip():
            raise ValueError("Verification review requires an authenticated subject")
        self.tenant_id = tenant_id
        self.subject_user_id = subject_user_id
        self.store = store if store is not None else get_outcome_store()

    def _validate_observations(
        self, observations: Sequence[PolicyObservation],
    ) -> None:
        if not 1 <= len(observations) <= _MAX_CASES:
            raise ValueError("Verification review batch must have 1-500 cases")
        validate_evaluated_policy_observations(
            observations,
            tenant_id=self.tenant_id,
            decision_type=DecisionType.RESPOND_STRATEGY,
            domain="verification",
        )
        seen_need: set[str] = set()
        for observation in observations:
            if (
                set(observation.eligible_actions) != _ACTIONS
                or observation.context.risk_class not in {
                    ActionRiskClass.LOW, ActionRiskClass.MODERATE,
                }
                or not isinstance(observation.utility_policy_version, str)
                or not observation.utility_policy_version.strip()
            ):
                raise ValueError("Only low/moderate versioned verification decisions qualify")
            label_ref = observation.metadata.get("verification_label_ref")
            label_source = observation.metadata.get("verification_label_source")
            needed = observation.metadata.get("verification_needed")
            reward_ref = observation.metadata["reward_evidence_ref"]
            if (
                label_source not in _ALLOWED_SOURCES
                or not isinstance(needed, bool)
                or not isinstance(label_ref, str)
                or not 1 <= len(label_ref) <= 256
                or not label_ref.isascii()
                or not all(ch.isalnum() or ch in "-._:/" for ch in label_ref)
                or label_ref == reward_ref
                or label_ref in seen_need
            ):
                raise ValueError("Distinct independently reviewed verification label required")
            seen_need.add(label_ref)

    def _snapshot_sha256(self, observation: PolicyObservation) -> str:
        """Hash only the minimum evidence contract, never private prompt text."""
        payload = {
            "tenant_id": self.tenant_id,
            "subject_user_id": self.subject_user_id,
            "observation_id": observation.observation_id,
            "feature_snapshot_id": observation.context.feature_snapshot_id,
            "decision_type": observation.context.decision_type.value,
            "risk_class": observation.context.risk_class.value,
            "eligible_actions": observation.eligible_actions,
            "chosen_action": observation.chosen_action,
            "behavior_policy_id": observation.behavior_policy_id,
            "behavior_policy_version": observation.behavior_policy_version,
            "behavior_probabilities": observation.behavior_probabilities,
            "chosen_probability": observation.chosen_probability,
            "candidate_policy_id": observation.candidate_policy_id,
            "candidate_policy_version": observation.candidate_policy_version,
            "candidate_probabilities": observation.candidate_probabilities,
            "utility_policy_version": observation.utility_policy_version,
            "reward": observation.reward,
            "reward_evidence_type": observation.metadata["reward_evidence_type"],
            "reward_evidence_ref": observation.metadata["reward_evidence_ref"],
            "verification_needed": observation.metadata["verification_needed"],
            "verification_label_source": observation.metadata["verification_label_source"],
            "verification_label_ref": observation.metadata["verification_label_ref"],
        }
        snapshot = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_review_authority(
        reviewer: AuthenticatedPrincipal,
        tenant_id: str,
        subject_user_id: str,
    ) -> None:
        if not isinstance(reviewer, AuthenticatedPrincipal):
            raise PermissionError("A trusted authenticated reviewer principal is required")
        if (
            reviewer.tenant_id != tenant_id
            or reviewer.user_id == subject_user_id
            or reviewer.is_expired()
            or not reviewer.has_permission(_PERMISSION)
        ):
            raise PermissionError("Independent verification review permission denied")

    @staticmethod
    def _require_subject_authority(
        subject: AuthenticatedPrincipal,
        tenant_id: str,
        subject_user_id: str,
    ) -> None:
        if (
            not isinstance(subject, AuthenticatedPrincipal)
            or subject.tenant_id != tenant_id
            or subject.user_id != subject_user_id
            or subject.is_expired()
        ):
            raise PermissionError("Scoped subject evidence read permission denied")

    def _receipt(
        self,
        observation: PolicyObservation,
        *,
        reviewer_user_id: str,
        kind: str,
        digest: str,
    ) -> dict[str, Any]:
        metadata = observation.metadata
        if kind == "reward":
            reference = metadata["reward_evidence_ref"]
            source = metadata["reward_evidence_type"]
            value: bool | float = float(observation.reward)
        else:
            reference = metadata["verification_label_ref"]
            source = metadata["verification_label_source"]
            value = metadata["verification_needed"]
        return {
            "outcome_id": reference,
            "tenant_id": self.tenant_id,
            "user_id": self.subject_user_id,
            "source": "intelligence.ml",
            "decision_observation_id": observation.observation_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "schema_version": _SCHEMA,
                "evidence_kind": kind,
                "evidence_source": source,
                "evidence_ref": reference,
                "decision_observation_id": observation.observation_id,
                "observation_sha256": digest,
                "reviewer_user_id": reviewer_user_id,
                "utility_policy_version": observation.utility_policy_version,
                "value": value,
            },
        }

    async def record_review(
        self,
        observation: PolicyObservation,
        *,
        reviewer: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        """Only a separately authorized reviewer may atomically issue both receipts."""
        self._require_review_authority(
            reviewer, self.tenant_id, self.subject_user_id,
        )
        self._validate_observations([observation])
        digest = self._snapshot_sha256(observation)
        receipts = [
            self._receipt(
                observation, reviewer_user_id=reviewer.user_id,
                kind=kind, digest=digest,
            )
            for kind in ("reward", "verification_need")
        ]
        await self.store.save_unique_outcomes_async(receipts)
        return {
            "stored": True,
            "receipt_count": 2,
            "evidence_schema": _SCHEMA,
            "decision_observation_id": observation.observation_id,
        }

    async def require_persisted_reviews(
        self,
        observations: Sequence[PolicyObservation],
        *,
        subject: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        """Reconcile both independent receipts with exact frozen observations.

        Fail the *whole* study on missing, cross-tenant, replayed, tampered or
        mismatched records; never try a cached/non-durable fallback.
        """
        self._require_subject_authority(
            subject, self.tenant_id, self.subject_user_id,
        )
        self._validate_observations(observations)
        wanted: list[str] = []
        for observation in observations:
            wanted.extend((
                observation.metadata["reward_evidence_ref"],
                observation.metadata["verification_label_ref"],
            ))
        if len(set(wanted)) != len(wanted):
            raise ValueError("Review receipts must be globally distinct within a study")

        rows = await asyncio.to_thread(
            self.store.list_scoped_outcomes_by_ids,
            self.tenant_id,
            user_id=self.subject_user_id,
            source="intelligence.ml",
            outcome_ids=wanted,
        )
        if not isinstance(rows, list) or len(rows) != len(wanted):
            raise OutcomeStoreError("Incomplete governed verification receipts")
        indexed: dict[str, dict[str, Any]] = {}
        for receipt in rows:
            if not isinstance(receipt, dict):
                raise OutcomeStoreError("Malformed governed verification receipt")
            key = receipt.get("outcome_id")
            if key in indexed or key not in wanted:
                raise OutcomeStoreError("Duplicate or extraneous reviewed evidence")
            tenant, source = PostgresOutcomeStore._validated_identity(receipt)
            if (
                tenant != self.tenant_id
                or source != "intelligence.ml"
                or receipt.get("user_id") != self.subject_user_id
            ):
                raise PermissionError("Cross-principal verification evidence forbidden")
            indexed[key] = receipt

        reviewers: set[str] = set()
        for observation in observations:
            digest = self._snapshot_sha256(observation)
            for expected in (
                self._receipt(
                    observation, reviewer_user_id="", kind="reward", digest=digest,
                ),
                self._receipt(
                    observation, reviewer_user_id="", kind="verification_need",
                    digest=digest,
                ),
            ):
                actual = indexed[expected["outcome_id"]]
                actual_metadata = actual["metadata"]
                expected_metadata = expected["metadata"]
                for field in (
                    "schema_version", "evidence_kind", "evidence_source",
                    "evidence_ref", "decision_observation_id",
                    "observation_sha256", "utility_policy_version", "value",
                ):
                    if actual_metadata.get(field) != expected_metadata[field]:
                        raise OutcomeStoreError(
                            "Stored review does not match the frozen policy observation"
                        )
                reviewers.add(actual_metadata["reviewer_user_id"])
        return {
            "evidence_schema": _SCHEMA,
            "persisted_decision_count": len(observations),
            "persisted_receipt_count": len(rows),
            "reviewer_count": len(reviewers),
            "receipt_scope_verified": True,
            "policy_activated": False,
        }


__all__ = ["GovernedVerificationReviewEvidence"]
