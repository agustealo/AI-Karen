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
from ai_karen_engine.core.intelligence.ml.training.datasets import (
    FixtureTrainingDatasetProvider,
    TopologyTrainingExample,
)
from ai_karen_engine.core.intelligence.ml.training.pipeline import (
    TrainingPipeline,
)
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import (
    SklearnTrainingExecutor,
)


def _make_examples() -> list[TopologyTrainingExample]:
    return [
        TopologyTrainingExample(
            example_id="ex-1",
            feature_version="topology_features_v1",
            features={
                "token_count": 3,
                "sentence_count": 1,
                "entity_count": 0,
                "intent_confidence": 0.9,
                "complexity_score": 0.0,
                "ambiguity_score": 0.0,
                "memory_relevance_score": 0.0,
                "capability_count": 0,
                "tool_requirement_count": 0,
                "multiple_actions": False,
                "dependency_chain": False,
                "external_lookup": False,
                "code_execution": False,
                "filesystem_operation": False,
                "parallelizable": False,
                "requires_followup": False,
                "risk_score": 0.0,
                "web_search": False,
                "code_execution_hint": False,
                "filesystem_read": False,
                "filesystem_write": False,
                "tool_use": False,
                "deep_reasoning": False,
                "structured_output": False,
            },
            target="direct",
        ),
        TopologyTrainingExample(
            example_id="ex-2",
            feature_version="topology_features_v1",
            features={
                "token_count": 12,
                "sentence_count": 2,
                "entity_count": 2,
                "intent_confidence": 0.6,
                "complexity_score": 0.5,
                "ambiguity_score": 0.3,
                "memory_relevance_score": 0.1,
                "capability_count": 1,
                "tool_requirement_count": 1,
                "multiple_actions": True,
                "dependency_chain": True,
                "external_lookup": False,
                "code_execution": False,
                "filesystem_operation": False,
                "parallelizable": False,
                "requires_followup": True,
                "risk_score": 0.2,
                "web_search": False,
                "code_execution_hint": False,
                "filesystem_read": False,
                "filesystem_write": False,
                "tool_use": False,
                "deep_reasoning": True,
                "structured_output": False,
            },
            target="reasoning",
        ),
        TopologyTrainingExample(
            example_id="ex-3",
            feature_version="topology_features_v1",
            features={
                "token_count": 20,
                "sentence_count": 3,
                "entity_count": 3,
                "intent_confidence": 0.7,
                "complexity_score": 1.0,
                "ambiguity_score": 0.2,
                "memory_relevance_score": 0.0,
                "capability_count": 2,
                "tool_requirement_count": 3,
                "multiple_actions": True,
                "dependency_chain": True,
                "external_lookup": True,
                "code_execution": True,
                "filesystem_operation": True,
                "parallelizable": True,
                "requires_followup": True,
                "risk_score": 0.4,
                "web_search": True,
                "code_execution_hint": True,
                "filesystem_read": True,
                "filesystem_write": True,
                "tool_use": True,
                "deep_reasoning": False,
                "structured_output": False,
            },
            target="workflow",
        ),
        TopologyTrainingExample(
            example_id="ex-4",
            feature_version="topology_features_v1",
            features={
                "token_count": 25,
                "sentence_count": 4,
                "entity_count": 4,
                "intent_confidence": 0.5,
                "complexity_score": 0.8,
                "ambiguity_score": 0.4,
                "memory_relevance_score": 0.1,
                "capability_count": 3,
                "tool_requirement_count": 3,
                "multiple_actions": True,
                "dependency_chain": True,
                "external_lookup": True,
                "code_execution": True,
                "filesystem_operation": True,
                "parallelizable": True,
                "requires_followup": True,
                "risk_score": 0.3,
                "web_search": True,
                "code_execution_hint": True,
                "filesystem_read": True,
                "filesystem_write": True,
                "tool_use": True,
                "deep_reasoning": True,
                "structured_output": True,
            },
            target="multi_agent",
        ),
    ]


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
    examples = _make_examples()
    provider = FixtureTrainingDatasetProvider(examples)
    pipeline = TrainingPipeline(registry=registry, executor=SklearnTrainingExecutor(dataset_provider=provider))
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
    examples = _make_examples()
    provider = FixtureTrainingDatasetProvider(examples)
    pipeline = TrainingPipeline(registry=registry, executor=SklearnTrainingExecutor(dataset_provider=provider))
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


def test_local_mock_executor_creates_artifact():
    class MockTrainingExecutor:
        def execute(self, job: TrainingJob) -> TrainingArtifact:
            artifact_path = f"models/training/{job.job_id}"
            Path(artifact_path).mkdir(parents=True, exist_ok=True)
            (Path(artifact_path) / "model.bin").write_bytes(b"mock-model-weights")
            h = __import__("hashlib").sha256(b"mock-model-weights").hexdigest()
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

    executor = MockTrainingExecutor()
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="base", dataset_version="ds-v1"
    )
    artifact = executor.execute(job)
    assert artifact.artifact_path != ""
    assert artifact.artifact_hash != ""
    assert Path(artifact.artifact_path).exists()


def test_sklearn_executor_trains_real_model(tmp_path):
    examples = _make_examples()
    provider = FixtureTrainingDatasetProvider(examples)
    executor = SklearnTrainingExecutor(dataset_provider=provider)
    job = TrainingJob(
        job_id="job-1", task="intent", base_model="logistic_regression", dataset_version="ds-v1"
    )
    artifact = executor.execute(job)
    assert artifact.artifact_path != ""
    assert artifact.artifact_hash != ""
    assert Path(artifact.artifact_path).exists()
    assert "accuracy" in artifact.metrics
    assert "macro_f1" in artifact.metrics
    assert "weighted_f1" in artifact.metrics
    assert artifact.metrics.get("training_samples", 0) > 0
