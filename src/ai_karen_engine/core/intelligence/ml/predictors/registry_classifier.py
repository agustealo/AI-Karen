from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.calibration import CalibrationService
from ai_karen_engine.core.intelligence.ml.contracts import (
    CalibrationContext,
    MLModelManifest,
    Prediction,
    PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

logger = logging.getLogger(__name__)


class RegistryBackedClassifier(BasePredictor):
    """Run a promoted sklearn classifier from the canonical ML registry.

    The classifier does not provide a heuristic answer when a model is absent,
    incompatible, or missing required features. That is intentional for learned
    affect, preference, behavior, and forecasting signals: unknown must remain
    unknown rather than becoming a fabricated personal inference.
    """

    def __init__(
        self,
        task: PredictionTask,
        ml_runtime: Any = None,
        *,
        registry: MLModelRegistry | None = None,
    ) -> None:
        super().__init__(ml_runtime)
        self._task = task
        self._registry = (
            registry
            or (
                ml_runtime._registry
                if ml_runtime is not None and hasattr(ml_runtime, "_registry")
                else None
            )
            or MLModelRegistry()
        )
        self._calibration = CalibrationService()
        self._loaded_manifest: MLModelManifest | None = None
        self._loaded_model: Any = None
        self._feature_order: list[str] = []

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        manifest = self._active_manifest()
        if manifest is None:
            return self._unknown(features, "no_active_model")

        try:
            model, feature_order = self._load_artifact(manifest)
            feature_values = self._feature_values(features, feature_order)
            probabilities = model.predict_proba(
                np.array([feature_values], dtype=np.float64)
            )[0]
            labels = [str(label) for label in getattr(model, "classes_", [])]
            if not labels or len(labels) != len(probabilities):
                return self._unknown(features, "invalid_class_schema", manifest)

            winner = int(np.argmax(probabilities))
            label = labels[winner]
            probability = float(probabilities[winner])
            calibrated = self._calibration.calibrate_prediction(
                Prediction(
                    task=self._task,
                    label=label,
                    probability=probability,
                    confidence=probability,
                    model_id=manifest.model_id,
                    model_version=manifest.model_version,
                    feature_version=manifest.feature_version,
                    calibration_version=manifest.calibration_version
                    or "calib-identity-v1",
                    inference_method="registry_model",
                ),
                CalibrationContext(
                    task=self._task,
                    model_id=manifest.model_id,
                    model_version=manifest.model_version,
                    feature_version=manifest.feature_version,
                    predicted_label=label,
                    dataset_version=manifest.training_dataset_version,
                ),
            )
            return Prediction(
                task=self._task,
                label=label,
                probability=probability,
                confidence=calibrated.calibrated_probability,
                model_id=manifest.model_id,
                model_version=manifest.model_version,
                feature_version=manifest.feature_version,
                calibration_version=calibrated.calibration_version,
                calibrated=True,
                fallback_used=False,
                inference_method="registry_model",
                metadata={
                    "probabilities": {
                        candidate: float(score)
                        for candidate, score in zip(labels, probabilities)
                    },
                    "training_dataset_version": manifest.training_dataset_version,
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "Registry classifier feature contract unavailable for %s: %s",
                self._task.value,
                exc,
            )
            return self._unknown(
                features,
                "feature_contract_unavailable",
                manifest,
                detail=str(exc),
            )
        except Exception as exc:
            logger.warning(
                "Registry classifier failed for %s: %s",
                self._task.value,
                exc,
            )
            return self._unknown(
                features,
                "prediction_exception",
                manifest,
                detail=type(exc).__name__,
            )

    async def health(self) -> dict[str, Any]:
        manifest = self._active_manifest()
        if manifest is None:
            return {
                "status": "unavailable",
                "task": self._task.value,
                "reason": "no_active_model",
            }
        artifact = Path(manifest.artifact_path)
        missing = [
            filename
            for filename in ("model.joblib", "feature_schema.json")
            if not (artifact / filename).exists()
        ]
        if not missing and (
            not manifest.artifact_hash
            or not self._registry.validate_artifact(manifest)
        ):
            return {
                "status": "degraded",
                "task": self._task.value,
                "model_id": manifest.model_id,
                "reason": "artifact_integrity_unverified",
            }
        if missing:
            return {
                "status": "degraded",
                "task": self._task.value,
                "model_id": manifest.model_id,
                "reason": "artifact_incomplete",
                "missing": missing,
            }
        return {
            "status": "ready",
            "task": self._task.value,
            "model_id": manifest.model_id,
            "model_version": manifest.model_version,
        }

    async def metadata(self) -> dict[str, Any]:
        manifest = self._active_manifest()
        return {
            "predictor": self.__class__.__name__,
            "task": self._task.value,
            "model_id": manifest.model_id if manifest else None,
            "model_version": manifest.model_version if manifest else None,
        }

    def _active_manifest(self) -> MLModelManifest | None:
        try:
            return self._registry.get_active(self._task.value)
        except Exception as exc:
            logger.debug(
                "Failed to resolve active model for %s: %s",
                self._task.value,
                exc,
            )
            return None

    def _load_artifact(
        self,
        manifest: MLModelManifest,
    ) -> tuple[Any, list[str]]:
        if self._loaded_manifest == manifest and self._loaded_model is not None:
            return self._loaded_model, list(self._feature_order)

        artifact = Path(manifest.artifact_path)
        model_path = artifact / "model.joblib"
        schema_path = artifact / "feature_schema.json"
        if not model_path.exists() or not schema_path.exists():
            raise ValueError("active model artifact is incomplete")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        feature_order = schema.get("feature_order")
        if not isinstance(feature_order, list) or not feature_order:
            raise ValueError("feature_schema.feature_order is missing")
        schema_version = str(schema.get("feature_version") or "")
        if schema_version and schema_version != manifest.feature_version:
            raise ValueError(
                "feature schema version does not match active manifest"
            )

        if not manifest.artifact_hash or not self._registry.validate_artifact(manifest):
            raise ValueError("active model artifact integrity is not verified")

        model = joblib.load(str(model_path))
        self._loaded_manifest = manifest
        self._loaded_model = model
        self._feature_order = [str(name) for name in feature_order]
        return model, list(self._feature_order)

    @classmethod
    def _feature_values(
        cls,
        features: IntelligenceFeatures,
        feature_order: list[str],
    ) -> list[float]:
        return [
            cls._coerce_numeric(cls._resolve_feature(features, name), name)
            for name in feature_order
        ]

    @staticmethod
    def _resolve_feature(features: IntelligenceFeatures, name: str) -> Any:
        top_level = {
            "token_count": features.token_count,
            "sentence_count": features.sentence_count,
            "entity_count": features.entity_count,
        }
        if name in top_level:
            return top_level[name]

        if name.startswith("semantic_embedding_"):
            index_text = name.removeprefix("semantic_embedding_")
            index = int(index_text)
            embedding = features.semantic_embedding or []
            if index < 0 or index >= len(embedding):
                raise KeyError(name)
            return embedding[index]

        namespaces = {
            "request": features.request_features,
            "conversation": features.conversation_features,
            "temporal": features.temporal_features,
            "linguistic": features.linguistic_features,
            "syntax": features.syntax_features,
        }
        if "." in name:
            prefix, path = name.split(".", 1)
            if prefix in namespaces:
                return RegistryBackedClassifier._nested_lookup(
                    namespaces[prefix],
                    path,
                )

        matches: list[Any] = []
        for values in namespaces.values():
            if name in values:
                matches.append(values[name])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(f"ambiguous feature: {name}")
        raise KeyError(name)

    @staticmethod
    def _nested_lookup(values: dict[str, Any], path: str) -> Any:
        current: Any = values
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise KeyError(path)
            current = current[part]
        return current

    @staticmethod
    def _coerce_numeric(value: Any, name: str) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        raise TypeError(f"feature {name} is not numeric")

    def _unknown(
        self,
        features: IntelligenceFeatures,
        reason: str,
        manifest: MLModelManifest | None = None,
        *,
        detail: str | None = None,
    ) -> Prediction:
        metadata: dict[str, Any] = {"reason": reason}
        if detail:
            metadata["detail"] = detail
        return Prediction(
            task=self._task,
            label="unknown",
            probability=0.0,
            confidence=0.0,
            model_id=manifest.model_id if manifest else "",
            model_version=manifest.model_version if manifest else "",
            feature_version=(
                manifest.feature_version if manifest else features.feature_version
            ),
            fallback_used=True,
            inference_method="model_unavailable",
            metadata=metadata,
        )


__all__ = ["RegistryBackedClassifier"]
