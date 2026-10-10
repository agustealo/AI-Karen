"""Leakage-resistant temporal forecasting executor.

Input JSONL: {"timestamp": ISO-8601 timezone-aware, "value": finite float,
"series_id": optional string}. Chronological holdout, never random split.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
import joblib

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingArtifact, TrainingJob
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory


class TemporalTrainingExecutor:
    def execute(self, job: TrainingJob) -> TrainingArtifact:
        cfg = job.metadata.get("advanced_config", {})
        if job.task != "outcome_forecast":
            raise ValueError("Temporal executor requires outcome_forecast task")
        version = job.dataset_version
        if not version or any(not (c.isascii() and (c.isalnum() or c in "._-")) for c in version) or version in {".", ".."}:
            raise ValueError("Invalid dataset version")
        path = Path(get_ml_registry_dir()) / "datasets" / (version + ".jsonl")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Canonical temporal dataset missing")
        rows = []
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                data = json.loads(line)
                if not isinstance(data, dict) or not isinstance(data.get("timestamp"), str):
                    raise ValueError("Temporal records require timestamp")
                stamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError("Temporal timestamps must include timezone")
                value = data.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Temporal values must be finite numbers")
                if data.get("series_id", "default") != "default":
                    raise ValueError("Multiple series require separate datasets")
                rows.append((stamp.timestamp(), float(value)))
        if len(rows) < 30 or len(rows) > int(cfg.get("max_samples", 100000)):
            raise ValueError("Temporal dataset must contain 30 to configured max_samples observations")
        if any(rows[i][0] >= rows[i + 1][0] for i in range(len(rows) - 1)):
            raise ValueError("Timestamps must be strictly increasing without duplicates")
        lags = int(cfg.get("lags", 5))
        horizon = int(cfg.get("horizon", 1))
        test_split = float(cfg.get("test_split", 0.2))
        if not 2 <= lags <= 128 or not 1 <= horizon <= 32 or not 0.05 <= test_split <= 0.5:
            raise ValueError("Invalid temporal forecast configuration")
        values = np.asarray([v for _, v in rows], dtype=np.float64)
        # y[t] is horizon steps after the final observed lag at time t-horizon.
        X = np.asarray([values[i-lags:i] for i in range(lags, len(values)-horizon+1)])
        y = np.asarray([values[i+horizon-1] for i in range(lags, len(values)-horizon+1)])
        split = len(X) - max(5, math.ceil(len(X) * test_split))
        if split < 10:
            raise ValueError("Not enough chronological train/holdout windows")
        # Purge overlapping boundary labels and ensure training never sees holdout targets.
        train_end = split - horizon
        if train_end < 10:
            raise ValueError("Insufficient embargoed training windows")
        model = Ridge(alpha=1.0)
        model.fit(X[:train_end], y[:train_end])
        prediction = model.predict(X[split:])
        actual = y[split:]
        mae = float(np.mean(np.abs(actual - prediction)))
        rmse = float(np.sqrt(np.mean((actual - prediction) ** 2)))
        baseline = X[split:, -1]
        baseline_mae = float(np.mean(np.abs(actual - baseline)))
        tenant = str(job.metadata.get("tenant_id") or "")
        if not tenant or tenant == "default":
            raise ValueError("Governed temporal training requires explicit tenant")
        key = hashlib.sha256(tenant.encode()).hexdigest()[:16]
        model_id = f"tenant-{key}-outcome_forecast-{job.job_id[:12]}"
        model_version = f"train-{job.job_id[:8]}"
        artifact = Path(get_ml_registry_dir()) / "topology" / model_id / model_version
        if artifact.exists():
            raise FileExistsError("Training artifact version already exists")
        artifact.mkdir(parents=True)
        joblib.dump(model, artifact / "model.joblib")
        (artifact / "feature_schema.json").write_text(json.dumps({
            "feature_version": "temporal-lags-v1",
            "feature_order": [f"lag_{i}" for i in range(lags, 0, -1)],
            "lags": lags, "horizon": horizon, "target": "value",
        }, sort_keys=True))
        metrics = {
            "executor": "timeseries", "mae": mae, "rmse": rmse,
            "baseline_mae": baseline_mae, "test_samples": int(len(actual)),
            "training_samples": int(train_end), "feature_version": "temporal-lags-v1",
            "temporal_validation": "chronological_holdout_with_embargo",
            "canonical_benchmark_status": "not_run", "model_id": model_id,
            "model_version": model_version, "training_job_id": job.job_id,
            "tenant_key": key, "tenant_scoped": True, "dataset_version": version,
        }
        (artifact / "training_metadata.json").write_text(json.dumps(metrics, sort_keys=True))
        return TrainingArtifact(
            artifact_path=str(artifact), artifact_hash=_hash_directory(artifact),
            model_id=model_id, model_version=model_version, task=job.task,
            dataset_version=version, training_config_version=job.training_config_version,
            metrics=metrics, resource_usage={"training_samples": train_end},
        )
