from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import (
    ModelStatus,
    Prediction,
    PredictionTask,
    SemanticEncoder,
    SemanticEncoding,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

logger = logging.getLogger(__name__)


class MLRuntime:
    def __init__(self, registry: MLModelRegistry | None = None) -> None:
        self._registry = registry or MLModelRegistry()
        self._encoders: dict[str, SemanticEncoder] = {}
        self._predictors: dict[PredictionTask, Any] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True

    def register_encoder(self, model_id: str, encoder: SemanticEncoder) -> None:
        self._encoders[model_id] = encoder

    def get_encoder(self, model_id: str) -> SemanticEncoder | None:
        return self._encoders.get(model_id)

    def register_predictor(self, task: PredictionTask, predictor: Any) -> None:
        self._predictors[task] = predictor

    def get_predictor(self, task: PredictionTask) -> Any | None:
        return self._predictors.get(task)

    async def encode(self, text: str, model_id: str = "default") -> SemanticEncoding | None:
        encoder = self.get_encoder(model_id)
        if encoder is None:
            return None
        try:
            return await encoder.encode(text)
        except Exception as exc:
            logger.debug("MLRuntime encode failed: %s", exc)
            return None

    async def encode_batch(self, texts: list[str], model_id: str = "default") -> list[SemanticEncoding | None]:
        encoder = self.get_encoder(model_id)
        if encoder is None:
            return [None] * len(texts)
        try:
            return await encoder.encode_batch(texts)
        except Exception as exc:
            logger.debug("MLRuntime encode_batch failed: %s", exc)
            return [None] * len(texts)

    async def predict(self, features: IntelligenceFeatures, task: PredictionTask) -> Prediction | None:
        predictor = self.get_predictor(task)
        if predictor is None:
            return None
        try:
            return await predictor.predict(features)
        except Exception as exc:
            logger.debug("MLRuntime predict failed for %s: %s", task, exc)
            return None

    async def predict_batch(self, features_list: list[IntelligenceFeatures], task: PredictionTask) -> list[Prediction | None]:
        predictor = self.get_predictor(task)
        if predictor is None:
            return [None] * len(features_list)
        try:
            return await predictor.predict_batch(features_list)
        except Exception as exc:
            logger.debug("MLRuntime predict_batch failed for %s: %s", task, exc)
            return [None] * len(features_list)

    async def health(self) -> dict[str, Any]:
        encoder_health = {}
        for model_id, encoder in self._encoders.items():
            try:
                encoder_health[model_id] = await encoder.health()
            except Exception as exc:
                encoder_health[model_id] = {"status": "error", "error": str(exc)}

        predictor_health = {}
        for task, predictor in self._predictors.items():
            try:
                predictor_health[task.value] = await predictor.health()
            except Exception as exc:
                predictor_health[task.value] = {"status": "error", "error": str(exc)}

        active_models = [m.model_id for m in self._registry.list_all() if m.status == ModelStatus.ACTIVE.value]
        shadow_models = [m.model_id for m in self._registry.list_all() if m.status == ModelStatus.SHADOW.value]

        overall = "healthy"
        for h in list(encoder_health.values()) + list(predictor_health.values()):
            if isinstance(h, dict) and h.get("status") in ("degraded", "unavailable", "error"):
                overall = "degraded"
                break

        return {
            "encoders": encoder_health,
            "predictors": predictor_health,
            "registry": {
                "active": active_models,
                "shadow": shadow_models,
            },
            "overall": overall,
        }

    async def model_metadata(self, model_id: str) -> dict[str, Any] | None:
        encoder = self.get_encoder(model_id)
        if encoder is None:
            return None
        try:
            return await encoder.metadata()
        except Exception as exc:
            logger.debug("MLRuntime model_metadata failed: %s", exc)
            return None
