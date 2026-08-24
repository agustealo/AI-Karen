from __future__ import annotations

import math

import pytest

from ai_karen_engine.core.intelligence.ml.calibration import (
    CalibrationService,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
)
from ai_karen_engine.core.intelligence.ml.contracts import (
    CalibratedProbability,
    CalibrationContext,
    Prediction,
    PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkResult,
    PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import CanonicalEvaluationCorpus
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkConfig
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures


class FakePredictor:
    def __init__(self, label: str, probability: float, confidence: float) -> None:
        self._label = label
        self._probability = probability
        self._confidence = confidence

    async def predict(self, features: IntelligenceFeatures):
        return Prediction(
            task=PredictionTask.INTENT,
            label=self._label,
            probability=self._probability,
            confidence=self._confidence,
        )


@pytest.mark.asyncio
async def test_identity_calibrator():
    calibrator = IdentityCalibrator()
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    result = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.8, context=ctx)
    assert result.raw_probability == 0.8
    assert result.calibrated_probability == 0.8
    assert result.method == "identity"


@pytest.mark.asyncio
async def test_platt_calibrator_identity_params():
    calibrator = PlattCalibrator(a=1.0, b=0.0)
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    result = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.5, context=ctx)
    assert result.calibrated_probability == pytest.approx(1.0 / (1.0 + math.exp(-0.5)), abs=1e-6)
    assert result.raw_probability == 0.5


@pytest.mark.asyncio
async def test_platt_calibrator_fit_and_calibrate():
    probabilities = [0.1, 0.2, 0.3, 0.8, 0.9]
    labels = [0, 0, 0, 1, 1]
    calibrator = PlattCalibrator.fit(probabilities, labels)
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    low = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.1, context=ctx)
    high = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.9, context=ctx)
    assert low.calibrated_probability < high.calibrated_probability
    assert low.method == "platt"
    assert high.calibration_version == "calib-platt-v1"


@pytest.mark.asyncio
async def test_platt_calibrator_bounds():
    calibrator = PlattCalibrator(a=5.0, b=-2.0)
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    result = calibrator.calibrate(task=PredictionTask.INTENT, probability=1.0, context=ctx)
    assert 0.0 <= result.calibrated_probability <= 1.0


@pytest.mark.asyncio
async def test_isotonic_calibrator_fit():
    probabilities = [0.1, 0.2, 0.3, 0.8, 0.9, 0.85, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35, 0.25, 0.15, 0.05, 0.95, 0.92]
    labels = [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1]
    calibrator = IsotonicCalibrator.fit(probabilities, labels, min_samples=5)
    assert calibrator is not None
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    low = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.1, context=ctx)
    high = calibrator.calibrate(task=PredictionTask.INTENT, probability=0.9, context=ctx)
    assert low.calibrated_probability <= high.calibrated_probability
    assert low.method == "isotonic"


@pytest.mark.asyncio
async def test_isotonic_calibrator_insufficient_samples():
    probabilities = [0.1, 0.9]
    labels = [0, 1]
    calibrator = IsotonicCalibrator.fit(probabilities, labels, min_samples=5)
    assert calibrator is None


@pytest.mark.asyncio
async def test_calibration_service_fit_and_query():
    runner = BenchmarkRunner(CanonicalEvaluationCorpus())
    predictor = FakePredictor(label="information_seeking", probability=0.9, confidence=0.9)
    config = BenchmarkConfig(
        model_id="calib-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001", "intent-002", "intent-003", "intent-004", "intent-005"],
    )
    result = await runner.run(predictor, config)
    assert result.sample_count > 0

    service = CalibrationService()
    service.fit(result)

    assert len(service.fitted_tasks) > 0
    calibrator = service.get_calibrator(PredictionTask.INTENT)
    assert isinstance(calibrator, (IdentityCalibrator, PlattCalibrator, IsotonicCalibrator))


@pytest.mark.asyncio
async def test_calibration_service_missing_task():
    service = CalibrationService()
    calibrator = service.get_calibrator(PredictionTask.DOMAIN)
    assert isinstance(calibrator, IdentityCalibrator)


@pytest.mark.asyncio
async def test_calibration_service_calibrate_prediction():
    runner = BenchmarkRunner(CanonicalEvaluationCorpus())
    predictor = FakePredictor(label="information_seeking", probability=0.9, confidence=0.9)
    config = BenchmarkConfig(
        model_id="calib-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001", "intent-002", "intent-003"],
    )
    result = await runner.run(predictor, config)
    service = CalibrationService()
    service.fit(result)

    prediction = Prediction(
        task=PredictionTask.INTENT,
        label="information_seeking",
        probability=0.9,
        confidence=0.9,
    )
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="calib-model",
        model_version="v1",
        feature_version="v1",
        predicted_label="information_seeking",
    )
    calibrated = service.calibrate_prediction(prediction, ctx)
    assert isinstance(calibrated, CalibratedProbability)
    assert calibrated.raw_probability == 0.9
    assert 0.0 <= calibrated.calibrated_probability <= 1.0
    assert calibrated.calibration_version


@pytest.mark.asyncio
async def test_calibration_service_single_class_fallback():
    runner = BenchmarkRunner(CanonicalEvaluationCorpus())
    predictor = FakePredictor(label="information_seeking", probability=0.9, confidence=0.9)
    config = BenchmarkConfig(
        model_id="calib-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001", "intent-002", "intent-003", "intent-004", "intent-005"],
    )
    result = await runner.run(predictor, config)
    # Filter to only correct outcomes to create single-class labels
    single_class_outcomes = [o for o in result.outcomes if o.correct]
    single_class_result = BenchmarkResult(
        model_id=result.model_id,
        model_version=result.model_version,
        task=result.task,
        dataset_version=result.dataset_version,
        sample_count=len(single_class_outcomes),
        metrics=result.metrics,
        latency_p50_ms=result.latency_p50_ms,
        latency_p95_ms=result.latency_p95_ms,
        error_count=result.error_count,
        fallback_count=result.fallback_count,
        abstention_count=result.abstention_count,
        outcomes=single_class_outcomes,
    )
    service = CalibrationService()
    service.fit(single_class_result)
    calibrator = service.get_calibrator(PredictionTask.INTENT)
    assert isinstance(calibrator, IdentityCalibrator)


@pytest.mark.asyncio
async def test_isotonic_preserves_monotonicity():
    probabilities = [0.1, 0.2, 0.3, 0.8, 0.9]
    labels = [0, 0, 0, 1, 1]
    calibrator = IsotonicCalibrator.fit(probabilities, labels, min_samples=3)
    assert calibrator is not None
    ctx = CalibrationContext(
        task=PredictionTask.INTENT,
        model_id="m1",
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
    )
    vals = [
        calibrator.calibrate(task=PredictionTask.INTENT, probability=p, context=ctx).calibrated_probability
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]
    ]
    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1]
