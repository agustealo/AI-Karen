from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    CalibrationBin,
    MetricResult,
    PredictionOutcome,
)


def _probability(outcome: PredictionOutcome) -> float:
    if outcome.prediction is None:
        return 0.0
    prob = outcome.prediction.probability
    return prob if prob > 0 else outcome.prediction.confidence


def _predicted_label(outcome: PredictionOutcome) -> str:
    if outcome.prediction is None:
        return ""
    return outcome.prediction.label


def _predicted_capabilities(outcome: PredictionOutcome, threshold: float = 0.3) -> set[str]:
    if outcome.prediction is None or not isinstance(outcome.prediction.value, dict):
        return set()
    return {cap for cap, score in outcome.prediction.value.items() if score >= threshold}


def compute_classification_metrics(
    outcomes: list[PredictionOutcome],
) -> dict[str, MetricResult]:
    valid = [o for o in outcomes if o.prediction is not None and not o.error]
    total = len(valid)
    if total == 0:
        return {
            "accuracy": MetricResult("accuracy", 0.0, 0),
            "macro_precision": MetricResult("macro_precision", 0.0, 0),
            "macro_recall": MetricResult("macro_recall", 0.0, 0),
            "macro_f1": MetricResult("macro_f1", 0.0, 0),
        }

    correct_count = sum(1 for o in valid if o.correct)
    accuracy = correct_count / total

    classes = sorted(
        set(o.expected_label for o in valid) | set(_predicted_label(o) for o in valid)
    )
    per_class: dict[str, dict[str, float]] = {}
    for cls in classes:
        tp = sum(1 for o in valid if _predicted_label(o) == cls and o.correct)
        fp = sum(1 for o in valid if _predicted_label(o) == cls and not o.correct)
        fn = sum(1 for o in valid if o.expected_label == cls and _predicted_label(o) != cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        per_class[cls] = {"precision": precision, "recall": recall, "f1": f1}

    macro_precision = sum(v["precision"] for v in per_class.values()) / len(per_class)
    macro_recall = sum(v["recall"] for v in per_class.values()) / len(per_class)
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class)

    return {
        "accuracy": MetricResult("accuracy", accuracy, total),
        "macro_precision": MetricResult("macro_precision", macro_precision, total, {"per_class": per_class}),
        "macro_recall": MetricResult("macro_recall", macro_recall, total, {"per_class": per_class}),
        "macro_f1": MetricResult("macro_f1", macro_f1, total, {"per_class": per_class}),
    }


def compute_capability_metrics(
    outcomes: list[PredictionOutcome],
    threshold: float = 0.3,
) -> dict[str, MetricResult]:
    valid = [o for o in outcomes if o.prediction is not None and not o.error]
    total = len(valid)
    if total == 0:
        return {
            "micro_f1": MetricResult("micro_f1", 0.0, 0),
            "macro_f1": MetricResult("macro_f1", 0.0, 0),
        }

    all_caps = set()
    for o in valid:
        if isinstance(o.expected_value, list):
            all_caps.update(o.expected_value)
        pred_caps = _predicted_capabilities(o, threshold)
        all_caps.update(pred_caps)

    global_tp = 0
    global_fp = 0
    global_fn = 0
    per_cap: dict[str, dict[str, float]] = {}

    for cap in sorted(all_caps):
        tp = fp = fn = 0
        for o in valid:
            expected = set(o.expected_value or [])
            predicted = _predicted_capabilities(o, threshold)
            if cap in expected and cap in predicted:
                tp += 1
            elif cap in predicted and cap not in expected:
                fp += 1
            elif cap in expected and cap not in predicted:
                fn += 1
        global_tp += tp
        global_fp += fp
        global_fn += fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        per_cap[cap] = {"precision": precision, "recall": recall, "f1": f1, "fp": fp, "tp": tp, "fn": fn}

    micro_precision = global_tp / (global_tp + global_fp) if (global_tp + global_fp) > 0 else 0.0
    micro_recall = global_tp / (global_tp + global_fn) if (global_tp + global_fn) > 0 else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall) > 0
        else 0.0
    )
    macro_f1 = sum(v["f1"] for v in per_cap.values()) / len(per_cap) if per_cap else 0.0

    return {
        "micro_f1": MetricResult("micro_f1", micro_f1, total),
        "macro_f1": MetricResult("macro_f1", macro_f1, total, {"per_capability": per_cap}),
    }


def compute_brier_score(outcomes: list[PredictionOutcome]) -> MetricResult:
    valid = [o for o in outcomes if o.prediction is not None and not o.error]
    total = len(valid)
    if total == 0:
        return MetricResult("brier_score", 0.0, 0)

    brier = 0.0
    for o in valid:
        prob = _probability(o)
        correct = 1.0 if o.correct else 0.0
        brier += (prob - correct) ** 2
    brier /= total
    return MetricResult("brier_score", brier, total)


def compute_ece(
    outcomes: list[PredictionOutcome],
    n_bins: int = 10,
) -> tuple[MetricResult, list[CalibrationBin]]:
    valid = [o for o in outcomes if o.prediction is not None and not o.error]
    total = len(valid)
    if total == 0:
        return MetricResult("ece", 0.0, 0), []

    bins: list[list[PredictionOutcome]] = [[] for _ in range(n_bins)]
    for o in valid:
        prob = _probability(o)
        bin_idx = min(int(prob * n_bins), n_bins - 1)
        bins[bin_idx].append(o)

    ece = 0.0
    calibration_bins: list[CalibrationBin] = []
    for i, bin_cases in enumerate(bins):
        if not bin_cases:
            continue
        bin_start = i / n_bins
        bin_end = (i + 1) / n_bins
        avg_confidence = sum(_probability(o) for o in bin_cases) / len(bin_cases)
        avg_accuracy = sum(1.0 if o.correct else 0.0 for o in bin_cases) / len(bin_cases)
        gap = abs(avg_confidence - avg_accuracy)
        ece += gap * len(bin_cases)
        calibration_bins.append(
            CalibrationBin(
                bin_start=bin_start,
                bin_end=bin_end,
                count=len(bin_cases),
                avg_confidence=avg_confidence,
                avg_accuracy=avg_accuracy,
                gap=gap,
            )
        )

    ece /= total
    return MetricResult("ece", ece, total), calibration_bins


def compute_reliability_curve(
    outcomes: list[PredictionOutcome],
    n_bins: int = 10,
) -> list[CalibrationBin]:
    _, bins = compute_ece(outcomes, n_bins=n_bins)
    return bins


def compute_latency_metrics(
    outcomes: list[PredictionOutcome],
) -> dict[str, MetricResult]:
    latencies = sorted(o.latency_ms for o in outcomes if o.latency_ms > 0)
    total = len(latencies)
    if total == 0:
        return {
            "p50_latency_ms": MetricResult("p50_latency_ms", 0.0, 0),
            "p95_latency_ms": MetricResult("p95_latency_ms", 0.0, 0),
        }

    def percentile(sorted_data: list[float], p: float) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    p50 = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)
    return {
        "p50_latency_ms": MetricResult("p50_latency_ms", p50, total),
        "p95_latency_ms": MetricResult("p95_latency_ms", p95, total),
    }
