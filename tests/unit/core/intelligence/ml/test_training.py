from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingJob,
    TrainingJobStatus,
    TrainingPipelineResult,
)
from ai_karen_engine.core.intelligence.ml.training.pipeline import (
    MockTrainingExecutor,
    TrainingPipeline,
)


def test_pipeline_submit_sets_queued(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry)
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    assert result.job.status == TrainingJobStatus.QUEUED.value


@pytest.mark.asyncio
async def test_pipeline_run_succeeds(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry)
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    result = await pipeline.run(result)
    assert result.job.status == TrainingJobStatus.SUCCEEDED.value
    assert result.artifact is not None
    assert result.registered is True
    assert result.job.artifact_path != ""
    assert result.job.artifact_hash != ""


@pytest.mark.asyncio
async def test_pipeline_registers_candidate(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry)
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    result = await pipeline.run(result)
    manifest = registry.get(result.artifact.model_id)
    assert manifest is not None
    assert manifest.status == "CANDIDATE"
    assert manifest.purpose == "intent"


@pytest.mark.asyncio
async def test_pipeline_run_failure(tmp_path):
    class FailExecutor:
        def execute(self, job):
            raise RuntimeError("training boom")

    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry, executor=FailExecutor())
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    result = await pipeline.run(result)
    assert result.job.status == TrainingJobStatus.FAILED.value
    assert result.error is not None


@pytest.mark.asyncio
async def test_pipeline_validates_missing_fields(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry)
    job = TrainingJob(
        job_id="job-1", task="", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    result = await pipeline.run(result)
    assert result.job.status == TrainingJobStatus.FAILED.value
    assert "task is required" in result.job.error_message


@pytest.mark.asyncio
async def test_pipeline_validates_unknown_task(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = TrainingPipeline(registry=registry)
    job = TrainingJob(
        job_id="job-1", task="unknown_task", base_model="base", dataset_version="ds-v1"
    )
    result = pipeline.submit(job)
    result = await pipeline.run(result)
    assert result.job.status == TrainingJobStatus.FAILED.value
    assert "Unknown task" in result.job.error_message


@pytest.mark.asyncio
async def test_mock_executor_creates_artifact(tmp_path):
    executor = MockTrainingExecutor()
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    artifact = executor.execute(job)
    assert artifact.artifact_path != ""
    assert artifact.artifact_hash != ""
    assert Path(artifact.artifact_path).exists()
