"""Persistence and integrity proof for canonical trained-model promotion receipts."""
from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest, ModelStatus, Prediction, PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkResult, MetricResult, PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import EvaluationEvidenceStore
from ai_karen_engine.core.intelligence.ml.promotion import PromotionDecision
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory


def test_canonical_receipt_survives_registry_restart_and_rejects_tampering(tmp_path, monkeypatch):
    from ai_karen_engine.core.intelligence.ml.evaluation import evidence

    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    artifact = tmp_path / "model"
    artifact.mkdir()
    (artifact / "weights.bin").write_bytes(b"training-proof")
    tenant_key = hashlib.sha256(b"tenant-a").hexdigest()[:16]
    model_id = f"tenant-{tenant_key}-intent-receipt"
    manifest = MLModelManifest(
        model_id=model_id, purpose="intent", architecture="spacy",
        artifact_path=str(artifact), artifact_hash=_hash_directory(artifact),
        model_version="v1", feature_version="spacy_textcat_v1",
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(manifest)
    prediction = Prediction(
        task=PredictionTask.INTENT, label="test", probability=0.9,
        model_id=model_id, model_version="v1",
    )
    result = BenchmarkResult(
        model_id=model_id, model_version="v1", task=PredictionTask.INTENT,
        dataset_version="benchmark-v1", sample_count=1,
        metrics={"accuracy": MetricResult(metric_name="accuracy", value=1.0, sample_count=1)},
        latency_p50_ms=1.0, latency_p95_ms=1.0,
        error_count=0, fallback_count=0, abstention_count=0,
        outcomes=[PredictionOutcome(
            case_id="case-1", task=PredictionTask.INTENT, prediction=prediction,
            expected_label="test", correct=True,
        )],
    )
    # Isolate receipt durability from the threshold calculator: the actual
    # benchmark gate is tested in test_promotion.py.
    monkeypatch.setattr(evidence, "evaluate_promotion", lambda *args: (
        PromotionDecision.PROMOTION_ELIGIBLE, ["test fixture threshold approved"],
    ))
    store = EvaluationEvidenceStore(registry.registry_dir)
    receipt = store._record(manifest, result)
    assert receipt
    restarted = MLModelRegistry(registry_dir=str(registry.registry_dir))
    reopened = EvaluationEvidenceStore(registry.registry_dir)
    assert reopened.is_approved(restarted.get(model_id))
    restarted.register(replace(restarted.get(model_id), status=ModelStatus.SHADOW.value))
    (artifact / "weights.bin").write_bytes(b"tampered")
    assert not reopened.is_approved(restarted.get(model_id))


def test_receipt_rejects_unregistered_candidate(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    manifest = MLModelManifest(
        model_id="missing", purpose="intent", architecture="spacy",
        artifact_path=str(tmp_path), artifact_hash="invalid",
        model_version="v1", feature_version="v1",
    )
    assert not EvaluationEvidenceStore(registry.registry_dir).is_approved(manifest)
