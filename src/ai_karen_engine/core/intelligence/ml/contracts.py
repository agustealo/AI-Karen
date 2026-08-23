from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures


class PredictionTask(str, Enum):
    INTENT = "intent"
    DOMAIN = "domain"
    COMPLEXITY = "complexity"
    AMBIGUITY = "ambiguity"
    MEMORY_RELEVANCE = "memory_relevance"
    CAPABILITY = "capability"
    COLLABORATION_VALUE = "collaboration_value"
    VERIFICATION_VALUE = "verification_value"


@dataclass
class Prediction:
    task: PredictionTask
    label: str = ""
    value: Any = None
    probability: float = 0.0
    confidence: float = 0.0
    model_id: str = ""
    model_version: str = ""
    feature_version: str = "v1"
    calibration_version: str = ""
    calibrated: bool = False
    fallback_used: bool = False
    latency_ms: float = 0.0
    inference_method: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SemanticEncoding:
    vector: list[float]
    dimensions: int
    model_id: str
    model_version: str
    normalized: bool = False
    fallback_used: bool = False
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class EncoderHealthStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SemanticEncoder:
    async def encode(self, text: str) -> SemanticEncoding: ...
    async def encode_batch(self, texts: list[str]) -> list[SemanticEncoding]: ...
    async def health(self) -> dict[str, Any]: ...
    async def metadata(self) -> dict[str, Any]: ...


class Predictor:
    async def predict(self, features: IntelligenceFeatures) -> Prediction: ...
    async def predict_batch(self, features_list: list[IntelligenceFeatures]) -> list[Prediction]: ...
    async def health(self) -> dict[str, Any]: ...
    async def metadata(self) -> dict[str, Any]: ...


@dataclass
class MLModelManifest:
    model_id: str
    purpose: str
    architecture: str
    artifact_path: str
    artifact_hash: str
    model_version: str
    feature_version: str
    training_dataset_version: str = ""
    calibration_version: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    status: str = "CANDIDATE"


class ModelStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
