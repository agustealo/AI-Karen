"""KCOG-01A2: truthful, principal-scoped confidence evaluation proof.

All fixture outcomes are synthetic and do not establish real-world cognitive
improvement. The evaluator only consumes governed OutcomeStore evidence and
never authorizes runtime verification or model promotion.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)

_TASK = PredictionTask.VERIFICATION_VALUE
_MODEL = "verified-verification-model"
_VERSION = "model-v2"
_FEATURE = "features-v3"
_STAMP = "2026-11-16T12:00:00+00:00"


def record(
    number: int,
    *,
    correct: bool,
    confidence: float,
    tenant: str = "tenant-a",
    user: str = "user-a",
    model: str = _MODEL,
    model_version: str = _VERSION,
    feature_version: str = _FEATURE,
    fallback: bool = False,
    label_source: str = "heldout_evaluation",
    label_evidence_ref: str | None = None,
    outcome_id: str | None = None,
) -> dict:
    return {
        "outcome_id": outcome_id or f"outcome-{number}",
        "tenant_id": tenant,
        "user_id": user,
        "source": "intelligence.ml",
        "recorded_at": _STAMP,
        "metadata": {
            "schema_version": "ml_predictor_evidence_v1",
            "label_source": label_source,
            "label_evidence_ref": label_evidence_ref or f"benchmark:receipt:{number}",
            "task": _TASK.value,
            "model_id": model,
            "model_version": model_version,
            "feature_version": feature_version,
            "correct": correct,
            "raw_probability": confidence,
            "calibrated_probability": confidence,
            "confidence": confidence,
            "calibration_error": abs(confidence - float(correct)),
            "latency_ms": 25.0,
            "fallback_used": fallback,
        },
    }


@dataclass
class PrincipalScopedStore:
    rows: list[dict]
    failure: bool = False

    def list_scoped_ml_predictor_outcomes(
        self,
        tenant_id: str,
        *,
        limit: int,
        user_id: str,
    ) -> list[dict]:
        assert (tenant_id, user_id) == ("tenant-a", "user-a")
        if self.failure:
            raise RuntimeError("OutcomeStore unavailable")
        # This fixture implements the production store's predicate-before-limit
        # guarantee. The loader independently revalidates returned records.
        rows = [
            row for row in self.rows
            if row.get("tenant_id") == tenant_id
            and row.get("user_id") == user_id
            and row.get("source") == "intelligence.ml"
            and isinstance(row.get("metadata"), dict)
            and row["metadata"].get("schema_version")
            == "ml_predictor_evidence_v1"
        ]
        return rows[:limit]


def evaluator(rows: list[dict], *, failure: bool = False) -> GovernedMLLearningEvidence:
    return GovernedMLLearningEvidence(
        tenant_id="tenant-a",
        user_id="user-a",
        store=PrincipalScopedStore(rows=rows, failure=failure),
    )


async def evaluate(
    evidence: GovernedMLLearningEvidence,
    *,
    minimum_samples: int = 20,
    limit: int = 500,
    model: str = _MODEL,
):
    return await evidence.evaluate_verified_confidence(
        task=_TASK,
        model_id=model,
        model_version=_VERSION,
        feature_version=_FEATURE,
        minimum_samples=minimum_samples,
        limit=limit,
    )


@pytest.mark.asyncio
async def test_perfect_and_worst_scored_with_existing_ml_metrics() -> None:
    perfect = [
        record(i, correct=(i % 2 == 0), confidence=float(i % 2 == 0))
        for i in range(20)
    ]
    report = await evaluate(evaluator(perfect))
    assert report.status == "evaluated_shadow"
    assert report.runtime_authorized is False
    assert report.sample_count == 20
    assert report.scope == "principal_scoped_bounded_window"
    assert report.evidence_version == "ml_predictor_evidence_v1"
    assert report.task is _TASK
    assert report.brier_score is not None
    assert report.expected_calibration_error is not None
    assert report.brier_score.value == pytest.approx(0.0)
    assert report.expected_calibration_error.value == pytest.approx(0.0)
    assert report.brier_score.sample_count == 20

    worst = [
        record(i, correct=(i % 2 == 0), confidence=float(i % 2 != 0))
        for i in range(20)
    ]
    other = await evaluate(evaluator(worst))
    assert other.status == "evaluated_shadow"
    assert other.brier_score is not None
    assert other.expected_calibration_error is not None
    assert other.brier_score.value == pytest.approx(1.0)
    assert other.expected_calibration_error.value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_absent_and_small_evidence_never_looks_perfect() -> None:
    for rows in ([], [record(i, correct=True, confidence=1.0) for i in range(3)]):
        report = await evaluate(evaluator(rows))
        assert report.status == "insufficient_evidence"
        assert report.sample_count == len(rows)
        assert report.brier_score is None
        assert report.expected_calibration_error is None
        assert report.runtime_authorized is False


@pytest.mark.asyncio
async def test_principal_scope_version_and_label_provenance_filtering() -> None:
    valid = [
        record(i, correct=True, confidence=1.0) for i in range(18)
    ]
    excluded = [
        record(100, correct=False, confidence=1.0, tenant="tenant-b"),
        record(101, correct=False, confidence=1.0, user="user-b"),
        record(102, correct=False, confidence=1.0, model="other-model"),
        record(103, correct=False, confidence=1.0, model_version="v1"),
        record(104, correct=False, confidence=1.0, feature_version="v1"),
        record(105, correct=False, confidence=1.0, fallback=True),
        record(106, correct=False, confidence=1.0, label_source="generic_feedback"),
        record(107, correct=False, confidence=1.0, outcome_id="outcome-0"),
    ]
    report = await evaluate(evaluator(valid + excluded))
    assert report.status == "insufficient_evidence"
    assert report.sample_count == 18
    assert report.brier_score is None
    assert report.expected_calibration_error is None


@pytest.mark.asyncio
async def test_duplicate_label_receipts_cannot_inflate_sample_count() -> None:
    valid = [
        record(i, correct=True, confidence=1.0) for i in range(18)
    ]
    replayed_labels = [
        record(
            200 + i,
            correct=False,
            confidence=0.0,
            label_evidence_ref="benchmark:receipt:0",
        )
        for i in range(7)
    ]
    report = await evaluate(evaluator(valid + replayed_labels))
    assert report.status == "insufficient_evidence"
    assert report.sample_count == 18
    assert report.brier_score is None
    assert report.expected_calibration_error is None


@pytest.mark.asyncio
async def test_invalid_persisted_label_reference_is_never_evaluated() -> None:
    valid = [
        record(i, correct=True, confidence=1.0) for i in range(19)
    ]
    forged = record(
        201,
        correct=True,
        confidence=1.0,
        label_evidence_ref="private label injection !",
    )
    report = await evaluate(evaluator(valid + [forged]))
    assert report.status == "insufficient_evidence"
    assert report.sample_count == 19


@pytest.mark.asyncio
async def test_window_and_model_identity_are_explicit() -> None:
    rows = [record(i, correct=True, confidence=1.0) for i in range(22)]
    report = await evaluate(evaluator(rows), limit=20, minimum_samples=20)
    assert report.status == "evaluated_shadow"
    assert report.sample_count == 20
    assert report.window_limit == 20
    wrong = await evaluate(evaluator(rows), model="unrelated-model")
    assert wrong.status == "insufficient_evidence"
    assert wrong.sample_count == 0


@pytest.mark.asyncio
async def test_replay_and_failure_propagate_without_phantom_receipt() -> None:
    rows = [record(i, correct=True, confidence=1.0) for i in range(20)]
    store = PrincipalScopedStore(rows=rows)
    first = await evaluate(
        GovernedMLLearningEvidence(tenant_id="tenant-a", user_id="user-a", store=store)
    )
    replay = await evaluate(
        GovernedMLLearningEvidence(tenant_id="tenant-a", user_id="user-a", store=store)
    )
    assert first == replay
    with pytest.raises(RuntimeError, match="OutcomeStore unavailable"):
        await evaluate(evaluator(rows, failure=True))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"task": "verification_value"},
        {"minimum_samples": 0},
        {"minimum_samples": True},
        {"minimum_samples": 501},
        {"limit": 0},
        {"limit": True},
        {"limit": 1001},
        {"n_bins": 1},
        {"n_bins": True},
        {"model_id": ""},
        {"model_version": ""},
        {"feature_version": ""},
    ],
)
async def test_invalid_evaluation_configuration_fails_closed(changes: dict) -> None:
    kwargs = {
        "task": _TASK,
        "model_id": _MODEL,
        "model_version": _VERSION,
        "feature_version": _FEATURE,
        "minimum_samples": 20,
        "limit": 500,
        "n_bins": 10,
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        await evaluator([]).evaluate_verified_confidence(**kwargs)


def test_explicit_principal_required_for_evaluation() -> None:
    for tenant, user in (("", "user-a"), ("default", "user-a"), ("tenant-a", "")):
        with pytest.raises(ValueError):
            GovernedMLLearningEvidence(
                tenant_id=tenant,
                user_id=user,
                store=PrincipalScopedStore(rows=[]),
            )
