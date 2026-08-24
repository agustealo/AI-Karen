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
    EXECUTION_TOPOLOGY = "execution_topology"


EXECUTION_TOPOLOGY_LABELS = {
    "direct": "direct",
    "reasoning": "reasoning",
    "workflow": "workflow",
    "multi_agent": "multi_agent",
}


class TopologyPredictionLabels:
    @staticmethod
    def canonical() -> dict[str, str]:
        return dict(EXECUTION_TOPOLOGY_LABELS)

    @staticmethod
    def to_enum(label: str) -> str:
        canonical_map = EXECUTION_TOPOLOGY_LABELS
        if label not in canonical_map:
            raise ValueError(f"Invalid topology label: {label}")
        return canonical_map[label]


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


@dataclass
class CalibrationContext:
    task: PredictionTask
    model_id: str
    model_version: str
    feature_version: str
    predicted_label: str
    dataset_version: str = "ml-eval-v1"


@dataclass
class CalibratedProbability:
    raw_probability: float
    calibrated_probability: float
    calibration_version: str
    method: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShadowEvaluation:
    evaluation_id: str
    purpose: str
    active_model_id: str
    active_model_version: str
    shadow_model_id: str
    shadow_model_version: str
    feature_version: str
    input_text: str
    input_features: dict[str, Any] = field(default_factory=dict)
    active_prediction: Prediction | None = None
    shadow_prediction: Prediction | None = None
    agreement: bool = False
    label_match: bool = False
    confidence_delta: float = 0.0
    latency_delta_ms: float = 0.0
    active_correct: bool | None = None
    shadow_correct: bool | None = None
    active_fallback: bool = False
    shadow_fallback: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShadowComparisonResult:
    evaluation_id: str
    purpose: str
    active_model_id: str
    shadow_model_id: str
    dataset_version: str
    sample_count: int
    agreement_rate: float
    label_disagreement_count: int
    avg_confidence_delta: float
    avg_latency_delta_ms: float
    fallback_delta: float
    regression_count: int
    active_fallback_rate: float
    shadow_fallback_rate: float
    active_accuracy: float | None = None
    shadow_accuracy: float | None = None
    evaluations: list[ShadowEvaluation] = field(default_factory=list)
