from __future__ import annotations

import json
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest,
    ModelStatus,
    PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.predictors.registry_classifier import (
    RegistryBackedClassifier,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry


def _register_active_model(
    registry: MLModelRegistry,
    tmp_path: Path,
    task: PredictionTask,
) -> MLModelManifest:
    artifact = tmp_path / task.value
    artifact.mkdir(parents=True, exist_ok=True)

    model = LogisticRegression(random_state=42)
    model.fit([[1.0], [2.0], [8.0], [9.0]], ["low", "low", "high", "high"])
    joblib.dump(model, artifact / "model.joblib")
    (artifact / "feature_schema.json").write_text(
        json.dumps(
            {
                "feature_version": "v1",
                "feature_order": ["token_count"],
                "classes": ["high", "low"],
            }
        ),
        encoding="utf-8",
    )

    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory

    manifest = MLModelManifest(
        model_id=f"adaptive-{task.value}",
        purpose=task.value,
        architecture="logistic_regression",
        artifact_path=str(artifact),
        artifact_hash=_hash_directory(artifact),
        model_version="test-v1",
        feature_version="v1",
        training_dataset_version="test-dataset",
        status=ModelStatus.ACTIVE.value,
    )
    registry.register(manifest)
    return manifest


async def test_registry_classifier_is_unknown_without_active_model(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    predictor = RegistryBackedClassifier(
        PredictionTask.AFFECT,
        registry=registry,
    )

    prediction = await predictor.predict(
        IntelligenceFeatures(text="hello", token_count=3)
    )

    assert prediction.label == "unknown"
    assert prediction.confidence == 0.0
    assert prediction.fallback_used is True
    assert prediction.metadata["reason"] == "no_active_model"


async def test_registry_classifier_runs_active_model(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    manifest = _register_active_model(registry, tmp_path, PredictionTask.AFFECT)
    predictor = RegistryBackedClassifier(
        PredictionTask.AFFECT,
        registry=registry,
    )

    prediction = await predictor.predict(
        IntelligenceFeatures(text="hello", token_count=9)
    )

    assert prediction.label == "high"
    assert prediction.model_id == manifest.model_id
    assert prediction.model_version == manifest.model_version
    assert prediction.fallback_used is False
    assert prediction.inference_method == "registry_model"
    assert 0.0 <= prediction.confidence <= 1.0


async def test_registry_classifier_fails_closed_on_missing_feature(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    manifest = _register_active_model(
        registry,
        tmp_path,
        PredictionTask.OUTCOME_FORECAST,
    )
    schema_path = Path(manifest.artifact_path) / "feature_schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "feature_version": "v1",
                "feature_order": ["request.missing_signal"],
                "classes": ["high", "low"],
            }
        ),
        encoding="utf-8",
    )

    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory
    manifest.artifact_hash = _hash_directory(Path(manifest.artifact_path))
    registry.register(manifest)

    predictor = RegistryBackedClassifier(
        PredictionTask.OUTCOME_FORECAST,
        registry=registry,
    )
    prediction = await predictor.predict(IntelligenceFeatures(text="forecast"))

    assert prediction.label == "unknown"
    assert prediction.fallback_used is True
    assert prediction.metadata["reason"] == "feature_contract_unavailable"


async def test_registry_classifier_decodes_numeric_training_labels(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    artifact = tmp_path / "numeric"
    artifact.mkdir()
    model = LogisticRegression(random_state=42)
    model.fit([[1.0], [2.0], [8.0], [9.0]], [1, 1, 0, 0])
    joblib.dump(model, artifact / "model.joblib")
    (artifact / "feature_schema.json").write_text(
        json.dumps({
            "feature_version": "v1",
            "feature_order": ["token_count"],
            "classes": ["high", "low"],
        }), encoding="utf-8",
    )
    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory
    manifest = MLModelManifest(
        model_id="numeric-affect",
        purpose=PredictionTask.AFFECT.value,
        architecture="logistic_regression",
        artifact_path=str(artifact),
        artifact_hash=_hash_directory(artifact),
        model_version="numeric-v1",
        feature_version="v1",
        training_dataset_version="test-dataset",
        status=ModelStatus.ACTIVE.value,
    )
    registry.register(manifest)
    predictor = RegistryBackedClassifier(PredictionTask.AFFECT, registry=registry)
    prediction = await predictor.predict(IntelligenceFeatures(text="longer", token_count=9))
    assert prediction.label == "high"
    assert set(prediction.metadata["probabilities"]) == {"high", "low"}


def test_registry_active_selection_requires_matching_tenant(tmp_path):
    import hashlib
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    a = hashlib.sha256(b"tenant-a").hexdigest()[:16]
    b = hashlib.sha256(b"tenant-b").hexdigest()[:16]
    for tenant_key in (a, b):
        registry.register(MLModelManifest(
            model_id=f"tenant-{tenant_key}-affect-model",
            purpose="affect",
            architecture="logistic_regression",
            artifact_path=str(tmp_path),
            artifact_hash="test-hash",
            model_version="v1",
            feature_version="v1",
            status=ModelStatus.ACTIVE.value,
        ))
    assert registry.get_active("affect") is None
    assert registry.get_active("affect", tenant_id="tenant-a").model_id.startswith(f"tenant-{a}-")
    assert registry.get_active("affect", tenant_id="tenant-b").model_id.startswith(f"tenant-{b}-")
    assert registry.get_active("affect", tenant_id="tenant-c") is None


async def test_shared_predictor_does_not_reuse_another_request_tenant(tmp_path):
    import hashlib

    class RecordingRegistry:
        def __init__(self):
            self.seen = []

        def get_active(self, purpose, *, tenant_id=None):
            self.seen.append((purpose, tenant_id))
            return None

    registry = RecordingRegistry()
    predictor = RegistryBackedClassifier(PredictionTask.AFFECT, registry=registry)
    for tenant in ("tenant-a", "tenant-b", None):
        result = await predictor.predict(IntelligenceFeatures(text="test", tenant_id=tenant))
        assert result.label == "unknown"
    assert registry.seen == [
        ("affect", "tenant-a"), ("affect", "tenant-b"), ("affect", None),
    ]


async def test_candidate_predictor_requires_matching_tenant_and_candidate_status(tmp_path):
    import hashlib
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    prefix = hashlib.sha256(b"tenant-a").hexdigest()[:16]
    candidate = MLModelManifest(
        model_id=f"tenant-{prefix}-affect-candidate",
        purpose=PredictionTask.AFFECT.value,
        architecture="trained",
        artifact_path=str(tmp_path / "missing"),
        artifact_hash="missing",
        model_version="v1",
        feature_version="v1",
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(candidate)
    allowed = RegistryBackedClassifier(
        PredictionTask.AFFECT, registry=registry,
        tenant_id="tenant-a", candidate_model_id=candidate.model_id,
    )
    denied = RegistryBackedClassifier(
        PredictionTask.AFFECT, registry=registry,
        tenant_id="tenant-b", candidate_model_id=candidate.model_id,
    )
    assert allowed._active_manifest() is not None
    assert denied._active_manifest() is None
    assert registry.get_active(PredictionTask.AFFECT.value, tenant_id="tenant-a") is None


def test_sklearn_predictor_rejects_spacy_candidate_architecture_before_loading(tmp_path):
    from dataclasses import replace

    registry = MLModelRegistry(registry_dir=str(tmp_path))
    manifest = _register_active_model(registry, tmp_path, PredictionTask.AFFECT)
    spacy_manifest = replace(manifest, architecture="spacy")
    predictor = RegistryBackedClassifier(PredictionTask.AFFECT, registry=registry)

    import pytest
    with pytest.raises(ValueError, match="only accepts canonical sklearn"):
        predictor._load_artifact(spacy_manifest)
