from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask

logger = logging.getLogger(__name__)


@dataclass
class MLOutcomeRecord:
    outcome_id: str
    task: PredictionTask
    model_id: str
    model_version: str
    feature_version: str
    predicted_label: str
    expected_label: str
    correct: bool
    raw_probability: float
    calibrated_probability: float
    confidence: float
    latency_ms: float
    fallback_used: bool
    calibration_error: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class EvidenceProfile:
    model_id: str
    model_version: str
    task: PredictionTask
    sample_count: int = 0
    correct_count: int = 0
    total_latency_ms: float = 0.0
    total_calibration_error: float = 0.0
    fallback_count: int = 0
    confidence_sum: float = 0.0
    last_updated: str = ""

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.sample_count if self.sample_count > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.sample_count if self.sample_count > 0 else 0.0

    @property
    def avg_calibration_error(self) -> float:
        return self.total_calibration_error / self.sample_count if self.sample_count > 0 else 0.0

    @property
    def fallback_rate(self) -> float:
        return self.fallback_count / self.sample_count if self.sample_count > 0 else 0.0


@dataclass
class AdaptiveThresholds:
    confidence_threshold: float = 0.7
    latency_threshold_ms: float = 500.0
    calibration_error_threshold: float = 0.05
    fallback_rate_threshold: float = 0.2
    min_samples_for_adaptation: int = 20


class MLOutcomeCollector:
    def __init__(self, max_history: int = 10000) -> None:
        self._outcomes: list[MLOutcomeRecord] = []
        self._max_history = max_history

    def record(self, outcome: MLOutcomeRecord) -> None:
        if not outcome.timestamp:
            outcome.timestamp = time.time()
        self._outcomes.append(outcome)
        if len(self._outcomes) > self._max_history:
            self._outcomes = self._outcomes[-self._max_history :]

    def recent(self, limit: int = 100) -> list[MLOutcomeRecord]:
        return self._outcomes[-limit:]

    def get_outcomes(
        self,
        model_id: str | None = None,
        task: PredictionTask | None = None,
    ) -> list[MLOutcomeRecord]:
        results = self._outcomes
        if model_id is not None:
            results = [o for o in results if o.model_id == model_id]
        if task is not None:
            results = [o for o in results if o.task == task]
        return results

    def clear(self) -> None:
        self._outcomes.clear()


class MLEvidenceAggregator:
    def __init__(self) -> None:
        self._profiles: dict[str, EvidenceProfile] = {}

    def add_outcome(self, outcome: MLOutcomeRecord) -> None:
        key = f"{outcome.model_id}:{outcome.model_version}:{outcome.task.value}"
        if key not in self._profiles:
            self._profiles[key] = EvidenceProfile(
                model_id=outcome.model_id,
                model_version=outcome.model_version,
                task=outcome.task,
            )
        profile = self._profiles[key]
        profile.sample_count += 1
        profile.correct_count += int(outcome.correct)
        profile.total_latency_ms += outcome.latency_ms
        profile.total_calibration_error += outcome.calibration_error
        profile.fallback_count += int(outcome.fallback_used)
        profile.confidence_sum += outcome.confidence
        profile.last_updated = outcome.timestamp

    def get_profile(
        self, model_id: str, model_version: str, task: PredictionTask
    ) -> EvidenceProfile | None:
        key = f"{model_id}:{model_version}:{task.value}"
        return self._profiles.get(key)

    def all_profiles(self) -> dict[str, EvidenceProfile]:
        return dict(self._profiles)

    def decay_older_than(self, cutoff_seconds: float) -> None:
        now = time.time()
        to_remove = []
        for key, profile in self._profiles.items():
            try:
                last = float(profile.last_updated)
                if now - last > cutoff_seconds:
                    to_remove.append(key)
            except (ValueError, TypeError):
                to_remove.append(key)
        for key in to_remove:
            del self._profiles[key]


class AdaptiveLayer:
    def __init__(self, collector: MLOutcomeCollector | None = None, aggregator: MLEvidenceAggregator | None = None) -> None:
        self._collector = collector or MLOutcomeCollector()
        self._aggregator = aggregator or MLEvidenceAggregator()
        self._thresholds = AdaptiveThresholds()

    def record_outcome(self, outcome: MLOutcomeRecord) -> None:
        self._collector.record(outcome)
        self._aggregator.add_outcome(outcome)

    def adapt_thresholds(self) -> AdaptiveThresholds:
        profiles = self._aggregator.all_profiles()
        if not profiles:
            return self._thresholds

        accuracies = [p.accuracy for p in profiles.values() if p.sample_count >= self._thresholds.min_samples_for_adaptation]
        latencies = [p.avg_latency_ms for p in profiles.values() if p.sample_count >= self._thresholds.min_samples_for_adaptation]
        calibration_errors = [p.avg_calibration_error for p in profiles.values() if p.sample_count >= self._thresholds.min_samples_for_adaptation]
        fallback_rates = [p.fallback_rate for p in profiles.values() if p.sample_count >= self._thresholds.min_samples_for_adaptation]

        if accuracies:
            self._thresholds.confidence_threshold = max(0.5, min(0.9, sum(accuracies) / len(accuracies)))
        if latencies:
            self._thresholds.latency_threshold_ms = max(100.0, min(1000.0, sum(latencies) / len(latencies) * 1.5))
        if calibration_errors:
            self._thresholds.calibration_error_threshold = max(0.01, min(0.1, sum(calibration_errors) / len(calibration_errors)))
        if fallback_rates:
            self._thresholds.fallback_rate_threshold = max(0.05, min(0.5, sum(fallback_rates) / len(fallback_rates)))

        return self._thresholds

    def get_profile(self, model_id: str, model_version: str, task: PredictionTask) -> EvidenceProfile | None:
        return self._aggregator.get_profile(model_id, model_version, task)

    def should_promote_candidate(
        self,
        candidate_model_id: str,
        candidate_model_version: str,
        task: PredictionTask,
        active_model_id: str,
        active_model_version: str,
    ) -> tuple[bool, str]:
        candidate = self._aggregator.get_profile(candidate_model_id, candidate_model_version, task)
        active = self._aggregator.get_profile(active_model_id, active_model_version, task)

        if candidate is None or candidate.sample_count < self._thresholds.min_samples_for_adaptation:
            return False, "insufficient_candidate_evidence"

        if active is None or active.sample_count < self._thresholds.min_samples_for_adaptation:
            return False, "insufficient_active_evidence"

        if candidate.accuracy <= active.accuracy:
            return False, "candidate_not_more_accurate"

        if candidate.avg_latency_ms > self._thresholds.latency_threshold_ms:
            return False, "candidate_too_slow"

        if candidate.avg_calibration_error > self._thresholds.calibration_error_threshold:
            return False, "candidate_poorly_calibrated"

        if candidate.fallback_rate > active.fallback_rate:
            return False, "candidate_higher_fallback_rate"

        return True, "promotion_eligible"

    @property
    def thresholds(self) -> AdaptiveThresholds:
        return self._thresholds
