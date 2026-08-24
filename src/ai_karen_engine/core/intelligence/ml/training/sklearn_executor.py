from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
)
from sklearn.model_selection import train_test_split

from ai_karen_engine.config.config_manager import (
    get_ml_random_seed,
    get_ml_registry_dir,
    get_ml_training_max_samples,
    get_ml_training_test_size,
)
from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus
from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingExecutor,
    TrainingJob,
)
from ai_karen_engine.core.intelligence.ml.training.datasets import (
    JsonlTrainingDatasetProvider,
    TopologyTrainingExample,
)

logger = logging.getLogger(__name__)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_directory(directory: Path) -> str:
    h = hashlib.sha256()
    entries = []
    for entry in sorted(directory.rglob("*")):
        rel = entry.relative_to(directory)
        if entry.is_file():
            file_hash = hashlib.sha256()
            with entry.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    file_hash.update(chunk)
            entries.append((str(rel).replace("\\", "/"), entry.stat().st_size, file_hash.hexdigest()))
    for rel_path, size, digest in sorted(entries):
        h.update(f"{rel_path}\t{size}\t{digest}\n".encode())
    return h.hexdigest()


@dataclass
class _TrainingMetrics:
    accuracy: float = 0.0
    macro_f1: float = 0.0
    weighted_f1: float = 0.0
    log_loss_value: float = 0.0
    brier_score: float = 0.0
    class_support: dict[str, int] = field(default_factory=dict)
    confusion_matrix: list[list[int]] = field(default_factory=list)
    training_samples: int = 0
    validation_samples: int = 0
    test_samples: int = 0
    training_duration_ms: float = 0.0
    feature_version: str = ""
    dataset_version: str = ""


class SklearnTrainingExecutor(TrainingExecutor):
    def __init__(self, dataset_provider: Any = None) -> None:
        self._dataset_provider = dataset_provider

    def execute(self, job: TrainingJob) -> TrainingArtifact:
        start = time.perf_counter()
        examples = self._load_examples(job)
        if not examples:
            raise ValueError("No training examples loaded")

        max_samples = get_ml_training_max_samples()
        if len(examples) > max_samples:
            examples = examples[:max_samples]

        feature_version = examples[0].feature_version if examples else "v1"
        classes = sorted({ex.target for ex in examples})
        class_to_idx = {cls: idx for idx, cls in enumerate(classes)}
        idx_to_class = {idx: cls for cls, idx in class_to_idx.items()}

        X = np.array([list(ex.features.values()) for ex in examples], dtype=np.float64)
        y = np.array([class_to_idx[ex.target] for ex in examples], dtype=np.int64)

        _, counts = np.unique(y, return_counts=True)
        stratify = y if np.min(counts) >= 2 else None

        test_size = get_ml_training_test_size()
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=get_ml_random_seed(), stratify=stratify
        )

        model = LogisticRegression(
            max_iter=1000,
            random_state=get_ml_random_seed(),
            class_weight="balanced",
            solver="lbfgs",
        )
        model.fit(X_train, y_train)

        test_pred = model.predict(X_test)
        test_proba = model.predict_proba(X_test)

        metrics = self._compute_metrics(
            y_test, test_pred, test_proba, model.classes_, idx_to_class
        )
        metrics.training_samples = len(X_train)
        metrics.validation_samples = 0
        metrics.test_samples = len(X_test)
        metrics.training_duration_ms = (time.perf_counter() - start) * 1000.0
        metrics.feature_version = feature_version
        metrics.dataset_version = job.dataset_version

        model_id = f"topology-{job.task}"
        model_version = f"train-{job.job_id[:8]}"
        artifact_root = Path(get_ml_registry_dir()) / "topology" / model_id / model_version
        artifact_root.mkdir(parents=True, exist_ok=True)

        import joblib
        model_path = artifact_root / "model.joblib"
        joblib.dump(model, model_path)

        feature_schema = {
            "feature_version": feature_version,
            "feature_order": list(examples[0].features.keys()) if examples else [],
            "classes": classes,
        }
        feature_schema_path = artifact_root / "feature_schema.json"
        feature_schema_path.write_text(
            json.dumps(feature_schema, indent=2, sort_keys=True), encoding="utf-8"
        )

        training_metadata = {
            "training_samples": metrics.training_samples,
            "validation_samples": metrics.validation_samples,
            "test_samples": metrics.test_samples,
            "feature_version": metrics.feature_version,
            "dataset_version": metrics.dataset_version,
            "training_duration_ms": metrics.training_duration_ms,
            "accuracy": metrics.accuracy,
            "macro_f1": metrics.macro_f1,
            "weighted_f1": metrics.weighted_f1,
            "log_loss": metrics.log_loss_value,
            "brier_score": metrics.brier_score,
            "class_support": metrics.class_support,
            "confusion_matrix": metrics.confusion_matrix,
            "model_id": model_id,
            "model_version": model_version,
            "task": job.task,
            "base_model": job.base_model,
            "seed": get_ml_random_seed(),
            "test_size": test_size,
            "class_weight": "balanced",
        }
        metadata_path = artifact_root / "training_metadata.json"
        metadata_path.write_text(
            json.dumps(training_metadata, indent=2, sort_keys=True), encoding="utf-8"
        )

        manifest = MLModelManifest(
            model_id=model_id,
            purpose=job.task,
            architecture="logistic_regression",
            artifact_path=str(artifact_root),
            artifact_hash=_hash_directory(artifact_root),
            model_version=model_version,
            feature_version=feature_version,
            training_dataset_version=job.dataset_version,
            calibration_version="",
            metrics=training_metadata,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            status=ModelStatus.CANDIDATE.value,
        )
        manifest_path = Path(get_ml_registry_dir()) / f"{model_id}.json"
        manifest_path.write_text(
            json.dumps(manifest.__dict__, indent=2, sort_keys=True), encoding="utf-8"
        )

        return TrainingArtifact(
            artifact_path=str(artifact_root),
            artifact_hash=manifest.artifact_hash,
            model_id=model_id,
            model_version=model_version,
            task=job.task,
            dataset_version=job.dataset_version,
            training_config_version=job.training_config_version,
            metrics=training_metadata,
            resource_usage={"cpu_seconds": metrics.training_duration_ms / 1000.0},
        )

    def _load_examples(self, job: TrainingJob) -> list[TopologyTrainingExample]:
        if self._dataset_provider is not None:
            return self._dataset_provider.load(job.dataset_version)

        dataset_version = job.dataset_version
        provider_path = Path(get_ml_registry_dir()) / "datasets"
        if provider_path.exists():
            provider = JsonlTrainingDatasetProvider(provider_path)
            examples = provider.load(dataset_version)
            if examples:
                return examples
        raise ValueError(
            f"No dataset provider available for dataset_version={dataset_version}"
        )

    def _compute_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_proba: np.ndarray,
        class_indices: np.ndarray,
        idx_to_class: dict[int, str],
    ) -> _TrainingMetrics:
        metrics = _TrainingMetrics()
        metrics.accuracy = float(accuracy_score(y_true, y_pred))
        metrics.macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
        metrics.weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))

        try:
            metrics.log_loss_value = float(log_loss(y_true, y_proba, labels=class_indices))
        except ValueError:
            metrics.log_loss_value = 0.0

        present_labels = np.unique(np.concatenate([y_true, y_pred]))
        metrics.confusion_matrix = confusion_matrix(y_true, y_pred, labels=present_labels).tolist()

        unique, counts = np.unique(y_true, return_counts=True)
        metrics.class_support = {idx_to_class[int(cls)]: int(cnt) for cls, cnt in zip(unique, counts)}

        y_true_binary = np.zeros_like(y_true, dtype=np.float64)
        for idx, val in enumerate(y_true):
            y_true_binary[idx] = y_proba[idx, np.searchsorted(class_indices, val)]
        metrics.brier_score = float(brier_score_loss(np.ones_like(y_true, dtype=np.float64), y_true_binary))

        return metrics
