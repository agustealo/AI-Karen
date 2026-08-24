from __future__ import annotations

import math
from typing import Any, Callable, Protocol

from ai_karen_engine.core.intelligence.ml.contracts import (
    CalibratedProbability,
    CalibrationContext,
    PredictionTask,
)


class ProbabilityCalibrator(Protocol):
    def calibrate(
        self,
        *,
        task: PredictionTask,
        probability: float,
        context: CalibrationContext,
    ) -> CalibratedProbability:
        ...


class IdentityCalibrator:
    def calibrate(
        self,
        *,
        task: PredictionTask,
        probability: float,
        context: CalibrationContext,
    ) -> CalibratedProbability:
        return CalibratedProbability(
            raw_probability=probability,
            calibrated_probability=probability,
            calibration_version="calib-identity-v1",
            method="identity",
        )


class PlattCalibrator:
    def __init__(self, a: float = 1.0, b: float = 0.0, calibration_version: str = "calib-platt-v1") -> None:
        self._a = a
        self._b = b
        self._calibration_version = calibration_version

    def calibrate(
        self,
        *,
        task: PredictionTask,
        probability: float,
        context: CalibrationContext,
    ) -> CalibratedProbability:
        z = self._a * probability + self._b
        if z >= 0:
            calibrated = 1.0 / (1.0 + math.exp(-z))
        else:
            calibrated = math.exp(z) / (1.0 + math.exp(z))
        calibrated = max(0.0, min(1.0, calibrated))
        return CalibratedProbability(
            raw_probability=probability,
            calibrated_probability=calibrated,
            calibration_version=self._calibration_version,
            method="platt",
            metadata={"a": self._a, "b": self._b},
        )

    @classmethod
    def fit(
        cls,
        probabilities: list[float],
        labels: list[int],
        calibration_version: str = "calib-platt-v1",
    ) -> PlattCalibrator:
        a, b = cls._fit_params(probabilities, labels)
        return cls(a=a, b=b, calibration_version=calibration_version)

    @staticmethod
    def _fit_params(probabilities: list[float], labels: list[int]) -> tuple[float, float]:
        a, b = 1.0, 0.0
        n = len(probabilities)
        if n == 0:
            return a, b

        for epoch in range(2000):
            z = [a * p + b for p in probabilities]
            pred = [
                1.0 / (1.0 + math.exp(-zi)) if zi >= 0 else math.exp(zi) / (1.0 + math.exp(zi))
                for zi in z
            ]
            da = sum((pred[i] - labels[i]) * probabilities[i] for i in range(n)) / n
            db = sum(pred[i] - labels[i] for i in range(n)) / n
            lr = 0.1 / (1.0 + epoch * 0.001)
            a -= lr * da
            b -= lr * db
        return a, b


class IsotonicCalibrator:
    def __init__(
        self,
        calibrator_fn: Callable[[float], float],
        calibration_version: str = "calib-isotonic-v1",
    ) -> None:
        self._calibrator_fn = calibrator_fn
        self._calibration_version = calibration_version

    def calibrate(
        self,
        *,
        task: PredictionTask,
        probability: float,
        context: CalibrationContext,
    ) -> CalibratedProbability:
        calibrated = self._calibrator_fn(probability)
        calibrated = max(0.0, min(1.0, calibrated))
        return CalibratedProbability(
            raw_probability=probability,
            calibrated_probability=calibrated,
            calibration_version=self._calibration_version,
            method="isotonic",
        )

    @staticmethod
    def fit(
        probabilities: list[float],
        labels: list[int],
        min_samples: int = 20,
        calibration_version: str = "calib-isotonic-v1",
    ) -> IsotonicCalibrator | None:
        if len(probabilities) < min_samples:
            return None
        calibrator_fn = IsotonicCalibrator._pava(probabilities, labels)
        return IsotonicCalibrator(
            calibrator_fn=calibrator_fn, calibration_version=calibration_version
        )

    @staticmethod
    def _pava(probabilities: list[float], labels: list[int]) -> Callable[[float], float]:
        pairs = sorted(zip(probabilities, [float(l) for l in labels]))
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        n = len(xs)

        block_ys = ys[:]
        block_sizes = [1] * n

        changed = True
        while changed:
            changed = False
            new_block_ys = []
            new_block_sizes = []
            i = 0
            while i < len(block_ys):
                j = i + 1
                curr_y = block_ys[i]
                curr_size = block_sizes[i]
                while j < len(block_ys) and block_ys[j] < curr_y:
                    curr_y = (curr_y * curr_size + block_ys[j] * block_sizes[j]) / (
                        curr_size + block_sizes[j]
                    )
                    curr_size += block_sizes[j]
                    j += 1
                    changed = True
                new_block_ys.append(curr_y)
                new_block_sizes.append(curr_size)
                i = j
            block_ys = new_block_ys
            block_sizes = new_block_sizes

        boundaries = []
        idx = 0
        for size in block_sizes:
            boundaries.append((xs[idx], xs[min(idx + size - 1, n - 1)]))
            idx += size

        def interpolate(p: float) -> float:
            for (lo, hi), y in zip(boundaries, block_ys):
                if lo <= p <= hi:
                    return y
            return block_ys[0] if p < boundaries[0][0] else block_ys[-1]

        return interpolate


class CalibrationService:
    def __init__(self, default_version: str = "calib-v1") -> None:
        self._calibrators: dict[str, ProbabilityCalibrator] = {}
        self._default_version = default_version

    def fit(self, benchmark_result: Any) -> None:
        from collections import defaultdict

        task_outcomes: dict[str, list[Any]] = defaultdict(list)
        for outcome in benchmark_result.outcomes:
            task_outcomes[outcome.task.value].append(outcome)

        for task_value, outcomes in task_outcomes.items():
            probabilities: list[float] = []
            labels: list[int] = []
            for o in outcomes:
                if o.prediction is not None and not o.error:
                    prob = o.raw_probability
                    if prob <= 0.0 and hasattr(o.prediction, "confidence"):
                        prob = o.prediction.confidence
                    if prob > 0.0:
                        probabilities.append(prob)
                        labels.append(1 if o.correct else 0)

            if not probabilities:
                self._calibrators[task_value] = IdentityCalibrator()
                continue

            unique_labels = set(labels)
            if len(unique_labels) < 2:
                self._calibrators[task_value] = IdentityCalibrator()
                continue

            calibrator: ProbabilityCalibrator
            try:
                iso = IsotonicCalibrator.fit(
                    probabilities,
                    labels,
                    calibration_version=f"{self._default_version}-isotonic",
                )
                if iso is not None:
                    calibrator = iso
                else:
                    calibrator = PlattCalibrator.fit(
                        probabilities,
                        labels,
                        calibration_version=f"{self._default_version}-platt",
                    )
            except Exception:
                calibrator = IdentityCalibrator()

            self._calibrators[task_value] = calibrator

    def get_calibrator(self, task: PredictionTask) -> ProbabilityCalibrator:
        return self._calibrators.get(task.value, IdentityCalibrator())

    def calibrate_prediction(
        self, prediction: Any, context: CalibrationContext
    ) -> CalibratedProbability:
        calibrator = self.get_calibrator(context.task)
        probability = prediction.probability if prediction.probability > 0 else prediction.confidence
        return calibrator.calibrate(task=context.task, probability=probability, context=context)

    @property
    def calibration_version(self) -> str:
        return self._default_version

    @property
    def fitted_tasks(self) -> list[str]:
        return list(self._calibrators.keys())
