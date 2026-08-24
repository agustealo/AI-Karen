from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkConfig
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import CanonicalEvaluationCorpus
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingJob,
    TrainingJobStatus,
    TrainingPipelineResult,
)

logger = logging.getLogger(__name__)


class TrainingExecutor(Protocol):
    def execute(self, job: TrainingJob) -> TrainingArtifact:
        ...


class MockTrainingExecutor:
    def execute(self, job: TrainingJob) -> TrainingArtifact:
        artifact_path = f"models/training/{job.job_id}"
        Path(artifact_path).mkdir(parents=True, exist_ok=True)
        (Path(artifact_path) / "model.bin").write_bytes(b"mock-model-weights")
        h = hashlib.sha256(b"mock-model-weights").hexdigest()
        return TrainingArtifact(
            artifact_path=artifact_path,
            artifact_hash=h,
            model_id=f"trained-{job.task}",
            model_version=f"train-{job.job_id[:8]}",
            task=job.task,
            dataset_version=job.dataset_version,
            training_config_version=job.training_config_version,
            metrics={"mock_loss": 0.1, "mock_accuracy": 0.9},
            resource_usage={"cpu_seconds": 10.0, "gpu_seconds": 5.0},
        )


class TrainingPipeline:
    def __init__(
        self,
        registry: MLModelRegistry | None = None,
        executor: TrainingExecutor | None = None,
        evaluator: BenchmarkRunner | None = None,
    ) -> None:
        self._registry = registry or MLModelRegistry()
        self._executor = executor or MockTrainingExecutor()
        self._evaluator = evaluator or BenchmarkRunner(CanonicalEvaluationCorpus())

    def submit(self, job: TrainingJob) -> TrainingPipelineResult:
        job.status = TrainingJobStatus.QUEUED.value
        return TrainingPipelineResult(job=job)

    async def run(self, result: TrainingPipelineResult) -> TrainingPipelineResult:
        job = result.job
        try:
            job.status = TrainingJobStatus.VALIDATING.value
            self._validate_job(job)

            job.status = TrainingJobStatus.RUNNING.value
            job.started_at = datetime.now().isoformat()
            artifact = self._executor.execute(job)
            job.artifact_path = artifact.artifact_path
            job.artifact_hash = artifact.artifact_hash
            job.metrics = artifact.metrics
            job.resource_usage = artifact.resource_usage

            job.status = TrainingJobStatus.EVALUATING.value
            eval_result = await self._evaluate_artifact(artifact)
            result.evaluation_result = eval_result

            registered = self._register_artifact(artifact, job)
            result.artifact = artifact
            result.registered = registered
            job.status = TrainingJobStatus.SUCCEEDED.value
            job.completed_at = datetime.now().isoformat()
        except Exception as exc:
            job.status = TrainingJobStatus.FAILED.value
            job.error_message = str(exc)
            result.error = str(exc)
            logger.error("Training pipeline failed for %s: %s", job.job_id, exc)
        return result

    def _validate_job(self, job: TrainingJob) -> None:
        if not job.base_model:
            raise ValueError("base_model is required")
        if not job.dataset_version:
            raise ValueError("dataset_version is required")
        if not job.task:
            raise ValueError("task is required")
        try:
            PredictionTask(job.task)
        except ValueError:
            raise ValueError(f"Unknown task: {job.task}")

    async def _evaluate_artifact(self, artifact: TrainingArtifact) -> Any:
        try:
            task = PredictionTask(artifact.task)
        except ValueError:
            return None

        config = BenchmarkConfig(
            model_id=artifact.model_id,
            model_version=artifact.model_version,
            task=task,
            dataset_version=artifact.dataset_version,
        )
        return await self._evaluator.run(MockTrainedPredictor(artifact), config)

    def _register_artifact(self, artifact: TrainingArtifact, job: TrainingJob) -> bool:
        try:
            task = PredictionTask(artifact.task)
        except ValueError:
            return False

        manifest = MLModelManifest(
            model_id=artifact.model_id,
            purpose=artifact.task,
            architecture="trained",
            artifact_path=artifact.artifact_path,
            artifact_hash=artifact.artifact_hash,
            model_version=artifact.model_version,
            feature_version="v1",
            training_dataset_version=artifact.dataset_version,
            calibration_version="",
            metrics=artifact.metrics,
            created_at=datetime.now().isoformat(),
            status=ModelStatus.CANDIDATE.value,
        )
        self._registry.register(manifest)
        return True


class MockTrainedPredictor:
    def __init__(self, artifact: TrainingArtifact) -> None:
        self._artifact = artifact

    async def predict(self, features: Any) -> Any:
        from ai_karen_engine.core.intelligence.ml.contracts import Prediction
        return Prediction(
            task=PredictionTask(self._artifact.task),
            label="mock",
            confidence=0.8,
            fallback_used=False,
            inference_method="trained_model",
        )
