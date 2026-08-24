from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    task: PredictionTask
    input_text: str
    expected_label: str
    expected_value: Any = None
    tags: list[str] = field(default_factory=list)
    difficulty: str = "normal"
    source: str = "curated"
    dataset_version: str = "ml-eval-v1"
    features: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionOutcome:
    case_id: str
    task: PredictionTask
    prediction: Prediction | None
    expected_label: str
    expected_value: Any = None
    correct: bool = False
    raw_probability: float = 0.0
    calibrated_probability: float = 0.0
    latency_ms: float = 0.0
    fallback_used: bool = False
    error: str | None = None


@dataclass
class MetricResult:
    metric_name: str
    value: float
    sample_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalibrationBin:
    bin_start: float
    bin_end: float
    count: int
    avg_confidence: float
    avg_accuracy: float
    gap: float


@dataclass
class BenchmarkConfig:
    model_id: str
    model_version: str
    task: PredictionTask
    dataset_version: str = "ml-eval-v1"
    difficulty: str | None = None
    tags: list[str] | None = None
    case_ids: list[str] | None = None


@dataclass
class BenchmarkResult:
    model_id: str
    model_version: str
    task: PredictionTask
    dataset_version: str
    sample_count: int
    metrics: dict[str, MetricResult]
    latency_p50_ms: float
    latency_p95_ms: float
    error_count: int
    fallback_count: int
    abstention_count: int
    outcomes: list[PredictionOutcome] = field(default_factory=list)
