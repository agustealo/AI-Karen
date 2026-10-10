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
