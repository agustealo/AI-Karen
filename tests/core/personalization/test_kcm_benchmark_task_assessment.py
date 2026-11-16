"""KCM-02B3A: canonical benchmark provenance is not general mastery.

These tests use an actual SQLite benchmark receipt, a registered hashed
candidate artifact, and the existing InMemoryOutcomeStore as isolated
test-only implementation of the canonical scoped OutcomeStore contract.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest, ModelStatus, Prediction, PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkResult, PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import (
    EvaluationEvidenceStore,
)
from ai_karen_engine.core.intelligence.ml.online_learning import MLOutcomeRecord
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.personalization.benchmark_task_assessment import (
    KcmBenchmarkAssessmentHealth,
    KcmBenchmarkTaskProjector,
)
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
OTHER_TENANT = "33333333-3333-4333-8333-333333333333"
OTHER_USER = "44444444-4444-4444-8444-444444444444"
TASK = PredictionTask.INTENT
VERSION = "v3"
FEATURE = "features-2"
DATASET = "benchmark-v7"


def identity(tenant: str = TENANT, user: str = USER):
    return AuthenticatedPrincipal(tenant_id=tenant, user_id=user)


def model_id(tenant: str = TENANT) -> str:
    return (
        "tenant-"
        + hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:16]
        + "-intent-proof"
    )


def outcome(
    case: int, model: MLModelManifest, *, correct: bool,
    prediction_feature: str | None = None,
) -> PredictionOutcome:
    prediction = Prediction(
        task=TASK,
        label="verified-expected" if correct else "different",
        model_id=model.model_id,
        model_version=model.model_version,
        feature_version=prediction_feature or model.feature_version,
        probability=0.8,
        confidence=0.8,
        fallback_used=False,
    )
    return PredictionOutcome(
        case_id=f"distinct-benchmark-case-{case}",
        task=TASK,
        prediction=prediction,
        expected_label="verified-expected",
        correct=correct,
        raw_probability=0.8,
        calibrated_probability=0.8,
        latency_ms=10,
        fallback_used=False,
    )


async def fixture(
    root: Path,
    *,
    verdicts: tuple[bool, ...] = (True, True, False),
    prediction_feature: str | None = None,
):
    artifact = root / "actual-model.bin"
    artifact.write_bytes(b"trusted-model-artifact-for-scoped-tests")
    data = artifact.read_bytes()
    manifest = MLModelManifest(
        model_id=model_id(),
        purpose=TASK.value,
        architecture="trained",
        artifact_path=str(artifact),
        artifact_hash=hashlib.sha256(data).hexdigest(),
        model_version=VERSION,
        feature_version=FEATURE,
        status=ModelStatus.CANDIDATE.value,
    )
    registry = MLModelRegistry(registry_dir=str(root))
    registry.register(manifest)
    benchmark = BenchmarkResult(
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        task=TASK,
        dataset_version=DATASET,
        sample_count=len(verdicts),
        metrics={},
        latency_p50_ms=10,
        latency_p95_ms=10,
        error_count=0,
        fallback_count=0,
        abstention_count=0,
        outcomes=[
            outcome(
                index, manifest, correct=correct,
                prediction_feature=prediction_feature,
            )
            for index, correct in enumerate(verdicts)
        ],
    )
    receipts = EvaluationEvidenceStore(root)
    receipt_id = receipts._record(manifest, benchmark)
    store = InMemoryOutcomeStore()
    governed = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    reviewed: list[tuple[MLOutcomeRecord, str, str]] = []
    for i, item in enumerate(benchmark.outcomes):
        ref = (
            f"benchmark:{receipt_id}:"
            + hashlib.sha256(item.case_id.encode("utf-8")).hexdigest()[:24]
        )
        record = MLOutcomeRecord(
            outcome_id=f"verified-benchmark-outcome-{i}",
            task=TASK, model_id=manifest.model_id,
            model_version=manifest.model_version,
            feature_version=manifest.feature_version,
            predicted_label="", expected_label="",
            correct=item.correct, raw_probability=0.8,
            calibrated_probability=0.8, confidence=0.8,
            latency_ms=10, fallback_used=False,
            calibration_error=0.2 if item.correct else 0.8,
        )
        reviewed.append((record, "heldout_evaluation", ref))
    await governed.record_verified_batch(reviewed)
    return manifest, receipt_id, store, artifact


async def inspect(
    root: Path,
    manifest: MLModelManifest,
    receipt_id: str,
    store: InMemoryOutcomeStore,
    *,
    principal: AuthenticatedPrincipal | None = None,
    tenant: str = TENANT,
    user: str = USER,
    min_cases: int = 1,
    max_cases: int = 30,
):
    return await KcmBenchmarkTaskProjector(
        registry_dir=root,
        minimum_cases=min_cases,
        maximum_cases=max_cases,
        store=store,
    ).inspect(
        principal=principal or identity(),
        tenant_id=tenant,
        user_id=user,
        task=TASK,
        model_id=manifest.model_id,
        receipt_id=receipt_id,
    )


@pytest.mark.asyncio
async def test_real_registered_receipt_and_scoped_case_cohort_is_measured(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.task == TASK.value
    assert result.model_id == manifest.model_id
    assert result.model_version == VERSION
    assert result.feature_version == FEATURE
    assert result.dataset_version == DATASET
    assert result.artifact_sha256 == manifest.artifact_hash
    assert result.sample_count == 3
    assert result.correct_count == 2
    assert result.observed_fraction_correct == pytest.approx(2 / 3)
    assert 0 < result.descriptive_wilson_lower < 2 / 3
    assert 2 / 3 < result.descriptive_wilson_upper <= 1
    assert len(result.evidence_sha256) == 64
    assert result.benchmark_provenance_verified is True
    assert result.independent_trial_groups_verified is False
    assert result.production_environment_verified is False
    assert result.general_skill_certified is False
    assert result.execution_authorized is False
    assert result.training_authorized is False


@pytest.mark.asyncio
async def test_same_receipt_is_deterministic(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    first = await inspect(tmp_path, manifest, receipt, store)
    second = await inspect(tmp_path, manifest, receipt, store)
    assert first == second


@pytest.mark.asyncio
async def test_legacy_feature_receipt_survives_but_is_not_kcm_evidence(tmp_path):
    manifest, receipt, store, _ = await fixture(
        tmp_path, prediction_feature="legacy-predictor-default-v1",
    )
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        data = db.execute(
            "SELECT evidence_json FROM benchmark_receipts WHERE receipt_id=?",
            (receipt,),
        ).fetchone()[0]
    assert "kcm_case_receipt_version" not in data
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_missing_case_fails_closed_instead_of_inflated_success(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    store._records.pop()
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.observed_fraction_correct is None
    assert result.sample_count == 0
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_tampered_case_label_does_not_match_canonical_receipt(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    store._records[0]["metadata"]["correct"] = False
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.observed_fraction_correct is None


@pytest.mark.asyncio
async def test_swapping_per_case_labels_with_same_total_is_rejected(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    # Reversing a correct and incorrect label leaves 2/3 accuracy unchanged,
    # but changes which task case passed the independent benchmark.
    store._records[0]["metadata"]["correct"] = False
    store._records[2]["metadata"]["correct"] = True
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.observed_fraction_correct is None


@pytest.mark.asyncio
async def test_relabeling_and_fallback_cannot_enter_heldout_cohort(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    store._records[0]["metadata"]["label_source"] = "human_review"
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE

    store._records[0]["metadata"]["label_source"] = "heldout_evaluation"
    store._records[0]["metadata"]["fallback_used"] = True
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_artifact_mutation_invalidates_benchmark_evidence(tmp_path):
    manifest, receipt, store, artifact = await fixture(tmp_path)
    artifact.write_bytes(b"modified-model-artifact")
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.benchmark_provenance_verified is False


@pytest.mark.asyncio
async def test_retired_model_is_not_a_current_task_capability(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    registry.register(replace(manifest, status=ModelStatus.RETIRED.value))
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_old_receipt_without_case_membership_remains_noncertifying(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    import json

    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        row = db.execute(
            "SELECT evidence_json FROM benchmark_receipts WHERE receipt_id=?",
            (receipt,),
        ).fetchone()
        obj = json.loads(row[0])
        obj.pop("case_hashes")
        db.execute(
            "UPDATE benchmark_receipts SET evidence_json=? WHERE receipt_id=?",
            (json.dumps(obj), receipt),
        )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_wrong_tenant_and_user_identity_are_blocked(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    invalid = (
        (identity(OTHER_TENANT), TENANT, USER),
        (identity(TENANT, OTHER_USER), TENANT, USER),
        (identity(), OTHER_TENANT, USER),
        (identity(), TENANT, OTHER_USER),
        (
            AuthenticatedPrincipal(
                tenant_id=TENANT, user_id=USER,
                expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            TENANT, USER,
        ),
        ({"tenant_id": TENANT, "user_id": USER}, TENANT, USER),
    )
    for principal, tenant, user in invalid:
        with pytest.raises(PermissionError):
            await inspect(
                tmp_path, manifest, receipt, store,
                principal=principal, tenant=tenant, user=user,
            )
    other = await inspect(
        tmp_path, manifest, receipt, store,
        principal=identity(TENANT, OTHER_USER),
        tenant=TENANT, user=OTHER_USER,
    )
    assert other.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_unknown_tenant_model_prefix_rejected(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    outcome = await inspect(
        tmp_path, manifest, receipt, store,
        principal=identity(OTHER_TENANT, OTHER_USER),
        tenant=OTHER_TENANT, user=OTHER_USER,
    )
    assert outcome.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_minimum_sample_budget_does_not_invent_skill(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    result = await inspect(
        tmp_path, manifest, receipt, store,
        min_cases=4, max_cases=10,
    )
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_whole_case_cohort_must_fit_limit(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    result = await inspect(
        tmp_path, manifest, receipt, store,
        min_cases=1, max_cases=2,
    )
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_deleted_receipt_is_not_available_after_scope_read(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        db.execute("DELETE FROM benchmark_receipts WHERE receipt_id=?", (receipt,))
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_duplicate_case_receipt_is_rejected(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    store._records[1]["metadata"]["label_evidence_ref"] = (
        store._records[0]["metadata"]["label_evidence_ref"]
    )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_wrong_model_and_feature_revision_is_not_comparable(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    store._records[0]["metadata"]["model_version"] = "v999"
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    store._records[0]["metadata"]["model_version"] = VERSION
    store._records[0]["metadata"]["feature_version"] = "feature-drift"
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_fixture_result_with_no_correct_cases_is_not_automatically_certified(tmp_path):
    manifest, receipt, store, _ = await fixture(
        tmp_path, verdicts=(False, False, False),
    )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.correct_count == 0
    assert result.observed_fraction_correct == 0
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_missing_evidence_read_does_not_create_sqlite_or_registry(tmp_path):
    empty = tmp_path / "already-configured-empty-registry"
    empty.mkdir()
    view = KcmBenchmarkTaskProjector(
        registry_dir=empty,
        minimum_cases=1, maximum_cases=10,
        store=InMemoryOutcomeStore(),
    )
    result = await view.inspect(
        principal=identity(), tenant_id=TENANT, user_id=USER,
        task=TASK, model_id=model_id(), receipt_id="absent-receipt",
    )
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert not (empty / "benchmark_evidence.sqlite3").exists()

    absent = tmp_path / "unknown-registry"
    missing = await KcmBenchmarkTaskProjector(
        registry_dir=absent,
        minimum_cases=1, maximum_cases=10,
        store=InMemoryOutcomeStore(),
    ).inspect(
        principal=identity(), tenant_id=TENANT, user_id=USER,
        task=TASK, model_id=model_id(), receipt_id="absent-receipt",
    )
    assert missing.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert not absent.exists()


def test_benchmark_bounds_are_explicit_and_validated(tmp_path):
    for minimum, maximum in ((0, 10), (10, 9), (1, 1001), (True, 2)):
        with pytest.raises(ValueError):
            KcmBenchmarkTaskProjector(
                registry_dir=tmp_path,
                minimum_cases=minimum,
                maximum_cases=maximum,
            )
    with pytest.raises(TypeError):
        KcmBenchmarkTaskProjector(
            registry_dir=str(tmp_path),
            minimum_cases=1,
            maximum_cases=10,
        )
