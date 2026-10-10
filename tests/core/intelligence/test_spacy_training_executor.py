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
