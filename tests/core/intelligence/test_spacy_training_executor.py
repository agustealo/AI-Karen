"""Execution proof for the opt-in spaCy training backend."""
from __future__ import annotations

import json

import pytest

from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory


@pytest.mark.parametrize("mode", ["textcat", "ner"])
def test_spacy_executor_creates_integrity_checked_candidate(tmp_path, monkeypatch, mode):
    spacy = pytest.importorskip("spacy")
    from ai_karen_engine.core.intelligence.ml.training import spacy_executor

    root = tmp_path / "registry"
    corpus = root / "datasets"
    corpus.mkdir(parents=True)
    rows = []
    for i in range(12):
        if mode == "textcat":
            rows.append({"example_id": str(i), "text": f"message number {i}",
                         "label": "A" if i % 2 else "B"})
        else:
            rows.append({"example_id": str(i), "text": "Alice works",
                         "entities": [[0, 5, "PERSON"]]})
    (corpus / "test-v1.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8",
    )
    monkeypatch.setattr(spacy_executor, "get_ml_registry_dir", lambda: str(root))
    job = TrainingJob(
        job_id=f"spacy-{mode}-test", task="intent", base_model="spacy",
        dataset_version="test-v1",
        metadata={"tenant_id": "tenant-a", "advanced_config": {
            "engine": "spacy", "max_samples": 12, "seed": 42,
            "test_split": 0.25, "max_iter": 2,
        }},
    )
    result = spacy_executor.SpacyTrainingExecutor().execute(job)
    assert result.metrics["mode"] == mode
    assert result.metrics["test_samples"] > 0
    assert result.artifact_hash == _hash_directory(
        __import__("pathlib").Path(result.artifact_path)
    )
    loaded = spacy.load(result.artifact_path)
    assert loaded.pipe_names == [mode]
    with pytest.raises(ValueError, match="already exists"):
        spacy_executor.SpacyTrainingExecutor().execute(job)


@pytest.mark.asyncio
async def test_spacy_textcat_through_governed_job_worker(tmp_path, monkeypatch):
    pytest.importorskip("spacy")
    from ai_karen_engine.core.intelligence.ml.training import pipeline as pipeline_module
    from ai_karen_engine.core.intelligence.ml.training import spacy_executor
    from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
    from ai_karen_engine.core.intelligence.ml.training.job_worker import TrainingJobWorker
    from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline
    from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench
    from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

    root = tmp_path / "registry"
    dataset_root = root / "datasets"
    dataset_root.mkdir(parents=True)
    rows = [
        {"example_id": str(i), "text": f"Example sentence {i}",
         "label": "A" if i % 2 else "B"}
        for i in range(12)
    ]
    (dataset_root / "governed.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_module, "get_ml_registry_dir", lambda: str(root))
    monkeypatch.setattr(spacy_executor, "get_ml_registry_dir", lambda: str(root))
    registry = MLModelRegistry(registry_dir=str(root))
    ledger = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    config = {
        "engine": "spacy", "task": "intent", "dataset_version": "governed",
        "test_split": 0.25, "max_samples": 12, "seed": 42,
        "max_iter": 2, "class_weight": "balanced",
        "optimizer": "lbfgs", "precision": "fp64",
    }
    workbench = AdvancedTrainingWorkbench(dataset_root=dataset_root)
    assert workbench.preflight(**config)["ready"]
    job = TrainingJob(
        job_id="spacy-worker-proof", task="intent", base_model="spacy",
        dataset_version="governed",
        metadata={"tenant_id": "tenant-a", "advanced_config": config},
    )
    ledger.submit(job, tenant_id="tenant-a", user_id="operator")
    worker = TrainingJobWorker(
        ledger=ledger, workbench=workbench,
        pipeline=TrainingPipeline(registry=registry),
    )
    result = await worker.run_claimed(job.job_id, tenant_id="tenant-a")
    assert result["status"] == "SUCCEEDED"
    assert result["job"]["artifact_hash"]
    candidates = [item for item in registry.list_all() if item.architecture == "spacy"]
    assert len(candidates) == 1
    assert candidates[0].status == "CANDIDATE"
    assert registry.validate_artifact(candidates[0])
