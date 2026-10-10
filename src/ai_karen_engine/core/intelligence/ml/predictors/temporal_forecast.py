"""Tenant-scoped deterministic temporal inference for candidate and active models.

This predictor consumes an ordered lag window, not generic IntelligenceFeatures.
It returns no fabricated forecast when a model or feature contract is absent.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import joblib
import numpy as np

from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.contracts import ModelStatus


class TemporalForecastPredictor:
    def __init__(self, registry: MLModelRegistry | None = None) -> None:
        self.registry = registry or MLModelRegistry()

    def forecast(
        self, *, tenant_id: str, recent_values: list[float],
        candidate_model_id: str | None = None,
    ) -> dict:
        if not tenant_id or tenant_id == "default":
            raise PermissionError("Tenant identity required")
        if candidate_model_id:
            import hashlib
            key = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
            if not candidate_model_id.startswith(f"tenant-{key}-"):
                raise PermissionError("Candidate does not belong to tenant")
            manifest = self.registry.get(candidate_model_id)
            if manifest is None or manifest.status != ModelStatus.CANDIDATE.value:
                raise ValueError("Candidate not available")
        else:
            manifest = self.registry.get_active("outcome_forecast", tenant_id=tenant_id)
        if manifest is None or manifest.metrics.get("executor") != "timeseries":
            raise ValueError("No eligible temporal forecast model")
        if not manifest.artifact_hash or not self.registry.validate_artifact(manifest):
            raise ValueError("Temporal model integrity check failed")
        # A trusted receipt alone is insufficient if a path can escape the
        # canonical model/version layout or introduce a symlink to a pickle.
        root = Path(manifest.artifact_path)
        if (
            not root.is_dir()
            or root.is_symlink()
            or root.name != manifest.model_version
            or root.parent.name != manifest.model_id
            or root.parent.parent.name != "topology"
            or root.resolve() != root.absolute()
            or any(entry.is_symlink() for entry in root.rglob("*"))
            or not (root / "model.joblib").is_file()
            or not (root / "feature_schema.json").is_file()
        ):
            raise ValueError("Unsafe temporal artifact layout")
        schema = json.loads((root / "feature_schema.json").read_text(encoding="utf-8"))
        lags = schema.get("lags")
        horizon = schema.get("horizon")
        if schema.get("feature_version") != manifest.feature_version or schema.get("target") != "value":
            raise ValueError("Temporal feature schema identity mismatch")
        if not isinstance(lags, int) or isinstance(lags, bool) or not 2 <= lags <= 128:
            raise ValueError("Invalid lag schema")
        if not isinstance(horizon, int) or isinstance(horizon, bool) or not 1 <= horizon <= 32:
            raise ValueError("Invalid forecast horizon")
        if not isinstance(recent_values, list) or len(recent_values) != lags:
            raise ValueError("Expected exactly the trained lag window")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in recent_values):
            raise ValueError("Lag values must be finite numbers")
        model = joblib.load(root / "model.joblib")
        prediction = float(model.predict(np.asarray([recent_values], dtype=np.float64))[0])
        if not math.isfinite(prediction):
            raise ValueError("Forecast is nonfinite")
        return {
            "value": prediction, "horizon": horizon, "model_id": manifest.model_id,
            "model_version": manifest.model_version, "status": manifest.status,
            "validation_mae": manifest.metrics.get("mae"),
            "baseline_mae": manifest.metrics.get("baseline_mae"),
        }
