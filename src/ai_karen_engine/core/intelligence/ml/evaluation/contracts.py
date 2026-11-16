from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

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
    # Optional curator-declared grouping. No independence claim follows from
    # this string alone; independent grouping requires separately reviewed proof.
    evaluation_group_id: str | None = None


def evaluation_case_sha256(case: EvaluationCase) -> str | None:
    """Fingerprint the EXACT evaluated input and oracle contract in one owner.

    Return no attestation for unserializable/malformed cases; the benchmark
    runner still evaluates them but cannot claim curated-oracle provenance.
    """
    if (
        not isinstance(case, EvaluationCase)
        or not isinstance(case.task, PredictionTask)
        or not isinstance(case.case_id, str)
        or not case.case_id
    ):
        return None
    try:
        canonical = json.dumps(
            {
                "case_id": case.case_id,
                "task": case.task.value,
                "input_text": case.input_text,
                "expected_label": case.expected_label,
                "expected_value": case.expected_value,
                "tags": case.tags,
                "difficulty": case.difficulty,
                "source": case.source,
                "dataset_version": case.dataset_version,
                "features": case.features,
                "evaluation_group_id": case.evaluation_group_id,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        return None
    return hashlib.sha256(canonical).hexdigest()


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
    # Hash of the *actual* EvaluationCase passed to the canonical runner;
    # never a claim of independent oracle approval.
    evaluated_case_sha256: str = ""


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


@dataclass(frozen=True, slots=True)
class GovernedConfidenceEvaluation:
    """Shadow-only confidence calibration from principal-scoped evaluated labels.

    Scores describe observed, independently labelled predictor correctness,
    not global model accuracy, causal certainty or a RuntimePolicy grant.
    A missing/undersized corpus has absent scores, never numeric zeros.
    """

    task: PredictionTask
    model_id: str
    model_version: str
    feature_version: str
    status: Literal["insufficient_evidence", "evaluated_shadow"]
    sample_count: int
    minimum_samples: int
    window_limit: int
    evidence_version: str
    brier_score: MetricResult | None = None
    expected_calibration_error: MetricResult | None = None
    scope: str = field(default="principal_scoped_bounded_window", init=False)
    runtime_authorized: bool = field(default=False, init=False)
