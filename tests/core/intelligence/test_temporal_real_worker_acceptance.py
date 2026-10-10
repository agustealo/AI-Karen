"""Real temporal training acceptance test through durable queue and worker.

No synthetic pipeline or model artifacts: exercises the canonical executor,
real holdout metrics, registration, and tenant-scoped job lifecycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.job_worker import TrainingJobWorker
from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline
from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench


@pytest.mark.asyncio
async def test_temporal_real_worker_queue_to_registered_candidate(tmp_path, monkeypatch):
    import ai_karen_engine.core.intelligence.ml.training.temporal_executor as temporal
    import ai_karen_engine.core.intelligence.ml.training.pipeline as pipeline_module

    monkeypatch.setattr(temporal, "get_ml_registry_dir", lambda: str(tmp_path))
    monkeypatch.setattr(pipeline_module, "get_ml_registry_dir", lambda: str(tmp_path))

    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with (dataset_root / "real-series.jsonl").open("w", encoding="utf-8") as output:
        for i in range(90):
            output.write(json.dumps({
                "timestamp": (start + timedelta(days=i)).isoformat(),
                "value": float(i) + 0.15 * (i % 4),
            }) + "\n")

    cfg = {
        "engine": "timeseries",
        "task": "outcome_forecast",
        "dataset_version": "real-series",
        "test_split": 0.2,
        "max_samples": 100,
        "seed": 42,
        "max_iter": 1000,
        "class_weight": "balanced",
        "optimizer": "lbfgs",
        "precision": "fp64",
        "base_model_path": None,
        "license_id": None,
        "license_accepted": False,
        "license_model_path": None,
        "epochs": 1,
        "sequence_length": 256,
        "lora_rank": 8,
        "allow_cpu_training": True,
        "lags": 5,
        "horizon": 1,
    }
    workbench = AdvancedTrainingWorkbench(dataset_root=dataset_root)
    preflight = workbench.preflight(**cfg)
    assert preflight["ready"], preflight["checks"]

    ledger = TrainingJobLedger(database=tmp_path / "jobs.sqlite3")
    job = TrainingJob(
        job_id="temporal-real-flow",
        task="outcome_forecast",
        base_model="timeseries",
        dataset_version="real-series",
        metadata={"tenant_id": "tenant-a", "advanced_config": cfg},
    )
    queued = ledger.submit(job, tenant_id="tenant-a", user_id="operator")
    assert queued["status"] == "QUEUED"
    assert ledger.get(job.job_id, tenant_id="tenant-b") is None

    registry = MLModelRegistry(registry_dir=str(tmp_path / "manifests"))
    worker = TrainingJobWorker(
        ledger=ledger,
        workbench=workbench,
        pipeline=TrainingPipeline(registry=registry),
    )
    result = await worker.run_claimed(job.job_id, tenant_id="tenant-a")
    assert result["status"] == "SUCCEEDED"
    assert result["job"]["metrics"]["temporal_validation"] == "chronological_holdout_with_embargo"
    assert result["job"]["metrics"]["test_samples"] >= 5
    assert result["job"]["artifact_hash"]
    assert ledger.get(job.job_id, tenant_id="tenant-b") is None
    assert ledger.get(job.job_id, tenant_id="tenant-a")["status"] == "SUCCEEDED"
