from __future__ import annotations

import logging
import time
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
from ai_karen_engine.monitoring.ml_metrics import get_ml_metrics

logger = logging.getLogger(__name__)


class MLRuntime:
    def __init__(self, registry: MLModelRegistry | None = None) -> None:
        self._registry = registry or MLModelRegistry()
        self._encoders: dict[str, SemanticEncoder] = {}
        self._predictors: dict[PredictionTask, Any] = {}
        self._initialized = False
        self._ml_metrics = get_ml_metrics()
        self._default_encoder_model_id = "default"

    async def initialize(self, encoder_config: Any = None) -> None:
        if self._initialized:
            return
        self._initialized = True
        await self._wire_default_encoder(encoder_config)

    async def _wire_default_encoder(self, encoder_config: Any = None) -> None:
        encoder = await self._resolve_encoder(encoder_config)
        if encoder is not None:
            self.register_encoder(self._default_encoder_model_id, encoder)
            logger.info("MLRuntime: registered default encoder %s", self._default_encoder_model_id)
        else:
            logger.warning("MLRuntime: no default encoder available; predictors will use heuristic fallback")

    async def _resolve_encoder(self, encoder_config: Any = None) -> SemanticEncoder | None:
        if encoder_config is not None:
            return self._build_encoder_from_config(encoder_config)

        manifest = self._registry.get_active("semantic_encoding")
        if manifest is not None:
            return self._build_encoder_from_manifest(manifest)

        return self._build_default_encoder()

    def _build_encoder_from_config(self, encoder_config: Any) -> SemanticEncoder | None:
        try:
            from ai_karen_engine.core.intelligence.ml.encoders.distilbert import DistilBertSemanticEncoder
            return DistilBertSemanticEncoder(config=encoder_config, registry=self._registry)
        except Exception as exc:
            logger.error("MLRuntime: failed to build encoder from config: %s", exc)
            self._ml_metrics.record_model_load_failure(getattr(encoder_config, "model_name", "unknown"), type(exc).__name__)
            return None

    def _build_encoder_from_manifest(self, manifest: Any) -> SemanticEncoder | None:
        try:
            from ai_karen_engine.core.intelligence.ml.encoders.distilbert import DistilBertSemanticEncoder
            from ai_karen_engine.core.intelligence.ml.distilbert_config import DistilBertConfig
            config = DistilBertConfig(
                model_name=manifest.model_id,
                local_model_root=str(manifest.artifact_path),
            )
            encoder = DistilBertSemanticEncoder(config=config, registry=self._registry)
            if encoder.fallback_mode:
                logger.warning("MLRuntime: encoder from manifest %s is in fallback mode", manifest.model_id)
            return encoder
        except Exception as exc:
            logger.error("MLRuntime: failed to build encoder from manifest %s: %s", manifest.model_id, exc)
            self._ml_metrics.record_model_load_failure(manifest.model_id, type(exc).__name__)
            return None

    def _build_default_encoder(self) -> SemanticEncoder | None:
        try:
            from ai_karen_engine.core.intelligence.ml.encoders.distilbert import DistilBertSemanticEncoder
            from ai_karen_engine.core.intelligence.ml.distilbert_config import DistilBertConfig
            config = DistilBertConfig()
            encoder = DistilBertSemanticEncoder(config=config, registry=self._registry)
            if encoder.fallback_mode:
                logger.info("MLRuntime: default DistilBERT encoder running in fallback mode")
            return encoder
        except Exception as exc:
            logger.error("MLRuntime: failed to build default encoder: %s", exc)
            self._ml_metrics.record_model_load_failure("distilbert-base-uncased", type(exc).__name__)
            return None

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
            start = time.perf_counter()
            result = await encoder.encode(text)
            duration = time.perf_counter() - start
            if result is not None:
                self._ml_metrics.record_inference(
                    prediction_task="encode",
                    model_id=result.model_id or model_id,
                    model_version=result.model_version or "unknown",
                    status="success",
                    duration_seconds=duration,
                )
            return result
        except Exception as exc:
            logger.debug("MLRuntime encode failed: %s", exc)
            self._ml_metrics.record_model_load_failure(model_id, type(exc).__name__)
            return None

    async def encode_batch(self, texts: list[str], model_id: str = "default") -> list[SemanticEncoding | None]:
        encoder = self.get_encoder(model_id)
        if encoder is None:
            return [None] * len(texts)
        try:
            start = time.perf_counter()
            results = await encoder.encode_batch(texts)
            duration = time.perf_counter() - start
            success_count = sum(1 for r in results if r is not None)
            if success_count:
                self._ml_metrics.record_inference(
                    prediction_task="encode_batch",
                    model_id=model_id,
                    model_version="unknown",
                    status="success",
                    duration_seconds=duration,
                )
            return results
        except Exception as exc:
            logger.debug("MLRuntime encode_batch failed: %s", exc)
            self._ml_metrics.record_model_load_failure(model_id, type(exc).__name__)
            return [None] * len(texts)

    async def predict(self, features: IntelligenceFeatures, task: PredictionTask) -> Prediction | None:
        predictor = self.get_predictor(task)
        if predictor is None:
            return None
        try:
            start = time.perf_counter()
            result = await predictor.predict(features)
            duration = time.perf_counter() - start
            if result is not None:
                result.task = task
                result.latency_ms = duration * 1000.0
                self._ml_metrics.record_inference(
                    prediction_task=task.value,
                    model_id=getattr(result, "model_id", "unknown") or "unknown",
                    model_version=getattr(result, "model_version", "unknown") or "unknown",
                    status="success",
                    duration_seconds=duration,
                )
            return result
        except Exception as exc:
            logger.debug("MLRuntime predict failed for %s: %s", task, exc)
            self._ml_metrics.record_fallback(
                prediction_task=task.value,
                model_id="unknown",
                fallback_reason=type(exc).__name__,
            )
            return None

    async def predict_batch(self, features_list: list[IntelligenceFeatures], task: PredictionTask) -> list[Prediction | None]:
        predictor = self.get_predictor(task)
        if predictor is None:
            return [None] * len(features_list)
        try:
            start = time.perf_counter()
            results = await predictor.predict_batch(features_list)
            duration = time.perf_counter() - start
            success_count = sum(1 for r in results if r is not None)
            if success_count:
                self._ml_metrics.record_inference(
                    prediction_task=f"{task.value}_batch",
                    model_id="unknown",
                    model_version="unknown",
                    status="success",
                    duration_seconds=duration,
                )
            return results
        except Exception as exc:
            logger.debug("MLRuntime predict_batch failed for %s: %s", task, exc)
            self._ml_metrics.record_fallback(
                prediction_task=f"{task.value}_batch",
                model_id="unknown",
                fallback_reason=type(exc).__name__,
            )
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

        configured_encoder = self._registry.get_active("semantic_encoding")
        encoder_missing = configured_encoder is not None and self._default_encoder_model_id not in self._encoders

        overall = "healthy"
        for h in list(encoder_health.values()) + list(predictor_health.values()):
            if isinstance(h, dict) and h.get("status") in ("degraded", "unavailable", "error"):
                overall = "degraded"
                break
        if encoder_missing:
            overall = "degraded"

        return {
            "encoders": encoder_health,
            "predictors": predictor_health,
            "registry": {
                "active": active_models,
                "shadow": shadow_models,
                "configured_encoder": configured_encoder.model_id if configured_encoder else None,
                "encoder_missing": encoder_missing,
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
