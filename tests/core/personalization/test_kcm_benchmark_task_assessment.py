"""KCM-02B3A: canonical benchmark provenance is not general mastery.

These tests use an actual SQLite benchmark receipt, a registered hashed
candidate artifact, and the existing InMemoryOutcomeStore as isolated
test-only implementation of the canonical scoped OutcomeStore contract.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest, ModelStatus, Prediction, PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkConfig, BenchmarkResult, EvaluationCase, PredictionOutcome,
    evaluation_case_sha256,
)
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import (
    CanonicalEvaluationCorpus,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import (
    EvaluationEvidenceStore,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
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
    oracle_case: EvaluationCase | None = None,
) -> PredictionOutcome:
    prediction = Prediction(
        task=TASK,
        label=(
            oracle_case.expected_label if correct else "incorrect-canonical-label"
        ) if oracle_case else ("verified-expected" if correct else "different"),
        model_id=model.model_id,
        model_version=model.model_version,
        feature_version=prediction_feature or model.feature_version,
        probability=0.8,
        confidence=0.8,
        fallback_used=False,
    )
    return PredictionOutcome(
        case_id=oracle_case.case_id if oracle_case else f"distinct-benchmark-case-{case}",
        task=TASK,
        prediction=prediction,
        expected_label=oracle_case.expected_label if oracle_case else "verified-expected",
        expected_value=oracle_case.expected_value if oracle_case else None,
        correct=correct,
        raw_probability=0.8,
        calibrated_probability=0.8,
        latency_ms=10,
        fallback_used=False,
        evaluated_case_sha256=(
            evaluation_case_sha256(oracle_case) or ""
        ) if oracle_case else "",
    )


async def fixture(
    root: Path,
    *,
    verdicts: tuple[bool, ...] = (True, True, False),
    prediction_feature: str | None = None,
    use_canonical_curated_oracles: bool = False,
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
    canonical_cases = (
        CanonicalEvaluationCorpus.get_cases(task=TASK)[:len(verdicts)]
        if use_canonical_curated_oracles else []
    )
    if use_canonical_curated_oracles:
        assert len(canonical_cases) == len(verdicts)
    benchmark = BenchmarkResult(
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        task=TASK,
        dataset_version=(
            CanonicalEvaluationCorpus.DATASET_VERSION
            if use_canonical_curated_oracles else DATASET
        ),
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
                oracle_case=canonical_cases[index]
                    if use_canonical_curated_oracles else None,
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
    max_evidence_age_seconds: int | None = None,
):
    return await KcmBenchmarkTaskProjector(
        registry_dir=root,
        minimum_cases=min_cases,
        maximum_cases=max_cases,
        store=store,
        max_evidence_age_seconds=max_evidence_age_seconds,
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
    with pytest.raises(PermissionError, match="tenant mismatch"):
        await inspect(
            tmp_path, manifest, receipt, store,
            principal=identity(OTHER_TENANT, OTHER_USER),
            tenant=OTHER_TENANT, user=OTHER_USER,
        )


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


@pytest.mark.asyncio
async def test_actual_canonical_curated_oracle_snapshot_is_verified_not_independent(tmp_path):
    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    result = await inspect(
        tmp_path, manifest, receipt, store,
        max_evidence_age_seconds=120,
    )
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.curated_oracle_source_verified is True
    assert len(result.curated_oracle_sha256) == 64
    assert result.declared_group_count == 0
    assert result.evaluated_at is not None
    assert result.expires_at is not None
    assert result.expires_at > result.evaluated_at
    assert result.freshness_verified is True
    assert result.artifact_architecture == "trained"
    assert result.independent_trial_groups_verified is False
    assert result.production_environment_verified is False
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_declared_correctness_not_scored_by_canonical_evaluator_is_not_oracle_proof(
    tmp_path, monkeypatch,
):
    from ai_karen_engine.core.intelligence.ml.evaluation import runner as runner_module

    original = runner_module.BenchmarkRunner._is_correct
    monkeypatch.setattr(
        runner_module.BenchmarkRunner, "_is_correct",
        lambda self, case, prediction: False,
    )
    # The canonical scoring rule disagrees with the injected 'correct'
    # flags. A durable baseline evaluation receipt is still allowed,
    # but it cannot gain verified curated oracle provenance.
    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    monkeypatch.setattr(runner_module.BenchmarkRunner, "_is_correct", original)
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.curated_oracle_source_verified is False
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_custom_corpus_reusing_ids_with_changed_input_is_not_canonical(
    tmp_path,
):
    from ai_karen_engine.core.intelligence.ml.evaluation.runner import (
        BenchmarkRunner,
    )
    from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
        BenchmarkConfig,
    )
    import json

    manifest, _, _, _ = await fixture(tmp_path)
    original = CanonicalEvaluationCorpus.get_cases(task=TASK)[0]
    altered = replace(
        original,
        input_text=(
            original.input_text + " Answer: " + original.expected_label
        ),
        features=dict(original.features),
    )

    class AlteredCorpus(CanonicalEvaluationCorpus):
        @classmethod
        def get_cases(cls, **kwargs):
            return [altered]

    class RealPredictor:
        def predict(self, features):
            return Prediction(
                task=TASK,
                label=original.expected_label,
                model_id=manifest.model_id,
                model_version=manifest.model_version,
                feature_version=manifest.feature_version,
                probability=0.9,
                confidence=0.9,
            )

    outcome_result = await BenchmarkRunner(
        corpus=AlteredCorpus(),
    ).run(
        RealPredictor(),
        BenchmarkConfig(
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            task=TASK,
            dataset_version=CanonicalEvaluationCorpus.DATASET_VERSION,
        ),
    )
    assert outcome_result.sample_count == 1
    assert outcome_result.outcomes[0].correct is True
    assert outcome_result.outcomes[0].evaluated_case_sha256 == evaluation_case_sha256(altered)
    assert evaluation_case_sha256(altered) != evaluation_case_sha256(original)

    receipt = EvaluationEvidenceStore(tmp_path)._record(
        manifest, outcome_result,
    )
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        payload = json.loads(db.execute(
            "SELECT evidence_json FROM benchmark_receipts WHERE receipt_id=?",
            (receipt,),
        ).fetchone()[0])
    assert "kcm_curated_oracle_version" not in payload
    assert "curated_oracle_sha256" not in payload


@pytest.mark.asyncio
async def test_canonical_oracle_edit_invalidates_existing_provenance(
    tmp_path, monkeypatch,
):
    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    original = CanonicalEvaluationCorpus.get_cases(task=TASK)
    monkeypatch.setattr(
        CanonicalEvaluationCorpus, "get_cases",
        classmethod(lambda cls, **kwargs: [
            replace(original[0], expected_label="tampered-expected-oracle"),
            *original[1:],
        ]),
    )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.curated_oracle_source_verified is False
    assert result.observed_fraction_correct is None


@pytest.mark.asyncio
async def test_canonical_curated_case_group_claim_cannot_infer_independence(
    tmp_path, monkeypatch,
):
    original = CanonicalEvaluationCorpus.get_cases(task=TASK)
    monkeypatch.setattr(
        CanonicalEvaluationCorpus, "get_cases",
        classmethod(lambda cls, **kwargs: [
            replace(case, evaluation_group_id="unreviewed-group")
            for case in original
        ]),
    )
    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.declared_group_count == 1
    assert result.independent_trial_groups_verified is False
    assert result.general_skill_certified is False


@pytest.mark.asyncio
async def test_expired_benchmark_is_unavailable_without_fabricated_zero(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        db.execute(
            "UPDATE benchmark_receipts SET created_at=? WHERE receipt_id=?",
            ("2020-01-01 00:00:00", receipt),
        )
    result = await inspect(
        tmp_path, manifest, receipt, store,
        max_evidence_age_seconds=300,
    )
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert result.observed_fraction_correct is None
    assert "benchmark_evidence_expired" in result.reason_codes
    assert not result.general_skill_certified


@pytest.mark.asyncio
async def test_future_dated_benchmark_is_not_credible(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        db.execute(
            "UPDATE benchmark_receipts SET created_at=? WHERE receipt_id=?",
            ("2099-01-01 00:00:00", receipt),
        )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert "benchmark_issuer_timestamp_in_future" in result.reason_codes


@pytest.mark.asyncio
async def test_canonical_default_evidence_age_is_enforced(tmp_path):
    from ai_karen_engine.config.learning import get_learning_settings

    manifest, receipt, store, _ = await fixture(tmp_path)
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert result.freshness_verified is True
    assert result.evaluated_at is not None
    assert result.expires_at is not None
    assert (
        result.expires_at - result.evaluated_at
    ).total_seconds() == get_learning_settings().kcm_benchmark_max_evidence_age_seconds
    assert "freshness_window_verified" in result.reason_codes
    assert result.curated_oracle_source_verified is False


@pytest.mark.asyncio
async def test_curated_digest_tamper_invalidates_receipt(tmp_path):
    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    import json
    with sqlite3.connect(tmp_path / "benchmark_evidence.sqlite3") as db:
        payload = json.loads(db.execute(
            "SELECT evidence_json FROM benchmark_receipts WHERE receipt_id=?",
            (receipt,),
        ).fetchone()[0])
        payload["curated_oracle_sha256"] = "0" * 64
        db.execute(
            "UPDATE benchmark_receipts SET evidence_json=? WHERE receipt_id=?",
            (json.dumps(payload), receipt),
        )
    result = await inspect(tmp_path, manifest, receipt, store)
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE


def test_invalid_configured_age_budget_rejected(tmp_path):
    for value in (0, -1, True, 1.5, "3600", 31_536_001):
        with pytest.raises(ValueError, match="age"):
            KcmBenchmarkTaskProjector(
                registry_dir=tmp_path,
                minimum_cases=1, maximum_cases=10,
                max_evidence_age_seconds=value,
            )


def test_central_learning_config_rejects_invalid_evidence_ttl(monkeypatch):
    from ai_karen_engine.config.learning import LearningSettings

    assert LearningSettings().kcm_benchmark_max_evidence_age_seconds == 2_592_000
    for bad in (0, -1, 31_536_001, True, 1.5):
        with pytest.raises(ValueError, match="evidence age"):
            LearningSettings(kcm_benchmark_max_evidence_age_seconds=bad)
    monkeypatch.setenv("KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS", "180")
    settings = LearningSettings()
    settings.apply_env_overrides()
    assert settings.kcm_benchmark_max_evidence_age_seconds == 180
    monkeypatch.setenv("KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS", "wrong")
    with pytest.raises(ValueError, match="numeric"):
        LearningSettings().apply_env_overrides()
    monkeypatch.setenv("KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS", "0")
    with pytest.raises(ValueError, match="evidence age"):
        LearningSettings().apply_env_overrides()


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


async def _actual_runner_result(manifest: MLModelManifest) -> BenchmarkResult:
    """Real canonical runner, exact curated case and typed predictor output."""
    case = CanonicalEvaluationCorpus.get_cases(task=TASK)[0]

    class ExactTaskPredictor:
        def predict(self, features):
            assert features.text == case.input_text
            return Prediction(
                task=TASK, label=case.expected_label,
                model_id=manifest.model_id,
                model_version=manifest.model_version,
                feature_version=manifest.feature_version,
                probability=0.9, confidence=0.9,
            )

    return await BenchmarkRunner().run(
        ExactTaskPredictor(),
        BenchmarkConfig(
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            task=TASK,
            dataset_version=CanonicalEvaluationCorpus.DATASET_VERSION,
            case_ids=[case.case_id],
        ),
    )


@pytest.mark.asyncio
async def test_actual_runner_window_is_recorded_and_reissued_run_fails(tmp_path):
    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    assert benchmark.sample_count == 1
    assert benchmark.evaluation_run_id
    assert benchmark.evaluation_started_at is not None
    assert benchmark.evaluation_finished_at is not None
    assert benchmark.evaluation_finished_at >= benchmark.evaluation_started_at
    issuer = EvaluationEvidenceStore(tmp_path)
    receipt_id = issuer._record(manifest, benchmark)
    assert receipt_id == benchmark.evaluation_run_id
    observed = issuer.read_case_receipt(
        manifest=manifest, tenant_id=TENANT, receipt_id=receipt_id,
    )
    assert observed is not None
    assert observed.runner_evaluation_started_at == benchmark.evaluation_started_at
    assert observed.runner_evaluation_finished_at == benchmark.evaluation_finished_at
    with pytest.raises(sqlite3.IntegrityError):
        issuer._record(manifest, benchmark)


@pytest.mark.asyncio
async def test_recent_issuance_cannot_refresh_old_runner_evaluation(tmp_path):
    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    benchmark.evaluation_started_at = datetime(
        2020, 1, 1, tzinfo=timezone.utc,
    )
    benchmark.evaluation_finished_at = (
        benchmark.evaluation_started_at + timedelta(seconds=1)
    )
    receipt_id = EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)
    result = await inspect(
        tmp_path, manifest, receipt_id, InMemoryOutcomeStore(),
        max_evidence_age_seconds=300,
    )
    assert result.health is KcmBenchmarkAssessmentHealth.UNAVAILABLE
    assert "benchmark_evidence_expired" in result.reason_codes
    assert result.observed_fraction_correct is None


@pytest.mark.asyncio
async def test_future_runner_window_and_partial_window_cannot_be_issued(tmp_path):
    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    original_finish = benchmark.evaluation_finished_at
    benchmark.evaluation_finished_at = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(ValueError, match="runner window"):
        EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)
    benchmark.evaluation_finished_at = original_finish
    benchmark.evaluation_started_at = None
    with pytest.raises(ValueError, match="runner window"):
        EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)


@pytest.mark.asyncio
async def test_diagnostic_digest_binds_freshness_policy_and_legacy_basis(tmp_path):
    manifest, receipt, store, _ = await fixture(tmp_path)
    short = await inspect(
        tmp_path, manifest, receipt, store, max_evidence_age_seconds=120,
    )
    long = await inspect(
        tmp_path, manifest, receipt, store, max_evidence_age_seconds=600,
    )
    assert short.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert long.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert short.freshness_basis == "receipt_issuance_only"
    assert not short.runner_execution_window_recorded
    assert short.evidence_sha256 != long.evidence_sha256
    assert not short.production_environment_verified
    assert not short.independent_trial_groups_verified
    assert not short.general_skill_certified


@pytest.mark.asyncio
async def test_live_canonical_runner_projection_reports_actual_freshness_basis(tmp_path):
    """Exact registered artifact, canonical runner, SQLite and scoped outcomes."""
    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    receipt_id = EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)
    record_store = InMemoryOutcomeStore()
    evaluated = benchmark.outcomes[0]
    evidence_ref = (
        f"benchmark:{receipt_id}:"
        + hashlib.sha256(evaluated.case_id.encode("utf-8")).hexdigest()[:24]
    )
    persisted = MLOutcomeRecord(
        outcome_id="runner-window-measured-outcome",
        task=TASK,
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        feature_version=manifest.feature_version,
        predicted_label="",
        expected_label="",
        correct=evaluated.correct,
        raw_probability=0.9,
        calibrated_probability=0.9,
        confidence=0.9,
        latency_ms=evaluated.latency_ms,
        fallback_used=False,
        calibration_error=abs(0.9 - float(evaluated.correct)),
    )
    await GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=record_store,
    ).record_verified_batch([(persisted, "heldout_evaluation", evidence_ref)])
    assessment = await inspect(
        tmp_path, manifest, receipt_id, record_store,
        max_evidence_age_seconds=300,
    )
    assert assessment.health is KcmBenchmarkAssessmentHealth.MEASURED
    assert assessment.runner_execution_window_recorded is True
    assert assessment.freshness_basis == "runner_observed_inference_end"
    assert assessment.runner_evaluation_started_at == benchmark.evaluation_started_at
    assert assessment.runner_evaluation_finished_at == benchmark.evaluation_finished_at
    assert assessment.expires_at == (
        benchmark.evaluation_finished_at + timedelta(seconds=300)
    )
    assert assessment.curated_oracle_source_verified is True
    assert assessment.independent_trial_groups_verified is False
    assert assessment.production_environment_verified is False
    assert assessment.general_skill_certified is False
    assert assessment.execution_authorized is False
    assert assessment.training_authorized is False


@pytest.mark.asyncio
async def test_partial_or_malformed_runner_window_in_receipt_fails_closed(tmp_path):
    import json

    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    receipt_id = EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)
    database = tmp_path / "benchmark_evidence.sqlite3"
    with sqlite3.connect(database) as db:
        original = json.loads(db.execute(
            "SELECT evidence_json FROM benchmark_receipts WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()[0])
        corrupted = dict(original)
        corrupted.pop("runner_evaluation_finished_at")
        db.execute(
            "UPDATE benchmark_receipts SET evidence_json=? WHERE receipt_id=?",
            (json.dumps(corrupted), receipt_id),
        )
    assert EvaluationEvidenceStore(
        tmp_path, create_if_missing=False,
    ).read_case_receipt(
        manifest=manifest, tenant_id=TENANT, receipt_id=receipt_id,
    ) is None

    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE benchmark_receipts SET evidence_json=?, created_at=?"
            " WHERE receipt_id=?",
            (json.dumps(original), "2020-01-01 00:00:00", receipt_id),
        )
    assert EvaluationEvidenceStore(
        tmp_path, create_if_missing=False,
    ).read_case_receipt(
        manifest=manifest, tenant_id=TENANT, receipt_id=receipt_id,
    ) is None


async def _actual_runner_scoped_review_fixture(tmp_path):
    """Actual canonical evaluation, current receipt, and exact owner outcomes."""
    manifest, _, _, _ = await fixture(tmp_path)
    benchmark = await _actual_runner_result(manifest)
    receipt_id = EvaluationEvidenceStore(tmp_path)._record(manifest, benchmark)
    exact_outcome = benchmark.outcomes[0]
    case_hash = hashlib.sha256(
        exact_outcome.case_id.encode("utf-8"),
    ).hexdigest()[:24]
    store = InMemoryOutcomeStore()
    row = MLOutcomeRecord(
        outcome_id="scoped-curated-oracle-review-outcome",
        task=TASK,
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        feature_version=manifest.feature_version,
        predicted_label="",
        expected_label="",
        correct=exact_outcome.correct,
        raw_probability=0.9,
        calibrated_probability=0.9,
        confidence=0.9,
        latency_ms=exact_outcome.latency_ms,
        fallback_used=False,
        calibration_error=abs(0.9 - float(exact_outcome.correct)),
    )
    await GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    ).record_verified_batch([
        (row, "heldout_evaluation", f"benchmark:{receipt_id}:{case_hash}"),
    ])
    return manifest, receipt_id, store


def _authorized_curated_reviewer(*, tenant=TENANT, user=OTHER_USER):
    from ai_karen_engine.auth.rbac_middleware import Permission

    return AuthenticatedPrincipal(
        tenant_id=tenant,
        user_id=user,
        session_id="trusted-reviewer-session",
        permissions=[Permission.BENCHMARK_ORACLE_REVIEW.value],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_scoped_curated_oracle_reviewer_receipt_is_observational_only(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    reviewer = _authorized_curated_reviewer()
    issued = await adapter.record_review(
        subject=identity(), reviewer=reviewer,
        model_id=manifest.model_id, receipt_id=receipt,
    )
    read = await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    )
    assert issued == read
    assert read is not None
    assert read.reviewer_user_id == OTHER_USER
    assert read.exact_cohort_reviewer_acknowledged is True
    assert read.curated_source_integrity_verified is True
    assert read.group_membership_integrity_verified is True
    assert read.independent_trial_groups_verified is False
    assert read.independent_ground_truth_verified is False
    assert read.training_data_disjointness_verified is False
    assert read.general_skill_certified is False
    assert read.execution_authorized is False
    assert read.training_authorized is False

    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError
    with pytest.raises(OutcomeStoreError):
        await adapter.record_review(
            subject=identity(), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )


@pytest.mark.asyncio
async def test_oracle_review_requires_separate_active_authorized_reviewer(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path, store=store,
    )
    bad = (
        identity(),
        AuthenticatedPrincipal(
            tenant_id=TENANT, user_id=OTHER_USER, session_id="s",
        ),
        _authorized_curated_reviewer(tenant=OTHER_TENANT),
        AuthenticatedPrincipal(
            tenant_id=TENANT, user_id=OTHER_USER,
            permissions=_authorized_curated_reviewer().permissions,
        ),
        AuthenticatedPrincipal(
            tenant_id=TENANT, user_id=OTHER_USER, session_id="s",
            permissions=_authorized_curated_reviewer().permissions,
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ),
    )
    for reviewer in bad:
        with pytest.raises(PermissionError):
            await adapter.record_review(
                subject=identity(), reviewer=reviewer,
                model_id=manifest.model_id, receipt_id=receipt,
            )
    with pytest.raises(PermissionError):
        await adapter.inspect_review(
            subject=identity(OTHER_TENANT, USER),
            model_id=manifest.model_id, receipt_id=receipt,
        )
    with pytest.raises(PermissionError):
        await adapter.record_review(
            subject=identity(OTHER_TENANT, USER),
            reviewer=_authorized_curated_reviewer(),
            model_id=manifest.model_id, receipt_id=receipt,
        )
    assert not any(
        row["metadata"].get("schema_version")
        == "kcm_curated_oracle_reviewer_observation_v1"
        for row in store._records
    )


@pytest.mark.asyncio
async def test_oracle_review_drift_tampering_and_revocation_fail_closed(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path, store=store,
    )
    await adapter.record_review(
        subject=identity(), reviewer=_authorized_curated_reviewer(),
        model_id=manifest.model_id, receipt_id=receipt,
    )
    review_payload = store._records[-1]
    review_payload["metadata"]["exact_snapshot_sha256"] = "0" * 64
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
    review_payload["metadata"]["exact_snapshot_sha256"] = (
        adapter._snapshot(model_id=manifest.model_id, receipt_id=receipt)
        .snapshot_sha256
    )
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is not None
    saved = store._records.pop()
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
    store._records.append(saved)
    from pathlib import Path
    Path(manifest.artifact_path).write_bytes(b"tampered-model")
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None


@pytest.mark.asyncio
async def test_legacy_receipt_cannot_gain_reviewer_provenance(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    manifest, receipt, store, _ = await fixture(
        tmp_path, use_canonical_curated_oracles=True,
    )
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path, store=store,
    )
    with pytest.raises(OutcomeStoreError):
        await adapter.record_review(
            subject=identity(), reviewer=_authorized_curated_reviewer(),
            model_id=manifest.model_id, receipt_id=receipt,
        )


@pytest.mark.asyncio
async def test_oracle_review_never_claims_success_without_durable_readback(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)

    class FalseAcknowledgmentStore(InMemoryOutcomeStore):
        async def save_unique_outcome_async(self, payload):
            # Simulate a defective or interrupted persistence adapter that
            # returns without writing the requested review receipt.
            return None

    broken = FalseAcknowledgmentStore()
    for source_record in store._records:
        broken.save_outcome(source_record)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER,
        registry_dir=tmp_path, store=broken,
    )
    with pytest.raises(OutcomeStoreError, match="not durably reconciled"):
        await adapter.record_review(
            subject=identity(),
            reviewer=_authorized_curated_reviewer(),
            model_id=manifest.model_id,
            receipt_id=receipt,
        )
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None


@pytest.mark.asyncio
async def test_oracle_review_invalidates_when_numeric_case_revoked_during_lookup(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, source = await _actual_runner_scoped_review_fixture(tmp_path)
    authority = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=source,
    )
    await authority.record_review(
        subject=identity(), reviewer=_authorized_curated_reviewer(),
        model_id=manifest.model_id, receipt_id=receipt,
    )

    class RevokingDuringReviewerLookup(InMemoryOutcomeStore):
        def __init__(self):
            super().__init__()
            self._revoked = False

        def list_scoped_outcomes_by_ids(self, tenant_id, *, user_id, source, outcome_ids):
            if (
                not self._revoked
                and len(outcome_ids) in (2, 3)
                and any(
                    key.startswith("kcm_curated_review_")
                    for key in outcome_ids
                )
                and any(
                    key.startswith("kcm_curated_review_")
                    and key != outcome_ids[0]
                    for key in outcome_ids
                )
            ):
                self._revoked = True
                surviving = [
                    item for item in self._records
                    if (item.get("metadata") or {}).get("schema_version")
                    != "ml_predictor_evidence_v1"
                ]
                self._records = []
                self._tenant_index = {}
                self._trajectory_index = {}
                for row in surviving:
                    self.save_outcome(row)
            return super().list_scoped_outcomes_by_ids(
                tenant_id, user_id=user_id, source=source, outcome_ids=outcome_ids,
            )

    changed = RevokingDuringReviewerLookup()
    for row in source._records:
        changed.save_outcome(row)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=changed,
    )
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
    assert changed._revoked is True


@pytest.mark.asyncio
async def test_full_bound_numeric_case_is_not_displaced_by_reviewer_receipt(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER,
        registry_dir=tmp_path, store=store, maximum_cases=1,
    )
    issued = await adapter.record_review(
        subject=identity(), reviewer=_authorized_curated_reviewer(),
        model_id=manifest.model_id, receipt_id=receipt,
    )
    assert issued.exact_cohort_reviewer_acknowledged
    numeric = store.list_scoped_ml_predictor_outcomes(
        TENANT, user_id=USER, limit=1,
    )
    assert len(numeric) == 1
    assert numeric[0]["metadata"]["schema_version"] == "ml_predictor_evidence_v1"
    assert len(store.list_for_tenant(
        TENANT, user_id=USER, source="intelligence.ml", limit=3,
    )) == 3
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is not None


@pytest.mark.asyncio
async def test_reviewer_authority_expiry_during_await_prevents_receipt(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    reviewer = _authorized_curated_reviewer()
    original = adapter._require_measured

    async def expire_during_outcome_read(*, subject, snapshot):
        await original(subject=subject, snapshot=snapshot)
        reviewer.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

    adapter._require_measured = expire_during_outcome_read
    with pytest.raises(PermissionError):
        await adapter.record_review(
            subject=identity(), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
    assert not any(
        (row.get("metadata") or {}).get("schema_version")
        == "kcm_curated_oracle_reviewer_observation_v1"
        for row in store._records
    )


@pytest.mark.asyncio
async def test_mutable_reviewer_scope_cannot_change_during_await(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    reviewer = _authorized_curated_reviewer()
    original = adapter._require_measured

    async def mutate_session_during_outcome_read(*, subject, snapshot):
        await original(subject=subject, snapshot=snapshot)
        reviewer.session_id = "new-trusted-session"

    adapter._require_measured = mutate_session_during_outcome_read
    with pytest.raises(PermissionError, match="changed"):
        await adapter.record_review(
            subject=identity(), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
    assert not any(
        (row.get("metadata") or {}).get("schema_version")
        == "kcm_curated_oracle_reviewer_observation_v1"
        for row in store._records
    )


def test_canonical_store_rejects_forged_or_malformed_oracle_receipts():
    from ai_karen_engine.core.runtime.outcome.store import (
        OutcomeStoreError, PostgresOutcomeStore,
    )

    now = datetime.now(timezone.utc).isoformat()
    key = "kcm_curated_review_" + "a" * 64
    valid = {
        "tenant_id": TENANT,
        "user_id": USER,
        "outcome_id": key,
        "source": "intelligence.ml",
        "recorded_at": now,
        "metadata": {
            "schema_version": "kcm_curated_oracle_reviewer_observation_v1",
            "receipt_id": "b" * 32,
            "model_id": model_id(),
            "reviewer_user_id": OTHER_USER,
            "reviewer_session_present": True,
            "reviewed_at": now,
            "exact_snapshot_sha256": "c" * 64,
            "review_phase": "confirmed",
            "proposal_outcome_id": "kcm_curated_review_" + "d" * 64,
            "review_acknowledged": True,
        },
    }
    assert PostgresOutcomeStore._validated_identity(valid) == (
        TENANT, "intelligence.ml",
    )
    from copy import deepcopy

    for field, value in [
        ("reviewer_user_id", USER),
        ("reviewer_session_present", False),
        ("exact_snapshot_sha256", "not-a-sha256"),
        ("receipt_id", "wrong"),
        ("review_acknowledged", False),
        ("reviewed_at", "2000-01-01T00:00:00+00:00"),
    ]:
        malformed = deepcopy(valid)
        malformed["metadata"][field] = value
        with pytest.raises(OutcomeStoreError):
            PostgresOutcomeStore._validated_identity(malformed)
    extra = deepcopy(valid)
    extra["metadata"]["unreviewed_policy_grant"] = True
    with pytest.raises(OutcomeStoreError):
        PostgresOutcomeStore._validated_identity(extra)


@pytest.mark.asyncio
async def test_incomplete_reviewer_proposal_never_becomes_consumable(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, original_store = await _actual_runner_scoped_review_fixture(
        tmp_path,
    )
    reviewer = _authorized_curated_reviewer()

    class ExpiringAfterProposal(InMemoryOutcomeStore):
        async def save_unique_outcome_async(self, payload):
            await super().save_unique_outcome_async(payload)
            if payload["metadata"].get("review_phase") == "proposed":
                reviewer.expires_at = datetime(
                    2020, 1, 1, tzinfo=timezone.utc,
                )

    store = ExpiringAfterProposal()
    for row in original_store._records:
        store.save_outcome(row)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    with pytest.raises(PermissionError):
        await adapter.record_review(
            subject=identity(), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
    assert sum(
        (row.get("metadata") or {}).get("review_phase") == "proposed"
        for row in store._records
    ) == 1
    assert not any(
        (row.get("metadata") or {}).get("review_phase") == "confirmed"
        for row in store._records
    )
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None


@pytest.mark.asyncio
async def test_final_await_subject_revocation_prevents_readout(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    await adapter.record_review(
        subject=identity(), reviewer=_authorized_curated_reviewer(),
        model_id=manifest.model_id, receipt_id=receipt,
    )
    subject = identity()
    original = adapter._require_measured
    reads = 0

    async def revoke_on_second_measure(*, subject, snapshot):
        nonlocal reads
        await original(subject=subject, snapshot=snapshot)
        reads += 1
        if reads == 2:
            subject.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

    adapter._require_measured = revoke_on_second_measure
    with pytest.raises(PermissionError):
        await adapter.inspect_review(
            subject=subject, model_id=manifest.model_id, receipt_id=receipt,
        )


@pytest.mark.asyncio
async def test_original_reviewer_can_withdraw_exact_confirmed_cohort(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store, maximum_cases=1,
    )
    reviewer = _authorized_curated_reviewer()
    reviewed = await adapter.record_review(
        subject=identity(), reviewer=reviewer,
        model_id=manifest.model_id, receipt_id=receipt,
    )
    assert reviewed.exact_cohort_reviewer_acknowledged
    before = len(store._records)
    withdrawal_id = await adapter.withdraw_review(
        subject=identity(), reviewer=reviewer,
        model_id=manifest.model_id, receipt_id=receipt,
    )
    assert withdrawal_id.startswith("kcm_curated_withdrawal_")
    assert len(store._records) == before + 1
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
    numeric = store.list_scoped_ml_predictor_outcomes(
        TENANT, user_id=USER, limit=1,
    )
    assert len(numeric) == 1
    assert numeric[0]["metadata"]["schema_version"] == "ml_predictor_evidence_v1"
    with pytest.raises(OutcomeStoreError):
        await adapter.withdraw_review(
            subject=identity(), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )


@pytest.mark.asyncio
async def test_reviewer_withdrawal_denies_other_reviewer_and_wrong_tenant(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    adapter = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER,
        registry_dir=tmp_path, store=store,
    )
    reviewer = _authorized_curated_reviewer()
    await adapter.record_review(
        subject=identity(), reviewer=reviewer,
        model_id=manifest.model_id, receipt_id=receipt,
    )
    for unauthorized in (
        _authorized_curated_reviewer(user="unrelated-reviewer"),
        _authorized_curated_reviewer(tenant=OTHER_TENANT),
        identity(),
    ):
        with pytest.raises(PermissionError):
            await adapter.withdraw_review(
                subject=identity(), reviewer=unauthorized,
                model_id=manifest.model_id, receipt_id=receipt,
            )
    with pytest.raises(PermissionError):
        await adapter.withdraw_review(
            subject=identity(OTHER_TENANT, USER), reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
    assert await adapter.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is not None
    assert not any(
        (row.get("metadata") or {}).get("schema_version")
        == "kcm_curated_oracle_reviewer_withdrawal_v1"
        for row in store._records
    )


@pytest.mark.asyncio
async def test_concurrent_withdrawal_after_final_numeric_read_blocks_review(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, store = await _actual_runner_scoped_review_fixture(tmp_path)
    writer = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    reader = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=store,
    )
    reviewer = _authorized_curated_reviewer()
    await writer.record_review(
        subject=identity(), reviewer=reviewer,
        model_id=manifest.model_id, receipt_id=receipt,
    )
    original = reader._require_measured
    checked = 0

    async def withdraw_during_last_measure(*, subject, snapshot):
        nonlocal checked
        await original(subject=subject, snapshot=snapshot)
        checked += 1
        if checked == 2:
            await writer.withdraw_review(
                subject=identity(), reviewer=reviewer,
                model_id=manifest.model_id, receipt_id=receipt,
            )

    reader._require_measured = withdraw_during_last_measure
    assert await reader.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
    assert checked == 2


def test_canonical_store_fences_malformed_reviewer_withdrawal_receipts():
    from ai_karen_engine.core.runtime.outcome.store import (
        OutcomeStoreError, PostgresOutcomeStore,
    )
    from copy import deepcopy

    now = datetime.now(timezone.utc).isoformat()
    valid = {
        "tenant_id": TENANT,
        "user_id": USER,
        "outcome_id": "kcm_curated_withdrawal_" + "b" * 64,
        "source": "intelligence.ml",
        "recorded_at": now,
        "metadata": {
            "schema_version": "kcm_curated_oracle_reviewer_withdrawal_v1",
            "receipt_id": "a" * 32,
            "model_id": model_id(),
            "reviewer_user_id": OTHER_USER,
            "review_confirmed_outcome_id": "kcm_curated_review_" + "c" * 64,
            "review_snapshot_sha256": "d" * 64,
            "revoked_at": now,
            "reason_code": "reviewer_withdrawal",
            "review_withdrawn": True,
        },
    }
    assert PostgresOutcomeStore._validated_identity(valid) == (
        TENANT, "intelligence.ml",
    )
    for k, v in (
        ("reviewer_user_id", USER),
        ("review_confirmed_outcome_id", "unknown"),
        ("review_snapshot_sha256", "bad"),
        ("reason_code", "training_authorized"),
        ("review_withdrawn", False),
        ("revoked_at", "2020-01-01T00:00:00+00:00"),
    ):
        bad = deepcopy(valid)
        bad["metadata"][k] = v
        with pytest.raises(OutcomeStoreError):
            PostgresOutcomeStore._validated_identity(bad)
    bad = deepcopy(valid)
    bad["metadata"]["execution_authorized"] = True
    with pytest.raises(OutcomeStoreError):
        PostgresOutcomeStore._validated_identity(bad)


@pytest.mark.asyncio
async def test_unknown_withdrawal_lookup_never_returns_active_review(tmp_path):
    from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
        GovernedCuratedOracleReviewEvidence,
    )

    manifest, receipt, original_store = await _actual_runner_scoped_review_fixture(
        tmp_path,
    )
    issuer = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=original_store,
    )
    await issuer.record_review(
        subject=identity(), reviewer=_authorized_curated_reviewer(),
        model_id=manifest.model_id, receipt_id=receipt,
    )
    assert await issuer.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is not None

    class UnreliableWithdrawalRead(InMemoryOutcomeStore):
        def list_scoped_outcomes_by_ids(
            self, tenant_id, *, user_id, outcome_ids, source,
        ):
            if (
                len(outcome_ids) == 1
                and outcome_ids[0].startswith("kcm_curated_withdrawal_")
            ):
                # A partial/incorrect ledger adapter must not manufacture a
                # favorable reviewer acknowledgment from an unknown read.
                return None
            return super().list_scoped_outcomes_by_ids(
                tenant_id, user_id=user_id, outcome_ids=outcome_ids,
                source=source,
            )

    unreadable = UnreliableWithdrawalRead()
    for row in original_store._records:
        unreadable.save_outcome(row)
    consumer = GovernedCuratedOracleReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, registry_dir=tmp_path,
        store=unreadable,
    )
    assert await consumer.inspect_review(
        subject=identity(), model_id=manifest.model_id, receipt_id=receipt,
    ) is None
