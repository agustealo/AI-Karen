from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingJob,
)
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.job_worker import TrainingJobWorker


class WorkbenchStub:
    def preflight(self, **configuration):
        return {"ready": True, "checks": []}


class PipelineStub:
    def __init__(self, success=True):
        self.success = success
        self.calls = 0

    async def run(self, result, on_state=None, authorize_publication=None):
        self.calls += 1
        if on_state is not None:
            result.job.status = 'RUNNING'
            await on_state('RUNNING', result.job)
            result.job.status = 'EVALUATING'
            await on_state('EVALUATING', result.job)
        if authorize_publication is not None and not authorize_publication():
            result.error = 'Expired training lease'
            result.job.status = 'FAILED'
            return result
        if self.success:
            result.job.status = "SUCCEEDED"
            result.registered = True
        else:
            result.job.status = "FAILED"
            result.error = "Synthetic failure"
        return result


def enqueue(store):
    job = TrainingJob(
        job_id="candidate-1", task="affect",
        base_model="sklearn", dataset_version="test-v1",
        metadata={
            "tenant_id": "tenant-a",
            "advanced_config": {\n                "engine": "sklearn", "task": "affect",\n                "dataset_version": "test-v1",\n            },
        },
    )
    store.submit(job, tenant_id="tenant-a", user_id="operator")


@pytest.mark.asyncio
async def test_worker_claims_and_finishes_persisted_job(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    enqueue(store)
    pipeline = PipelineStub()
    worker = TrainingJobWorker(ledger=store, pipeline=pipeline, workbench=WorkbenchStub())
    result = await worker.run_claimed("candidate-1", tenant_id="tenant-a")
    assert result["status"] == "SUCCEEDED"
    assert pipeline.calls == 1
    with pytest.raises(ValueError, match="already claimed"):
        await worker.run_claimed("candidate-1", tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_worker_marks_failure_and_preserves_evidence(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    enqueue(store)
    worker = TrainingJobWorker(
        ledger=store, pipeline=PipelineStub(False), workbench=WorkbenchStub(),
    )
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        await worker.run_claimed("candidate-1", tenant_id="tenant-a")
    record = store.get("candidate-1", tenant_id="tenant-a")
    assert record["status"] == "FAILED"
    assert "Synthetic failure" in record["job"]["error_message"]


@pytest.mark.asyncio
async def test_worker_never_claims_another_tenants_job(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    enqueue(store)
    worker = TrainingJobWorker(
        ledger=store, pipeline=PipelineStub(), workbench=WorkbenchStub(),
    )
    with pytest.raises(ValueError, match="already claimed"):
        await worker.run_claimed("candidate-1", tenant_id="tenant-b")
    assert store.get("candidate-1", tenant_id="tenant-a")["status"] == "QUEUED"
