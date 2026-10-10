from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timezone
from collections.abc import Callable, Awaitable

from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest,
    ModelStatus,
    PredictionTask,
)
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
    _hash_directory,
)
from ai_karen_engine.config.config_manager import get_ml_registry_dir

logger = logging.getLogger(__name__)


class TrainingPipeline:
    def __init__(
        self,
        registry: MLModelRegistry | None = None,
        executor: TrainingExecutor | None = None,
    ) -> None:
        self._registry = registry or MLModelRegistry()
        self._executor = executor

    def submit(self, job: TrainingJob) -> TrainingPipelineResult:
        job.status = TrainingJobStatus.QUEUED.value
        return TrainingPipelineResult(job=job)

    async def run(
        self,
        result: TrainingPipelineResult,
        on_state: Callable[[str, TrainingJob], Awaitable[None]] | None = None,
        authorize_publication: Callable[[], bool] | None = None,
    ) -> TrainingPipelineResult:
        job = result.job
        try:
            job.status = TrainingJobStatus.VALIDATING.value
            self._validate_job(job)

            job.status = TrainingJobStatus.RUNNING.value
            if on_state is not None:
                await on_state(job.status, job)
            job.started_at = datetime.now(timezone.utc).isoformat()
            executor = self._executor
            if executor is None:
                if job.base_model == "sklearn":
                    executor = SklearnTrainingExecutor()
                elif job.base_model == "spacy":
                    from ai_karen_engine.core.intelligence.ml.training.spacy_executor import SpacyTrainingExecutor
                    executor = SpacyTrainingExecutor()
                else:
                    raise ValueError("No governed training executor for requested model")
            artifact = executor.execute(job)
            job.artifact_path = artifact.artifact_path
            job.artifact_hash = artifact.artifact_hash
            job.metrics = artifact.metrics
            job.resource_usage = artifact.resource_usage

            # The executor reports genuine held-out classification metrics.
            # Canonical benchmark execution is a separate predictor-owned gate.
            job.status = TrainingJobStatus.EVALUATING.value
            if on_state is not None:
                await on_state(job.status, job)
            result.evaluation_result = None

            if (int(artifact.metrics.get('test_samples', 0)) < 1 or
                'macro_f1' not in artifact.metrics or
                not artifact.artifact_hash):
                raise ValueError('Missing held-out evaluation evidence or artifact integrity hash')
            artifact_root = Path(artifact.artifact_path).resolve()
            trusted_root = Path(get_ml_registry_dir()).resolve()
            if not artifact_root.is_relative_to(trusted_root) or not artifact_root.is_dir():
                raise ValueError('Training artifact is outside the canonical model registry')
            if _hash_directory(artifact_root) != artifact.artifact_hash:
                raise ValueError('Training artifact failed integrity verification')
            if authorize_publication is not None and not authorize_publication():
                raise RuntimeError('Training worker lease invalid before artifact publication')
            registered = self._register_artifact(artifact, job)
            if not registered:
                raise ValueError('Training candidate registration rejected')
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
            feature_version=str(artifact.metrics.get("feature_version") or "v1"),
            training_dataset_version=artifact.dataset_version,
            calibration_version="",
            metrics={**artifact.metrics, 'canonical_benchmark_status': 'not_run'},
            created_at=datetime.now(timezone.utc).isoformat(),
            status=ModelStatus.CANDIDATE.value,
        )
        self._registry.register(manifest)
        return True
