"""KCM-02B3C2A: scoped reviewer observation of an exact canonical oracle cohort.

Uses the current canonical benchmark receipt, KCM outcome projector and the
existing append-only tenant-scoped OutcomeStore. A reviewer acknowledgment
is NOT evidence of independent ground truth, leakage-free train/test splits,
statistically independent task families, or permission to act or train.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.config.learning import get_learning_settings
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import (
    CanonicalEvaluationCorpus,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import (
    EvaluationEvidenceStore,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.personalization.benchmark_task_assessment import (
    KcmBenchmarkAssessmentHealth,
    KcmBenchmarkTaskProjector,
)
from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStore,
    OutcomeStoreError,
    PostgresOutcomeStore,
    get_outcome_store,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)

_SCHEMA = "kcm_curated_oracle_reviewer_observation_v1"
_WITHDRAWAL_SCHEMA = "kcm_curated_oracle_reviewer_withdrawal_v1"
_PERMISSION = Permission.BENCHMARK_ORACLE_REVIEW.value
_SOURCE = "intelligence.ml"


@dataclass(frozen=True, slots=True)
class CuratedOracleReviewSnapshot:
    tenant_id: str
    user_id: str
    task: PredictionTask
    model_id: str
    model_version: str
    feature_version: str
    receipt_id: str
    sample_count: int
    curated_oracle_sha256: str
    group_membership_sha256: str
    declared_group_count: int
    snapshot_sha256: str
    runner_finished_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewedOracleObservation:
    tenant_id: str
    user_id: str
    model_id: str
    receipt_id: str
    reviewer_user_id: str
    reviewed_at: datetime
    exact_cohort_reviewer_acknowledged: bool
    curated_source_integrity_verified: bool
    group_membership_integrity_verified: bool
    independent_trial_groups_verified: bool = False
    independent_ground_truth_verified: bool = False
    training_data_disjointness_verified: bool = False
    production_environment_verified: bool = False
    general_skill_certified: bool = False
    execution_authorized: bool = False
    training_authorized: bool = False


class GovernedCuratedOracleReviewEvidence:
    """Append one reviewer observation for one live, user-scoped cohort.

    The reviewer cannot submit case IDs, source hashes, verdicts, task-group
    membership or benchmark scores; these are always recovered from canonical
    sources and rechecked after every awaited read/write. No new evidence store
    or training/admission authority is introduced.
    """

    def __init__(
        self, *, tenant_id: str, subject_user_id: str,
        registry_dir: Path, store: OutcomeStore | None = None,
        maximum_cases: int = 1000,
    ) -> None:
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or tenant_id == "default"
            or not isinstance(subject_user_id, str)
            or not subject_user_id.strip()
        ):
            raise ValueError("Explicit reviewer observation principal scope required")
        if not isinstance(registry_dir, Path):
            raise TypeError("Canonical registry directory is required")
        if type(maximum_cases) is not int or not 1 <= maximum_cases <= 1000:
            raise ValueError("Review cohort limit must be 1..1000")
        self._tenant = tenant_id
        self._user = subject_user_id
        self._directory = registry_dir
        self._store = store if store is not None else get_outcome_store()
        self._maximum = maximum_cases

    def _require_subject(self, principal: AuthenticatedPrincipal) -> None:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or principal.is_expired()
            or principal.tenant_id != self._tenant
            or principal.user_id != self._user
        ):
            raise PermissionError("Oracle observation requires authenticated subject")

    def _require_reviewer(self, principal: AuthenticatedPrincipal) -> None:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or principal.is_expired()
            or principal.tenant_id != self._tenant
            or principal.user_id == self._user
            or not principal.session_id
            or not principal.has_permission(_PERMISSION)
        ):
            raise PermissionError("Independent scoped oracle-review permission denied")

    def _snapshot(
        self, *, model_id: str, receipt_id: str,
    ) -> CuratedOracleReviewSnapshot | None:
        """Rebuild exact group mapping from CURRENT canonical corpus and receipt.

        This is a self-consistency check only. It does not independently
        establish task-family separation, contamination, or real oracle truth.
        """
        if (
            not isinstance(model_id, str)
            or not 1 <= len(model_id) <= 256
            or not isinstance(receipt_id, str)
            or not 1 <= len(receipt_id) <= 128
            or not self._directory.is_dir()
        ):
            return None
        model = MLModelRegistry(registry_dir=str(self._directory)).get(model_id)
        if model is None:
            return None
        receipt = EvaluationEvidenceStore(
            self._directory, create_if_missing=False,
        ).read_case_receipt(
            manifest=model, tenant_id=self._tenant, receipt_id=receipt_id,
        )
        if (
            receipt is None
            or not receipt.curated_oracle_sha256
            or not receipt.runner_evaluation_run_id
            or receipt.runner_evaluation_finished_at is None
            or receipt.sample_count > self._maximum
            or receipt.sample_count < 1
        ):
            return None
        age = get_learning_settings().kcm_benchmark_max_evidence_age_seconds
        now = datetime.now(timezone.utc)
        if (
            receipt.runner_evaluation_finished_at > now
            or now >= receipt.runner_evaluation_finished_at
            + timedelta(seconds=age)
        ):
            return None
        wanted = set(receipt.case_hashes)
        entries: dict[str, str | None] = {}
        for case in CanonicalEvaluationCorpus.get_cases(task=receipt.task):
            if case.dataset_version != receipt.dataset_version:
                continue
            hashed_id = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:24]
            if hashed_id not in wanted:
                continue
            if hashed_id in entries:
                return None
            group = case.evaluation_group_id
            if group is not None and (
                not isinstance(group, str)
                or not 1 <= len(group) <= 128
                or not group.isascii()
            ):
                return None
            entries[hashed_id] = group
        if set(entries) != wanted:
            return None
        groups = {value for value in entries.values() if value is not None}
        if len(groups) != receipt.declared_group_count:
            return None
        sorted_membership = sorted(entries.items())
        member_digest = hashlib.sha256(
            json.dumps(
                sorted_membership, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        identity = {
            "schema": _SCHEMA,
            "tenant_id": self._tenant,
            "user_id": self._user,
            "receipt_id": receipt.receipt_id,
            "model_id": receipt.model_id,
            "model_version": receipt.model_version,
            "feature_version": receipt.feature_version,
            "task": receipt.task.value,
            "artifact_sha256": receipt.artifact_hash,
            "dataset_version": receipt.dataset_version,
            "curated_oracle_sha256": receipt.curated_oracle_sha256,
            "group_membership_sha256": member_digest,
            "case_verdicts": receipt.case_verdicts,
            "runner_run_id": receipt.runner_evaluation_run_id,
            "runner_finished_at": receipt.runner_evaluation_finished_at.isoformat(),
            "sample_count": receipt.sample_count,
        }
        snapshot_sha = hashlib.sha256(
            json.dumps(
                identity, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return CuratedOracleReviewSnapshot(
            tenant_id=self._tenant,
            user_id=self._user,
            task=receipt.task,
            model_id=receipt.model_id,
            model_version=receipt.model_version,
            feature_version=receipt.feature_version,
            receipt_id=receipt.receipt_id,
            sample_count=receipt.sample_count,
            curated_oracle_sha256=receipt.curated_oracle_sha256,
            group_membership_sha256=member_digest,
            declared_group_count=receipt.declared_group_count,
            snapshot_sha256=snapshot_sha,
            runner_finished_at=receipt.runner_evaluation_finished_at,
        )

    @staticmethod
    def _outcome_id(
        tenant: str, user: str, receipt_id: str, *,
        phase: str = "proposed",
    ) -> str:
        # A deterministic pair per run enables strict append-only replay
        # denial without ever returning a tentative review as confirmed.
        if phase not in {"proposed", "confirmed"}:
            raise ValueError("Unknown KCM review phase")
        key = json.dumps(
            [tenant, user, receipt_id, phase],
            separators=(",", ":"), ensure_ascii=False,
        )
        return "kcm_curated_review_" + hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _withdrawal_id(tenant: str, user: str, receipt_id: str) -> str:
        proposed = GovernedCuratedOracleReviewEvidence._outcome_id(
            tenant, user, receipt_id,
        )
        return "kcm_curated_withdrawal_" + hashlib.sha256(
            (proposed + ":withdrawal").encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _principal_identity(principal: AuthenticatedPrincipal) -> tuple:
        return (
            principal.tenant_id, principal.user_id, principal.session_id,
            tuple(principal.roles), tuple(principal.permissions),
            principal.expires_at,
        )

    def _require_same_reviewer(
        self, reviewer: AuthenticatedPrincipal, authorized: tuple,
    ) -> None:
        self._require_reviewer(reviewer)
        if self._principal_identity(reviewer) != authorized:
            raise PermissionError("Reviewer authority changed during verification")

    def _require_same_subject(
        self, subject: AuthenticatedPrincipal, authorized: tuple,
    ) -> None:
        self._require_subject(subject)
        if self._principal_identity(subject) != authorized:
            raise PermissionError("Subject identity changed during review lookup")

    async def _require_measured(
        self, *, subject: AuthenticatedPrincipal,
        snapshot: CuratedOracleReviewSnapshot,
    ) -> None:
        result = await KcmBenchmarkTaskProjector(
            registry_dir=self._directory,
            minimum_cases=1,
            maximum_cases=self._maximum,
            store=self._store,
        ).inspect(
            principal=subject,
            tenant_id=self._tenant,
            user_id=self._user,
            task=snapshot.task,
            model_id=snapshot.model_id,
            receipt_id=snapshot.receipt_id,
        )
        if result.health is not KcmBenchmarkAssessmentHealth.MEASURED:
            raise OutcomeStoreError(
                "Current, exact scoped benchmark outcomes must be measured"
            )
        if (
            result.curated_oracle_sha256 != snapshot.curated_oracle_sha256
            or not result.runner_execution_window_recorded
        ):
            raise OutcomeStoreError("Canonical reviewed cohort provenance changed")

    async def record_review(
        self, *, subject: AuthenticatedPrincipal,
        reviewer: AuthenticatedPrincipal,
        model_id: str, receipt_id: str,
    ) -> ReviewedOracleObservation:
        """Append a proposal and a separately authorized confirmation receipt.

        If reviewer authorization fails during the first awaited persistence,
        only the proposal remains. Readers require the confirmed pair, so a
        denied request never leaves a consumable reviewed acknowledgment.
        """
        self._require_subject(subject)
        self._require_reviewer(reviewer)
        reviewer_authority = self._principal_identity(reviewer)
        subject_authority = self._principal_identity(subject)
        snapshot = self._snapshot(model_id=model_id, receipt_id=receipt_id)
        if snapshot is None:
            raise OutcomeStoreError("Current canonical oracle cohort unavailable")
        await self._require_measured(subject=subject, snapshot=snapshot)
        self._require_same_subject(subject, subject_authority)
        self._require_same_reviewer(reviewer, reviewer_authority)
        if self._snapshot(model_id=model_id, receipt_id=receipt_id) != snapshot:
            raise OutcomeStoreError("Oracle cohort drifted during outcome verification")

        proposed_id = self._outcome_id(self._tenant, self._user, receipt_id)
        now = datetime.now(timezone.utc)
        proposal = {
            "outcome_id": proposed_id,
            "tenant_id": self._tenant,
            "user_id": self._user,
            "source": _SOURCE,
            "recorded_at": now.isoformat(),
            "metadata": {
                "schema_version": _SCHEMA,
                "receipt_id": receipt_id,
                "model_id": model_id,
                "reviewer_user_id": reviewer.user_id,
                "reviewer_session_present": True,
                "reviewed_at": now.isoformat(),
                "exact_snapshot_sha256": snapshot.snapshot_sha256,
                "review_phase": "proposed",
                "proposal_outcome_id": proposed_id,
                "review_acknowledged": False,
            },
        }
        await self._store.save_unique_outcome_async(proposal)

        # An expired/changed reviewer during proposal persistence cannot
        # finalize it. An orphan proposal is intentionally non-consumable.
        self._require_same_subject(subject, subject_authority)
        self._require_same_reviewer(reviewer, reviewer_authority)
        if self._snapshot(model_id=model_id, receipt_id=receipt_id) != snapshot:
            raise OutcomeStoreError("Oracle cohort drifted before confirmation")

        # Authorization is checked immediately before the final append.
        # No post-confirmation reviewer rejection is permitted: it would
        # leave a completed receipt consumable after returning "denied".
        confirmed_at = datetime.now(timezone.utc)
        confirmed = {
            **proposal,
            "outcome_id": self._outcome_id(
                self._tenant, self._user, receipt_id, phase="confirmed",
            ),
            "recorded_at": confirmed_at.isoformat(),
            "metadata": {
                **proposal["metadata"],
                "reviewed_at": confirmed_at.isoformat(),
                "review_phase": "confirmed",
                "review_acknowledged": True,
            },
        }
        await self._store.save_unique_outcome_async(confirmed)

        # A store that falsely acknowledges writes must not report success.
        # Consumers independently reconcile both append-only records.
        persisted = await self.inspect_review(
            subject=subject, model_id=model_id, receipt_id=receipt_id,
        )
        if (
            persisted is None
            or persisted.reviewer_user_id != reviewer_authority[1]
            or persisted.reviewed_at != confirmed_at
        ):
            raise OutcomeStoreError("Reviewer observation was not durably reconciled")
        logger.info(
            "kcm.curated_oracle_review.recorded",
            extra={
                "tenant_id": self._tenant,
                "user_id": self._user,
                "reviewer_user_id": reviewer_authority[1],
                "model_id": model_id,
                "receipt_id": receipt_id,
                "review_kind": _SCHEMA,
            },
        )
        return persisted

    async def inspect_review(
        self, *, subject: AuthenticatedPrincipal,
        model_id: str, receipt_id: str,
    ) -> ReviewedOracleObservation | None:
        """Consume only a confirmed, scoped, unchanged original receipt pair."""
        self._require_subject(subject)
        subject_authority = self._principal_identity(subject)
        snapshot = self._snapshot(model_id=model_id, receipt_id=receipt_id)
        if snapshot is None:
            return None
        await self._require_measured(subject=subject, snapshot=snapshot)
        self._require_same_subject(subject, subject_authority)

        proposed_id = self._outcome_id(self._tenant, self._user, receipt_id)
        confirmed_id = self._outcome_id(
            self._tenant, self._user, receipt_id, phase="confirmed",
        )
        withdrawal_id = self._withdrawal_id(
            self._tenant, self._user, receipt_id,
        )
        rows = await asyncio.to_thread(
            self._store.list_scoped_outcomes_by_ids,
            self._tenant,
            user_id=self._user,
            source=_SOURCE,
            outcome_ids=[proposed_id, confirmed_id, withdrawal_id],
        )
        self._require_same_subject(subject, subject_authority)
        if (
            not isinstance(rows, list)
            or any(
                not isinstance(row, dict)
                or row.get("outcome_id") == withdrawal_id
                for row in rows
            )
            or len(rows) != 2
        ):
            # Even a corrupted withdrawal row blocks favorable evidence.
            return None
        if self._snapshot(model_id=model_id, receipt_id=receipt_id) != snapshot:
            return None
        indexed: dict[str, tuple[str, datetime]] = {}
        for row in rows:
            if not isinstance(row, dict):
                return None
            tenant, source = PostgresOutcomeStore._validated_identity(row)
            receipt_key = row.get("outcome_id")
            if (
                tenant != self._tenant or source != _SOURCE
                or row.get("user_id") != self._user
                or receipt_key in indexed
                or receipt_key not in {proposed_id, confirmed_id}
            ):
                raise PermissionError("Cross-principal oracle review receipt forbidden")
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                return None
            expected_phase = (
                "proposed" if receipt_key == proposed_id else "confirmed"
            )
            reviewer = metadata.get("reviewer_user_id")
            when = metadata.get("reviewed_at")
            if (
                metadata.get("schema_version") != _SCHEMA
                or metadata.get("receipt_id") != receipt_id
                or metadata.get("model_id") != model_id
                or metadata.get("exact_snapshot_sha256") != snapshot.snapshot_sha256
                or metadata.get("review_phase") != expected_phase
                or metadata.get("proposal_outcome_id") != proposed_id
                or metadata.get("review_acknowledged")
                    is not (expected_phase == "confirmed")
                or not isinstance(reviewer, str) or not reviewer.strip()
                or reviewer == self._user
                or metadata.get("reviewer_session_present") is not True
                or not isinstance(when, str)
            ):
                return None
            try:
                reviewed_at = datetime.fromisoformat(when.replace("Z", "+00:00"))
                raw_recorded = row.get("recorded_at")
                recorded_at = (
                    raw_recorded if isinstance(raw_recorded, datetime)
                    else datetime.fromisoformat(
                        str(raw_recorded).replace("Z", "+00:00")
                    )
                )
            except (TypeError, ValueError):
                return None
            if (
                reviewed_at.utcoffset() is None
                or recorded_at.utcoffset() is None
                or recorded_at.astimezone(timezone.utc)
                    != reviewed_at.astimezone(timezone.utc)
                or reviewed_at > datetime.now(timezone.utc)
                or reviewed_at < snapshot.runner_finished_at
            ):
                return None
            indexed[receipt_key] = (reviewer, reviewed_at)
        proposed_reviewer, proposed_at = indexed[proposed_id]
        confirmed_reviewer, confirmed_at = indexed[confirmed_id]
        if (
            proposed_reviewer != confirmed_reviewer
            or confirmed_at < proposed_at
        ):
            return None

        # This final awaited query can overlap with subject logout, expiry,
        # tenant changes, or source revocation. Recheck principal after it.
        try:
            await self._require_measured(subject=subject, snapshot=snapshot)
        except OutcomeStoreError:
            return None
        self._require_same_subject(subject, subject_authority)
        if self._snapshot(model_id=model_id, receipt_id=receipt_id) != snapshot:
            return None
        # Re-read withdrawal after the last awaited cohort check. A parallel
        # revocation that committed while numeric outcomes were being
        # verified must not be ignored by the final observation.
        withdrawn = await asyncio.to_thread(
            self._store.list_scoped_outcomes_by_ids,
            self._tenant,
            user_id=self._user,
            source=_SOURCE,
            outcome_ids=[withdrawal_id],
        )
        self._require_same_subject(subject, subject_authority)
        # An empty exact-scoped list proves absence. A missing/malformed
        # store response is *not* evidence that withdrawal never occurred.
        if not isinstance(withdrawn, list) or withdrawn:
            return None
        if self._snapshot(model_id=model_id, receipt_id=receipt_id) != snapshot:
            return None
        return ReviewedOracleObservation(
            tenant_id=self._tenant,
            user_id=self._user,
            model_id=model_id,
            receipt_id=receipt_id,
            reviewer_user_id=confirmed_reviewer,
            reviewed_at=confirmed_at,
            exact_cohort_reviewer_acknowledged=True,
            curated_source_integrity_verified=True,
            group_membership_integrity_verified=True,
        )


    async def withdraw_review(
        self, *, subject: AuthenticatedPrincipal,
        reviewer: AuthenticatedPrincipal,
        model_id: str, receipt_id: str,
    ) -> str:
        """Permanently withdraw the original reviewer's acknowledged cohort.

        This is a restrictive, append-only outcome, not a training or skill
        authorization. It requires the exact original reviewer and a current
        authenticated tenant-scoped reviewer principal. Pending or expired
        cohorts do not qualify for this narrow self-withdrawal operation.
        """
        self._require_subject(subject)
        self._require_reviewer(reviewer)
        subject_identity = self._principal_identity(subject)
        reviewer_identity = self._principal_identity(reviewer)
        reviewed = await self.inspect_review(
            subject=subject, model_id=model_id, receipt_id=receipt_id,
        )
        self._require_same_subject(subject, subject_identity)
        self._require_same_reviewer(reviewer, reviewer_identity)
        if reviewed is None:
            raise OutcomeStoreError("No current confirmed reviewer evidence to withdraw")
        if reviewed.reviewer_user_id != reviewer.user_id:
            raise PermissionError("Only the original reviewer may withdraw the receipt")
        snapshot = self._snapshot(model_id=model_id, receipt_id=receipt_id)
        if snapshot is None:
            raise OutcomeStoreError("Original oracle snapshot no longer available")
        withdrawal_id = self._withdrawal_id(
            self._tenant, self._user, receipt_id,
        )
        confirmed_id = self._outcome_id(
            self._tenant, self._user, receipt_id, phase="confirmed",
        )
        when = datetime.now(timezone.utc).isoformat()
        payload = {
            "outcome_id": withdrawal_id,
            "tenant_id": self._tenant,
            "user_id": self._user,
            "source": _SOURCE,
            "recorded_at": when,
            "metadata": {
                "schema_version": _WITHDRAWAL_SCHEMA,
                "receipt_id": receipt_id,
                "model_id": model_id,
                "reviewer_user_id": reviewer.user_id,
                "review_confirmed_outcome_id": confirmed_id,
                "review_snapshot_sha256": snapshot.snapshot_sha256,
                "revoked_at": when,
                "reason_code": "reviewer_withdrawal",
                "review_withdrawn": True,
            },
        }
        self._require_same_subject(subject, subject_identity)
        self._require_same_reviewer(reviewer, reviewer_identity)
        await self._store.save_unique_outcome_async(payload)
        # A restrictive revocation that commits despite a lost response
        # continues to block evidence. Never roll back an issuer withdrawal
        # because the session expired after commit.
        rows = await asyncio.to_thread(
            self._store.list_scoped_outcomes_by_ids,
            self._tenant,
            user_id=self._user,
            source=_SOURCE,
            outcome_ids=[withdrawal_id],
        )
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or rows[0].get("outcome_id") != withdrawal_id
            or rows[0].get("metadata") != payload["metadata"]
        ):
            raise OutcomeStoreError("Reviewer withdrawal not durably reconciled")
        PostgresOutcomeStore._validated_identity(rows[0])
        logger.info(
            "kcm.curated_oracle_review.withdrawn",
            extra={
                "tenant_id": self._tenant,
                "user_id": self._user,
                "reviewer_user_id": reviewer_identity[1],
                "model_id": model_id,
                "receipt_id": receipt_id,
                "review_kind": _WITHDRAWAL_SCHEMA,
            },
        )
        return withdrawal_id


__all__ = [
    "CuratedOracleReviewSnapshot",
    "ReviewedOracleObservation",
    "GovernedCuratedOracleReviewEvidence",
]
