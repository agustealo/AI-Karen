from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.temporal_executor import TemporalTrainingExecutor
from ai_karen_engine.core.intelligence.ml.predictors.temporal_forecast import TemporalForecastPredictor


def test_temporal_training_artifact_and_tenant_forecast(tmp_path, monkeypatch):
    import ai_karen_engine.core.intelligence.ml.training.temporal_executor as temporal
    monkeypatch.setattr(temporal, "get_ml_registry_dir", lambda: str(tmp_path))
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = [float(i) + (i % 3) * 0.1 for i in range(90)]
    (dataset_root / "series.jsonl").write_text(
        "\n".join(json.dumps({
            "timestamp": (first + timedelta(days=i)).isoformat(),
            "value": value,
        }) for i, value in enumerate(values)) + "\n",
        encoding="utf-8",
    )
    job = TrainingJob(
        job_id="temporal-example-1234", task="outcome_forecast",
        base_model="timeseries", dataset_version="series",
        metadata={"tenant_id": "tenant-a", "advanced_config": {
            "lags": 5, "horizon": 1, "test_split": 0.2, "max_samples": 100,
        }},
    )
    artifact = TemporalTrainingExecutor().execute(job)
    assert artifact.metrics["test_samples"] >= 5
    assert artifact.metrics["temporal_validation"] == "chronological_holdout_with_embargo"
    assert artifact.metrics["mae"] >= 0
    registry = MLModelRegistry(registry_dir=str(tmp_path / "manifests"))
    manifest = MLModelManifest(
        model_id=artifact.model_id, purpose=artifact.task,
        architecture="trained", artifact_path=artifact.artifact_path,
        artifact_hash=artifact.artifact_hash, model_version=artifact.model_version,
        feature_version=artifact.metrics["feature_version"],
        training_dataset_version=artifact.dataset_version,
        metrics=artifact.metrics, status=ModelStatus.CANDIDATE.value,
    )
    registry.register(manifest)
    predictor = TemporalForecastPredictor(registry)
    result = predictor.forecast(
        tenant_id="tenant-a", candidate_model_id=artifact.model_id,
        recent_values=values[-5:],
    )
    assert result["model_id"] == artifact.model_id
    assert result["horizon"] == 1
    assert isinstance(result["value"], float)
    with pytest.raises(PermissionError):
        predictor.forecast(
            tenant_id="tenant-b", candidate_model_id=artifact.model_id,
            recent_values=values[-5:],
        )
    with pytest.raises(ValueError):
        predictor.forecast(
            tenant_id="tenant-a", candidate_model_id=artifact.model_id,
            recent_values=[1.0],
        )


def test_temporal_rejects_symlinked_model_payload_before_pickle_load(tmp_path, monkeypatch):
    import hashlib
    from ai_karen_engine.core.intelligence.ml.predictors import temporal_forecast

    tenant = "tenant-a"
    key = hashlib.sha256(tenant.encode()).hexdigest()[:16]
    model_id = f"tenant-{key}-outcome_forecast-test"
    artifact = tmp_path / "topology" / model_id / "train-v1"
    artifact.mkdir(parents=True)
    real_payload = tmp_path / "outside.joblib"
    real_payload.write_bytes(b"untrusted pickle bytes")
    (artifact / "model.joblib").symlink_to(real_payload)
    (artifact / "feature_schema.json").write_text(json.dumps({
        "feature_version": "temporal-lags-v1",
        "lags": 5, "horizon": 1, "target": "value",
    }))
    registry = MLModelRegistry(registry_dir=str(tmp_path / "manifests"))
    registry.register(MLModelManifest(
        model_id=model_id, purpose="outcome_forecast", architecture="trained",
        artifact_path=str(artifact), artifact_hash="hash",
        model_version="train-v1", feature_version="temporal-lags-v1",
        metrics={"executor": "timeseries"}, status=ModelStatus.CANDIDATE.value,
    ))
    monkeypatch.setattr(registry, "validate_artifact", lambda manifest: True)
    monkeypatch.setattr(temporal_forecast.joblib, "load", lambda path: pytest.fail("pickle loaded"))
    with pytest.raises(ValueError, match="Unsafe temporal artifact"):
        TemporalForecastPredictor(registry).forecast(
            tenant_id=tenant, candidate_model_id=model_id,
            recent_values=[1., 2., 3., 4., 5.],
        )


def test_temporal_rejects_feature_schema_mismatch_before_inference(tmp_path, monkeypatch):
    import hashlib
    from ai_karen_engine.core.intelligence.ml.predictors import temporal_forecast

    tenant = "tenant-a"
    key = hashlib.sha256(tenant.encode()).hexdigest()[:16]
    model_id = f"tenant-{key}-outcome_forecast-schema-test"
    artifact = tmp_path / "topology" / model_id / "train-v1"
    artifact.mkdir(parents=True)
    (artifact / "model.joblib").write_bytes(b"not a real model")
    (artifact / "feature_schema.json").write_text(json.dumps({
        "feature_version": "wrong-version", "lags": 5, "horizon": 1,
        "target": "value",
    }))
    registry = MLModelRegistry(registry_dir=str(tmp_path / "manifests"))
    registry.register(MLModelManifest(
        model_id=model_id, purpose="outcome_forecast", architecture="trained",
        artifact_path=str(artifact), artifact_hash="hash", model_version="train-v1",
        feature_version="temporal-lags-v1",
        metrics={"executor": "timeseries"}, status=ModelStatus.CANDIDATE.value,
    ))
    monkeypatch.setattr(registry, "validate_artifact", lambda manifest: True)
    monkeypatch.setattr(temporal_forecast.joblib, "load", lambda path: pytest.fail("pickle loaded"))
    with pytest.raises(ValueError, match="feature schema identity mismatch"):
        TemporalForecastPredictor(registry).forecast(
            tenant_id=tenant, candidate_model_id=model_id,
            recent_values=[1., 2., 3., 4., 5.],
        )
