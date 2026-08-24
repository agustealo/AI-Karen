from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ai_karen_engine.config.config_manager import (
    get_ml_topology_feature_version,
    get_ml_topology_min_confidence,
)
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.calibration import CalibrationService
from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest,
    Prediction,
    PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor
from ai_karen_engine.core.intelligence.ml.predictors.topology_features import (
    TopologyFeatureVector,
    build_topology_feature_vector,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

logger = logging.getLogger(__name__)


class ExecutionTopologyPredictor(BasePredictor):
    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder
        self._registry = ml_runtime._registry if ml_runtime and hasattr(ml_runtime, "_registry") else MLModelRegistry()
        self._calibration_service = CalibrationService()
        self._loaded_model: Any = None
        self._loaded_manifest: MLModelManifest | None = None
        self._class_labels: list[str] = []

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        try:
            manifest = self._registry.get_active(PredictionTask.EXECUTION_TOPOLOGY.value)
        except Exception as exc:
            logger.debug("Failed to load topology manifest: %s", exc)
            manifest = None

        if manifest is None:
            return self._baseline_prediction(features, "no_model")

        try:
            if not self._is_compatible_manifest(manifest):
                return self._baseline_prediction(features, "incompatible_feature_version")

            model = self._load_model(manifest)
            if model is None:
                return self._baseline_prediction(features, "model_load_failed")

            vector = build_topology_feature_vector(features)
            expected_feature_version = get_ml_topology_feature_version()
            if vector.feature_version != expected_feature_version:
                return self._baseline_prediction(features, "feature_version_mismatch")

            feature_array = np.array([list(vector.features.values())], dtype=np.float64)
            probabilities = model.predict_proba(feature_array)[0]

            class_labels = getattr(model, "classes_", self._class_labels)
            if len(class_labels) != len(probabilities):
                class_labels = self._class_labels

            proba_map = {str(label): float(prob) for label, prob in zip(class_labels, probabilities)}
            max_idx = int(np.argmax(probabilities))
            label = str(class_labels[max_idx])
            confidence = float(probabilities[max_idx])

            min_confidence = get_ml_topology_min_confidence()
            if confidence < min_confidence:
                return self._baseline_prediction(features, "low_confidence")

            context = self._calibration_context(manifest, label)
            calibrated = self._calibration_service.calibrate_prediction(
                Prediction(
                    task=PredictionTask.EXECUTION_TOPOLOGY,
                    label=label,
                    probability=confidence,
                    confidence=confidence,
                    model_id=manifest.model_id,
                    model_version=manifest.model_version,
                    feature_version=vector.feature_version,
                    calibration_version=manifest.calibration_version or "calib-identity-v1",
                    inference_method="learned_model",
                ),
                context,
            )

            return Prediction(
                task=PredictionTask.EXECUTION_TOPOLOGY,
                label=label,
                probability=confidence,
                confidence=calibrated.calibrated_probability,
                model_id=manifest.model_id,
                model_version=manifest.model_version,
                feature_version=vector.feature_version,
                calibration_version=calibrated.calibration_version,
                calibrated=True,
                inference_method="learned_model",
                metadata={"probabilities": proba_map},
            )
        except Exception as exc:
            logger.debug("Topology prediction failed: %s", exc)
            return self._baseline_prediction(features, "prediction_exception")

    async def predict_batch(self, features_list: list[IntelligenceFeatures]) -> list[Prediction]:
        return [await self.predict(f) for f in features_list]

    async def health(self) -> dict[str, Any]:
        try:
            manifest = self._registry.get_active(PredictionTask.EXECUTION_TOPOLOGY.value)
            if manifest is None:
                return {"status": "unavailable", "reason": "no_active_model"}
            if not self._validate_artifact_path(manifest):
                return {"status": "degraded", "reason": "artifact_missing"}
            return {"status": "ready", "model_id": manifest.model_id, "model_version": manifest.model_version}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def metadata(self) -> dict[str, Any]:
        return {"predictor": self.__class__.__name__, "task": PredictionTask.EXECUTION_TOPOLOGY.value}

    def _is_compatible_manifest(self, manifest: MLModelManifest) -> bool:
        expected = get_ml_topology_feature_version()
        return manifest.feature_version == expected

    def _load_model(self, manifest: MLModelManifest) -> Any:
        if self._loaded_manifest == manifest and self._loaded_model is not None:
            return self._loaded_model

        model_path = Path(manifest.artifact_path) / "model.joblib"
        if not model_path.exists():
            return None

        model = joblib.load(str(model_path))
        self._loaded_model = model
        self._loaded_manifest = manifest
        self._class_labels = [
            label for label in getattr(model, "classes_", [])
        ]
        return model

    def _validate_artifact_path(self, manifest: MLModelManifest) -> bool:
        path = Path(manifest.artifact_path)
        if not path.exists():
            return False
        return (path / "model.joblib").exists()

    def _calibration_context(self, manifest: MLModelManifest, predicted_label: str):
        from ai_karen_engine.core.intelligence.ml.contracts import CalibrationContext
        return CalibrationContext(
            task=PredictionTask.EXECUTION_TOPOLOGY,
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            feature_version=manifest.feature_version,
            predicted_label=predicted_label,
            dataset_version=manifest.training_dataset_version,
        )

    def _baseline_prediction(self, features: IntelligenceFeatures, reason: str) -> Prediction:
        vector = build_topology_feature_vector(features)
        label = self._deterministic_baseline_label(features, vector)
        confidence = 0.5
        return Prediction(
            task=PredictionTask.EXECUTION_TOPOLOGY,
            label=label,
            probability=confidence,
            confidence=confidence,
            fallback_used=True,
            inference_method="deterministic_baseline",
            metadata={
                "probabilities": {
                    "direct": 0.25,
                    "reasoning": 0.25,
                    "workflow": 0.25,
                    "multi_agent": 0.25,
                }
            },
        )

    def _deterministic_baseline_label(self, features: IntelligenceFeatures, vector: TopologyFeatureVector) -> str:
        if vector.multiple_actions or vector.dependency_chain or vector.parallelizable:
            return "workflow"
        if vector.deep_reasoning or vector.code_execution_hint:
            return "reasoning"
        if len(features.request_features.get("tool_requirements", [])) > 2:
            return "multi_agent"
        return "direct"
