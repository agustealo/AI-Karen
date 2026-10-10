"""Governed CPU spaCy trainer for labeled textcat and NER JSONL.

The executor creates a local candidate artifact; publication is owned by TrainingPipeline.
"""
from __future__ import annotations

import hashlib
import json
import random
from itertools import islice
from pathlib import Path
from time import perf_counter

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingArtifact, TrainingJob
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory
from ai_karen_engine.core.intelligence.ml.training.spacy_datasets import validate_spacy_jsonl


class SpacyTrainingExecutor:
    def execute(self, job: TrainingJob) -> TrainingArtifact:
        import spacy
        from spacy.training import Example

        options = job.metadata.get("advanced_config", {})
        if options.get("engine") != "spacy":
            raise ValueError("spaCy training requires an approved spaCy configuration")
        tenant = job.metadata.get("tenant_id")
        if not tenant or tenant == "default":
            raise ValueError("Explicit tenant required")
        root = Path(get_ml_registry_dir()).resolve()
        version = job.dataset_version
        if not version or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in version) or version in {".", ".."}:
            raise ValueError("Invalid dataset identifier")
        dataset = root / "datasets" / f"{version}.jsonl"
        limit = int(options.get("max_samples", 10000))
        evidence = validate_spacy_jsonl(dataset, max_samples=limit)
        mode = evidence["mode"]
        with dataset.open("r", encoding="utf-8") as source:
            rows = [json.loads(line) for line in islice((line for line in source if line.strip()), limit)]
        seed = int(options.get("seed", 42))
        split = float(options.get("test_split", 0.2))
        if not 0.05 <= split <= 0.5:
            raise ValueError("Invalid held-out split")
        rng = random.Random(seed)
        rng.shuffle(rows)
        test_count = max(1, int(len(rows) * split))
        test_rows, train_rows = rows[:test_count], rows[test_count:]
        if not train_rows:
            raise ValueError("Missing training split")
        nlp = spacy.blank("en")
        pipe = nlp.add_pipe(mode)
        labels = sorted(evidence["class_counts"])
        for label in labels:
            pipe.add_label(label)
        def example(row):
            doc = nlp.make_doc(row["text"])
            if mode == "textcat":
                return Example.from_dict(doc, {"cats": {label: float(label == row["label"]) for label in labels}})
            return Example.from_dict(doc, {"entities": [tuple(span) for span in row["entities"]]})
        train = [example(row) for row in train_rows]
        optimizer = nlp.initialize(lambda: iter(train))
        start = perf_counter()
        iterations = min(int(options.get("max_iter", 100)), 100)
        if iterations < 1:
            raise ValueError("Invalid iterations")
        for _ in range(iterations):
            rng.shuffle(train)
            nlp.update(train, sgd=optimizer)
        evaluation = nlp.evaluate([example(row) for row in test_rows])
        score = float(evaluation.get("cats_macro_f", 0.0) if mode == "textcat" else evaluation.get("ents_f", 0.0))
        if not 0 <= score <= 1:
            raise ValueError("Invalid evaluation score")
        tenant_key = hashlib.sha256(str(tenant).encode()).hexdigest()[:16]
        model_id = f"tenant-{tenant_key}-{job.task}-{job.job_id[:12]}"
        model_version = f"train-{job.job_id[:8]}"
        artifact = root / "spacy" / model_id / model_version
        if artifact.exists():
            raise ValueError("Artifact path already exists; refusing overwrite")
        artifact.mkdir(parents=True)
        nlp.to_disk(artifact)
        metrics = {"macro_f1": score, "test_samples": len(test_rows), "training_samples": len(train_rows), "dataset_version": version, "feature_version": f"spacy_{mode}_v1", "engine": "spacy", "mode": mode}
        (artifact / "training_metrics.json").write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
        return TrainingArtifact(
            artifact_path=str(artifact), artifact_hash=_hash_directory(artifact),
            model_id=model_id, model_version=model_version, task=job.task,
            dataset_version=version, training_config_version=job.training_config_version,
            metrics=metrics, resource_usage={"training_duration_ms": (perf_counter() - start) * 1000},
        )
