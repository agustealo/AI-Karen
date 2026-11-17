"""KCM-02B3A: bounded, task-specific benchmark outcome observation.

Reuses the canonical ML benchmark receipt, current artifact registry and
principal-scoped OutcomeStore. A measured score is an observation of one
evaluated model, task, dataset and feature revision, not independent proof
of general intelligence, capability certification or permission to act.

The benchmark receipt is read twice around the awaited canonical outcome
read; an artifact or receipt removed during the query fails closed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from ai_karen_engine.config.learning import get_learning_settings
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import (
    BenchmarkCaseReceipt,
    EvaluationEvidenceStore,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)
_Z_95 = 1.959963984540054


class KcmBenchmarkAssessmentHealth(str, Enum):
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KcmBenchmarkTaskAssessment:
    tenant_id: str
    user_id: str
    health: KcmBenchmarkAssessmentHealth
    task: str
    model_id: str
    model_version: str
    feature_version: str
    dataset_version: str
    artifact_sha256: str
    receipt_id: str
    sample_count: int
    correct_count: int
    observed_fraction_correct: float | None
    descriptive_wilson_lower: float | None
    descriptive_wilson_upper: float | None
    evidence_sha256: str
    reason_codes: tuple[str, ...]
    scope: str = "user_benchmark_cohort"
    benchmark_provenance_verified: bool = False
    independent_trial_groups_verified: bool = False
    production_environment_verified: bool = False
    general_skill_certified: bool = False
    execution_authorized: bool = False
    training_authorized: bool = False
    # Conditions are issuer/corpus observations, never general skill grants.
    evaluated_at: datetime | None = None
    expires_at: datetime | None = None
    freshness_verified: bool = False
    artifact_architecture: str = ""
    curated_oracle_sha256: str = ""
    curated_oracle_source_verified: bool = False
    declared_group_count: int = 0
    runner_evaluation_started_at: datetime | None = None
    runner_evaluation_finished_at: datetime | None = None
    runner_execution_window_recorded: bool = False
    freshness_basis: str = "receipt_issuance_only"


def _wilson_interval(successes: int, count: int) -> tuple[float, float]:
    """Descriptive 95% Wilson score; assumes comparable independent cases.

    Without verified task-family independence this is **not** a calibrated
    population guarantee. KCM reports that limitation explicitly.
    """
    if count < 1 or not 0 <= successes <= count:
        raise ValueError("A nonempty, valid benchmark cohort is required")
    fraction = successes / count
    z2 = _Z_95 * _Z_95
    center = (fraction + z2 / (2 * count)) / (1 + z2 / count)
    half = (
        _Z_95
        * math.sqrt(
            fraction * (1.0 - fraction) / count
            + z2 / (4.0 * count * count)
        )
        / (1 + z2 / count)
    )
    return max(0.0, center - half), min(1.0, center + half)


class KcmBenchmarkTaskProjector:
    """One canonical benchmark cohort, one authenticated user and one model.

    All thresholds are caller-configured and validated at construction.
    The caller provides an authorized principal and trusted local registry
    location, not an untrusted URL or a model-generated benchmark summary.
    """

    def __init__(
        self,
        *,
        registry_dir: Path,
        minimum_cases: int,
        maximum_cases: int,
        store: OutcomeStore | None = None,
        max_evidence_age_seconds: int | None = None,
    ) -> None:
        if (
            type(minimum_cases) is not int
            or type(maximum_cases) is not int
            or not 1 <= minimum_cases <= maximum_cases <= 1000
        ):
            raise ValueError("KCM benchmark case bounds must satisfy 1 <= min <= max <= 1000")
        if not isinstance(registry_dir, Path):
            raise TypeError("Canonical ML registry path required")
        age_limit = (
            get_learning_settings().kcm_benchmark_max_evidence_age_seconds
            if max_evidence_age_seconds is None else max_evidence_age_seconds
        )
        if type(age_limit) is not int or not 1 <= age_limit <= 31_536_000:
            raise ValueError("KCM benchmark evidence age must be 1-31536000 seconds")
        self._max_evidence_age_seconds = age_limit
        self._directory = registry_dir
        self._minimum = minimum_cases
        self._maximum = maximum_cases
        self._store = store

    @staticmethod
    def _unavailable(
        *,
        tenant_id: str,
        user_id: str,
        task: PredictionTask,
        model_id: str,
        receipt_id: str,
        reason: str,
    ) -> KcmBenchmarkTaskAssessment:
        return KcmBenchmarkTaskAssessment(
            tenant_id=tenant_id,
            user_id=user_id,
            health=KcmBenchmarkAssessmentHealth.UNAVAILABLE,
            task=task.value,
            model_id=model_id,
            model_version="",
            feature_version="",
            dataset_version="",
            artifact_sha256="",
            receipt_id=receipt_id,
            sample_count=0,
            correct_count=0,
            observed_fraction_correct=None,
            descriptive_wilson_lower=None,
            descriptive_wilson_upper=None,
            evidence_sha256="",
            reason_codes=(reason,),
        )

    async def inspect(
        self,
        *,
        principal: AuthenticatedPrincipal,
        tenant_id: str,
        user_id: str,
        task: PredictionTask,
        model_id: str,
        receipt_id: str,
    ) -> KcmBenchmarkTaskAssessment:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or principal.is_expired()
            or not isinstance(tenant_id, str)
            or not tenant_id or tenant_id == "default"
            or not isinstance(user_id, str) or not user_id
            or principal.tenant_id != tenant_id
            or principal.user_id != user_id
        ):
            raise PermissionError("KCM task assessment requires the authenticated owner")
        if not isinstance(task, PredictionTask):
            raise ValueError("Canonical typed prediction task required")
        if not isinstance(model_id, str) or not 1 <= len(model_id) <= 256:
            raise ValueError("Registered model identity required")
        if not isinstance(receipt_id, str) or not 1 <= len(receipt_id) <= 128:
            raise ValueError("Exact benchmark receipt identity required")
        reject = lambda reason: self._unavailable(
            tenant_id=tenant_id, user_id=user_id, task=task,
            model_id=model_id, receipt_id=receipt_id, reason=reason,
        )
        try:
            if not self._directory.is_dir():
                return reject("canonical_benchmark_registry_unavailable")
            registry = MLModelRegistry(registry_dir=str(self._directory))
            manifest = registry.get(model_id)
            if manifest is None or manifest.purpose != task.value:
                return reject("benchmark_model_not_registered_for_task")
            evidence = EvaluationEvidenceStore(
                self._directory, create_if_missing=False,
            )
            receipt = evidence.read_case_receipt(
                manifest=manifest, tenant_id=tenant_id,
                receipt_id=receipt_id,
            )
            if receipt is None:
                return reject("benchmark_receipt_or_artifact_unavailable")
            if not self._minimum <= receipt.sample_count <= self._maximum:
                return reject("benchmark_cohort_outside_configured_bounds")

            observations = await GovernedMLLearningEvidence(
                tenant_id=tenant_id, user_id=user_id, store=self._store,
            ).load_verified(limit=self._maximum, task=task)

            # During the await the artifact can be replaced, revoked, or
            # deleted. Verify again using fresh registry + evidence reads.
            registry_after = MLModelRegistry(registry_dir=str(self._directory))
            current = registry_after.get(model_id)
            second = (
                evidence.read_case_receipt(
                    manifest=current, tenant_id=tenant_id,
                    receipt_id=receipt_id,
                )
                if current is not None else None
            )
            if second != receipt:
                return reject("benchmark_source_changed_during_read")
            now = datetime.now(timezone.utc)
            if receipt.evaluated_at is None:
                return reject("benchmark_issuer_timestamp_unavailable")
            if receipt.evaluated_at > now:
                return reject("benchmark_issuer_timestamp_in_future")
            # A newly issued receipt cannot refresh an older inference.
            # Historical observations remain explicitly issuer-age-only.
            freshness_reference = (
                receipt.runner_evaluation_finished_at
                if receipt.runner_evaluation_finished_at is not None
                else receipt.evaluated_at
            )
            expires_at = freshness_reference + timedelta(
                seconds=self._max_evidence_age_seconds,
            )
            if now >= expires_at:
                return reject("benchmark_evidence_expired")
            return self._measure(
                receipt=receipt, observations=observations,
                tenant_id=tenant_id, user_id=user_id,
                expires_at=expires_at,
                max_evidence_age_seconds=self._max_evidence_age_seconds,
                reject=reject,
            )
        except PermissionError:
            raise
        except Exception as exc:
            logger.warning(
                "kcm.benchmark_assessment_unavailable",
                extra={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return reject("benchmark_evidence_source_unavailable")

    @staticmethod
    def _measure(
        *,
        receipt: BenchmarkCaseReceipt,
        observations: list,
        tenant_id: str,
        user_id: str,
        expires_at: datetime | None,
        max_evidence_age_seconds: int,
        reject,
    ) -> KcmBenchmarkTaskAssessment:
        prefix = f"benchmark:{receipt.receipt_id}:"
        expected = dict(receipt.case_verdicts)
        by_hash: dict[str, bool] = {}
        for row in observations:
            ref = row.metadata.get("label_evidence_ref")
            if not isinstance(ref, str) or not ref.startswith(prefix):
                continue
            case_hash = ref[len(prefix):]
            if (
                case_hash not in expected
                or case_hash in by_hash
                or row.metadata.get("label_source") != "heldout_evaluation"
                or row.task != receipt.task
                or row.model_id != receipt.model_id
                or row.model_version != receipt.model_version
                or row.feature_version != receipt.feature_version
                or row.fallback_used
                or type(row.correct) is not bool
                or row.correct is not expected[case_hash]
            ):
                return reject("benchmark_case_identity_or_label_invalid")
            by_hash[case_hash] = row.correct

        if (
            by_hash != expected
            or len(by_hash) != receipt.sample_count
            or sum(by_hash.values()) != receipt.correct_count
        ):
            return reject("benchmark_case_cohort_incomplete_or_conflicting")
        lower, upper = _wilson_interval(receipt.correct_count, receipt.sample_count)
        lineage = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "task": receipt.task.value,
            "model": receipt.model_id,
            "model_version": receipt.model_version,
            "feature_version": receipt.feature_version,
            "artifact_hash": receipt.artifact_hash,
            "dataset_version": receipt.dataset_version,
            "receipt": receipt.receipt_id,
            "cases": sorted(by_hash.items()),
            "evaluated_at": receipt.evaluated_at.isoformat()
                if receipt.evaluated_at is not None else None,
            "artifact_architecture": receipt.artifact_architecture,
            "curated_oracle_sha256": receipt.curated_oracle_sha256,
            "declared_group_count": receipt.declared_group_count,
            "runner_evaluation_run_id": receipt.runner_evaluation_run_id,
            "runner_evaluation_started_at": (
                receipt.runner_evaluation_started_at.isoformat()
                if receipt.runner_evaluation_started_at is not None else None
            ),
            "runner_evaluation_finished_at": (
                receipt.runner_evaluation_finished_at.isoformat()
                if receipt.runner_evaluation_finished_at is not None else None
            ),
            # This is a policy-dependent diagnostic, not an off-host signature.
            "freshness_policy_version": "kcm_benchmark_evidence_age_v2",
            "freshness_max_age_seconds": max_evidence_age_seconds,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
        }
        digest = hashlib.sha256(
            json.dumps(lineage, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return KcmBenchmarkTaskAssessment(
            tenant_id=tenant_id,
            user_id=user_id,
            health=KcmBenchmarkAssessmentHealth.MEASURED,
            task=receipt.task.value,
            model_id=receipt.model_id,
            model_version=receipt.model_version,
            feature_version=receipt.feature_version,
            dataset_version=receipt.dataset_version,
            artifact_sha256=receipt.artifact_hash,
            receipt_id=receipt.receipt_id,
            sample_count=receipt.sample_count,
            correct_count=receipt.correct_count,
            observed_fraction_correct=receipt.correct_count / receipt.sample_count,
            descriptive_wilson_lower=lower,
            descriptive_wilson_upper=upper,
            evidence_sha256=digest,
            benchmark_provenance_verified=True,
            evaluated_at=receipt.evaluated_at,
            expires_at=expires_at,
            freshness_verified=expires_at is not None,
            artifact_architecture=receipt.artifact_architecture,
            curated_oracle_sha256=receipt.curated_oracle_sha256,
            curated_oracle_source_verified=bool(receipt.curated_oracle_sha256),
            declared_group_count=receipt.declared_group_count,
            runner_evaluation_started_at=receipt.runner_evaluation_started_at,
            runner_evaluation_finished_at=receipt.runner_evaluation_finished_at,
            runner_execution_window_recorded=(
                receipt.runner_evaluation_finished_at is not None
            ),
            freshness_basis=(
                "runner_observed_inference_end"
                if receipt.runner_evaluation_finished_at is not None
                else "receipt_issuance_only"
            ),
            reason_codes=(
                "runner_observed_inference_window"
                if receipt.runner_evaluation_finished_at is not None
                else "receipt_age_only_not_inference_recency",
                "task_and_model_specific_benchmark_only",
                "curated_oracle_source_verified"
                if receipt.curated_oracle_sha256
                else "oracle_source_not_verified",
                "freshness_window_verified",
                "declared_groups_not_independent",
                "case_independence_unverified",
                "production_conditions_unverified",
                "not_general_skill_certification",
            ),
        )


__all__ = [
    "KcmBenchmarkAssessmentHealth",
    "KcmBenchmarkTaskAssessment",
    "KcmBenchmarkTaskProjector",
]
