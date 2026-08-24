from __future__ import annotations

import logging
import math
import time
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkConfig,
    BenchmarkResult,
    EvaluationCase,
    MetricResult,
    PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import CanonicalEvaluationCorpus
from ai_karen_engine.core.intelligence.ml.evaluation.metrics import (
    compute_brier_score,
    compute_capability_metrics,
    compute_classification_metrics,
    compute_ece,
    compute_latency_metrics,
)

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    def __init__(self, corpus: CanonicalEvaluationCorpus | None = None) -> None:
        self._corpus = corpus or CanonicalEvaluationCorpus()

    async def run(
        self,
        predictor: Any,
        config: BenchmarkConfig,
    ) -> BenchmarkResult:
        cases = self._corpus.get_cases(
            task=config.task,
            difficulty=config.difficulty,
            tags=config.tags,
            case_ids=config.case_ids,
        )
        if not cases:
            return self._empty_result(config)

        outcomes: list[PredictionOutcome] = []
        for case in cases:
            outcome = await self._run_case(predictor, case)
            outcomes.append(outcome)

        metrics = self._collect_metrics(outcomes, config.task)
        latency_metrics = compute_latency_metrics(outcomes)
        metrics.update(latency_metrics)

        error_count = sum(1 for o in outcomes if o.error is not None)
        fallback_count = sum(1 for o in outcomes if o.fallback_used)
        abstention_count = sum(
            1 for o in outcomes
            if o.prediction is None
            or (hasattr(o.prediction, "label") and o.prediction.label in ("", "unknown"))
        )

        latencies = sorted(o.latency_ms for o in outcomes if o.latency_ms > 0)
        p50 = self._percentile(latencies, 0.50)
        p95 = self._percentile(latencies, 0.95)

        return BenchmarkResult(
            model_id=config.model_id,
            model_version=config.model_version,
            task=config.task,
            dataset_version=config.dataset_version,
            sample_count=len(cases),
            metrics=metrics,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            error_count=error_count,
            fallback_count=fallback_count,
            abstention_count=abstention_count,
            outcomes=outcomes,
        )

    async def _run_case(self, predictor: Any, case: EvaluationCase) -> PredictionOutcome:
        features = IntelligenceFeatures(
            text=case.input_text,
            **case.features,
        )
        prediction: Prediction | None = None
        error: str | None = None
        latency_ms = 0.0
        fallback_used = False

        start = time.perf_counter()
        try:
            result = predictor.predict(features)
            if hasattr(result, "__await__"):
                prediction = await result
            else:
                prediction = result
            latency_ms = (time.perf_counter() - start) * 1000.0
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            error = str(exc)
            logger.debug("Benchmark case %s failed: %s", case.case_id, exc)

        if prediction is not None:
            fallback_used = bool(getattr(prediction, "fallback_used", False))

        correct = self._is_correct(case, prediction)
        raw_prob = 0.0
        calibrated_prob = 0.0
        if prediction is not None:
            raw_prob = prediction.probability if prediction.probability > 0 else prediction.confidence
            calibrated_prob = raw_prob

        return PredictionOutcome(
            case_id=case.case_id,
            task=case.task,
            prediction=prediction,
            expected_label=case.expected_label,
            expected_value=case.expected_value,
            correct=correct,
            raw_probability=raw_prob,
            calibrated_probability=calibrated_prob,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            error=error,
        )

    def _is_correct(self, case: EvaluationCase, prediction: Prediction | None) -> bool:
        if prediction is None:
            return False
        if case.task == PredictionTask.CAPABILITY:
            expected = set(case.expected_value or [])
            predicted = {
                cap for cap, score in (prediction.value or {}).items() if score >= 0.3
            }
            return predicted == expected
        if case.task == PredictionTask.MEMORY_RELEVANCE:
            return prediction.label == case.expected_label
        return prediction.label == case.expected_label

    def _collect_metrics(
        self, outcomes: list[PredictionOutcome], task: PredictionTask
    ) -> dict[str, MetricResult]:
        metrics: dict[str, MetricResult] = {}

        if task == PredictionTask.CAPABILITY:
            metrics.update(compute_capability_metrics(outcomes))
        else:
            metrics.update(compute_classification_metrics(outcomes))

        metrics["brier_score"] = compute_brier_score(outcomes)
        ece_result, _ = compute_ece(outcomes)
        metrics["ece"] = ece_result

        return metrics

    def _empty_result(self, config: BenchmarkConfig) -> BenchmarkResult:
        return BenchmarkResult(
            model_id=config.model_id,
            model_version=config.model_version,
            task=config.task,
            dataset_version=config.dataset_version,
            sample_count=0,
            metrics={},
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            error_count=0,
            fallback_count=0,
            abstention_count=0,
        )

    @staticmethod
    def _percentile(sorted_data: list[float], p: float) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

