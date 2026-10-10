"""Training contracts are importable without optional ML backends.

Executors and pipelines are loaded on demand. Keep administrative ingress
independent of sklearn, spaCy, torch, and PEFT installations.
"""
from __future__ import annotations

from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingExecutor,
    TrainingJob,
    TrainingJobStatus,
    TrainingPipelineResult,
)

__all__ = [
    "SklearnTrainingExecutor",
    "TrainingArtifact",
    "TrainingExecutor",
    "TrainingJob",
    "TrainingJobStatus",
    "TrainingPipeline",
    "TrainingPipelineResult",
]


def __getattr__(name: str):
    if name == "TrainingPipeline":
        from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline
        return TrainingPipeline
    if name == "SklearnTrainingExecutor":
        from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import SklearnTrainingExecutor
        return SklearnTrainingExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
