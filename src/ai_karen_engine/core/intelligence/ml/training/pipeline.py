from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest,
    ModelStatus,
    PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkConfig
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import (
    CanonicalEvaluationCorpus,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingExecutor,
    TrainingJob,
    TrainingJobStatus,
    TrainingPipelineResult,
)
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import (
    SklearnTrainingExecutor,
)

logger = logging.getLogger(__name__)


class TrainingPipeline:
    def __init__(
        self,
        registry: MLModelRegistry | None = None,
        executor: TrainingExecutor | None = None,
        evaluator: BenchmarkRunner | None = None,
    ) -> None:
        self._registry = registry or MLModelRegistry()
        self._executor = executor or SklearnTrainingExecutor()
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
            job.started_at = datetime.now(timezone.utc).isoformat()
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
            job.completed_at = datetime.now(timezone.utc).isoformat()
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
        try:
            from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import (
                SklearnTrainingExecutor,
            )
            executor = SklearnTrainingExecutor()
            return await self._evaluator.run(executor, config)
        except Exception as exc:
            logger.debug("Evaluation artifact failed: %s", exc)
            return None

    def _register_artifact(self, artifact: TrainingArtifact, job: TrainingJob) -> bool:
        try:
            PredictionTask(artifact.task)
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
            created_at=datetime.now(timezone.utc).isoformat(),
            status=ModelStatus.CANDIDATE.value,
        )
        self._registry.register(manifest)
        return True
