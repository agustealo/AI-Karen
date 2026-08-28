from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "AdaptiveLayer": ("online_learning", "AdaptiveLayer"),
    "AdaptiveThresholds": ("online_learning", "AdaptiveThresholds"),
    "AgentPerformanceProfile": ("performance_profiles", "AgentPerformanceProfile"),
    "AuditEvent": ("audit", "AuditEvent"),
    "AuditLogger": ("audit", "AuditLogger"),
    "BenchmarkConfig": ("evaluation", "BenchmarkConfig"),
    "BenchmarkResult": ("evaluation", "BenchmarkResult"),
    "BenchmarkRunner": ("evaluation", "BenchmarkRunner"),
    "CalibrationBin": ("evaluation", "CalibrationBin"),
    "CalibratedProbability": ("contracts", "CalibratedProbability"),
    "CalibrationContext": ("contracts", "CalibrationContext"),
    "CalibrationService": ("calibration", "CalibrationService"),
    "CanonicalEvaluationCorpus": ("evaluation", "CanonicalEvaluationCorpus"),
    "CapabilityPerformanceProfile": ("performance_profiles", "CapabilityPerformanceProfile"),
    "ContinualRetrainingPipeline": ("continual_learning", "ContinualRetrainingPipeline"),
    "EvaluationCase": ("evaluation", "EvaluationCase"),
    "EvidenceAggregator": ("performance_profiles", "EvidenceAggregator"),
    "EvidenceProfile": ("online_learning", "EvidenceProfile"),
    "EXECUTION_TOPOLOGY_LABELS": ("contracts", "EXECUTION_TOPOLOGY_LABELS"),
    "IdentityCalibrator": ("calibration", "IdentityCalibrator"),
    "IsotonicCalibrator": ("calibration", "IsotonicCalibrator"),
    "MLEvidenceAggregator": ("online_learning", "MLEvidenceAggregator"),
    "MLModelManifest": ("contracts", "MLModelManifest"),
    "MLModelRegistry": ("registry", "MLModelRegistry"),
    "MLOutcomeCollector": ("online_learning", "MLOutcomeCollector"),
    "MLOutcomeRecord": ("online_learning", "MLOutcomeRecord"),
    "MLRuntime": ("ml_runtime", "MLRuntime"),
    "MetricResult": ("evaluation", "MetricResult"),
    "ModelStatus": ("contracts", "ModelStatus"),
    "OutcomeObservation": ("performance_profiles", "OutcomeObservation"),
    "PerformanceProfileAggregator": ("performance_profiles", "PerformanceProfileAggregator"),
    "PlattCalibrator": ("calibration", "PlattCalibrator"),
    "Prediction": ("contracts", "Prediction"),
    "PredictionOutcome": ("evaluation", "PredictionOutcome"),
    "PredictionTask": ("contracts", "PredictionTask"),
    "ProbabilityCalibrator": ("calibration", "ProbabilityCalibrator"),
    "PromotionDecision": ("promotion", "PromotionDecision"),
    "RetrainingTrigger": ("continual_learning", "RetrainingTrigger"),
    "SemanticEncoding": ("contracts", "SemanticEncoding"),
    "SemanticEncoder": ("contracts", "SemanticEncoder"),
    "ShadowComparisonResult": ("contracts", "ShadowComparisonResult"),
    "ShadowEvaluation": ("contracts", "ShadowEvaluation"),
    "ShadowEvaluator": ("shadow", "ShadowEvaluator"),
    "TOPOLOGY_FEATURE_VERSION": ("predictors.topology_features", "FEATURE_VERSION"),
    "TopologyPredictionLabels": ("contracts", "TopologyPredictionLabels"),
    "TrainingArtifact": ("training", "TrainingArtifact"),
    "TrainingExecutor": ("training", "TrainingExecutor"),
    "TrainingJob": ("training", "TrainingJob"),
    "TrainingJobStatus": ("training", "TrainingJobStatus"),
    "TrainingPipeline": ("training", "TrainingPipeline"),
    "TrainingPipelineResult": ("training", "TrainingPipelineResult"),
    "ExecutionTopologyPredictor": ("predictors.topology", "ExecutionTopologyPredictor"),
    "SklearnTrainingExecutor": ("training", "SklearnTrainingExecutor"),
    "compute_brier_score": ("evaluation", "compute_brier_score"),
    "compute_capability_metrics": ("evaluation", "compute_capability_metrics"),
    "compute_classification_metrics": ("evaluation", "compute_classification_metrics"),
    "compute_ece": ("evaluation", "compute_ece"),
    "compute_latency_metrics": ("evaluation", "compute_latency_metrics"),
    "compute_reliability_curve": ("evaluation", "compute_reliability_curve"),
    "evaluate_promotion": ("promotion", "evaluate_promotion"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = export
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
