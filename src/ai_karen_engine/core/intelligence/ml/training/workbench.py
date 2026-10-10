"""Validated advanced training workbench contracts for the canonical ML pipeline.

Only options backed by current execution services are exposed as runnable.
The design intentionally avoids claiming distributed GPUs, fp8, spaCy pipeline
freezing, or HF exports without an installed executor.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import (
    get_ml_registry_dir,
    get_ml_training_max_samples,
    get_ml_training_test_size,
    get_ml_random_seed,
)
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask

_ADAPTIVE_TASKS = frozenset({
    PredictionTask.INTENT.value,
    PredictionTask.DOMAIN.value,
    PredictionTask.COMPLEXITY.value,
    PredictionTask.AMBIGUITY.value,
    PredictionTask.MEMORY_RELEVANCE.value,
    PredictionTask.CAPABILITY.value,
    PredictionTask.EXECUTION_TOPOLOGY.value,
    PredictionTask.AFFECT.value,
    PredictionTask.PREFERENCE.value,
    PredictionTask.OUTCOME_FORECAST.value,
    PredictionTask.BEHAVIOR_PATTERN.value,
})

class AdvancedTrainingWorkbench:
    """Backend-owned catalog and request validation, never UI heuristics."""

    def __init__(self, dataset_root: Path | None = None) -> None:
        self.dataset_root = (
            dataset_root if dataset_root is not None
            else Path(get_ml_registry_dir()) / "datasets"
        )

    def catalog(self) -> dict[str, Any]:
        import importlib.util

        def installed(module: str) -> bool:
            try:
                return importlib.util.find_spec(module) is not None
            except (ImportError, ValueError, AttributeError):
                return False

        # Engine capability inventory is authoritative here. Python package presence
        # alone is not proof of a governed trainer or a compatible dataset contract.
        engine_specs = (
            ("sklearn", "Classical ML classifier",
             "core.intelligence.ml.training.sklearn_executor",
             ("sklearn", "joblib"),
             "Registry-backed classification on numeric-feature JSONL."),
            ("spacy", "spaCy text categorization (NER evaluation pending)",
             "core.intelligence.ml.training.spacy_executor", ("spacy",),
             "Text categorization runs through the governed worker; NER remains blocked pending entity-span benchmark."),
            ("transformers", "Transformer / LoRA / PEFT", "core.intelligence.ml.training.transformer_executor",
             ("transformers", "peft", "torch"),
             "Requires a governed fine-tuning executor, base-model license checks, and a compatible dataset."),
            ("timeseries", "Temporal forecasting", "core.intelligence.ml.training.temporal_executor", ("numpy", "sklearn"),
             "Requires time-indexed datasets, temporal validation, a forecasting executor, and predictor contract."),
        )
        engines = []
        for engine_id, label, executor, dependencies, details in engine_specs:
            missing = [module for module in dependencies if not installed(module)]
            wired = executor is not None
            supported = wired and not missing
            engines.append({
                "id": engine_id,
                "label": label,
                "supported": supported,
                "executor": executor if supported else None,
                "status": "ready" if supported else (
                    "missing_dependencies" if wired and missing else "not_implemented"
                ),
                "missing_dependencies": missing,
                "details": details,
            })
        datasets = []
        if self.dataset_root.exists():
            for path in sorted(self.dataset_root.glob("*.jsonl")):
                if not path.is_file() or path.is_symlink():
                    continue
                datasets.append({
                    "version": path.stem,
                    "bytes": path.stat().st_size,
                    "format": "jsonl",
                })
        return {
            "engines": engines,
            "tasks": sorted(_ADAPTIVE_TASKS),
            "datasets": datasets,
            "defaults": {
                "engine": "sklearn",
                "seed": get_ml_random_seed(),
                "test_split": get_ml_training_test_size(),
                "max_samples": get_ml_training_max_samples(),
                "max_iter": 1000,
                "class_weight": "balanced",
                "optimizer": "lbfgs",
                "precision": "fp64",
            },
            "configuration": {
                "engines_declare_support": True,
                "runtime_source_of_truth": "core.intelligence.ml",
                "unsupported_export_targets": [
                    "onnx", "tensorrt", "spacy_wheel", "huggingface_push",
                ],
            },
        }

    def preflight(
        self,
        *,
        engine: str,
        task: str,
        dataset_version: str,
        test_split: float,
        max_samples: int,
        seed: int,
        max_iter: int,
        class_weight: str,
        optimizer: str,
        precision: str,
        base_model_path: str | None = None,
        license_id: str | None = None,
        license_accepted: bool = False,
        license_model_path: str | None = None,
        epochs: int = 1,
        sequence_length: int = 256,
        lora_rank: int = 8,
        allow_cpu_training: bool = False,
        lags: int = 5,
        horizon: int = 1,
    ) -> dict[str, Any]:
        if engine in {"transformers", "timeseries"}:
            from ai_karen_engine.core.intelligence.ml.training.advanced_preflight import preflight_advanced_engine
            return preflight_advanced_engine(
                dataset_root=self.dataset_root, engine=engine, task=task,
                dataset_version=dataset_version, test_split=test_split,
                max_samples=max_samples, base_model_path=base_model_path,
                license_id=license_id, license_accepted=license_accepted,
                license_model_path=license_model_path, epochs=epochs,
                sequence_length=sequence_length, lora_rank=lora_rank,
                allow_cpu_training=allow_cpu_training, lags=lags, horizon=horizon,
            )
        failures: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        def error(code: str, message: str) -> None:
            failures.append({"code": code, "message": message})

        selected_engine = next((item for item in self.catalog()["engines"] if item["id"] == engine), None)
        if selected_engine is None or not selected_engine["supported"]:
            error("unsupported_engine", "A governed, dependency-ready executor is not available for this engine.")
        if task not in _ADAPTIVE_TASKS:
            error("unknown_task", "Task is absent from the supported ML prediction registry.")
        if not dataset_version or not all(
            c.isascii() and (c.isalnum() or c in "._-") for c in dataset_version
        ) or dataset_version in {".", ".."}:
            error("invalid_dataset_version", "Use an existing dataset version identifier.")
            path = None
        else:
            path = self.dataset_root / f"{dataset_version}.jsonl"
            if not path.is_file() or path.is_symlink():
                error("dataset_missing", "The requested canonical ML dataset was not found.")

        if engine == "spacy":
            from ai_karen_engine.core.intelligence.ml.training.spacy_datasets import (
                validate_spacy_jsonl,
            )

            evidence: dict[str, Any] = {
                "dataset_version": dataset_version,
                "examples_scanned": 0,
                "class_counts": {},
                "feature_count": 0,
            }
            if path is not None and path.is_file() and not path.is_symlink():
                try:
                    result = validate_spacy_jsonl(path, max_samples=max_samples)
                    evidence.update(result)
                except ValueError as exc:
                    error("invalid_spacy_dataset", str(exc))
            if evidence.get("mode") != "textcat":
                error("unsupported_spacy_mode", "Only spaCy text categorization has a governed benchmark; NER is not dispatchable.")
            if not math.isfinite(test_split) or not 0.05 <= test_split <= 0.5:
                error("invalid_test_split", "spaCy held-out split must be between 0.05 and 0.5.")
            if not 10 <= max_samples <= 100000:
                error("invalid_sample_limit", "spaCy sample limit must be between 10 and 100000.")
            if not 0 <= seed <= 2**32 - 1:
                error("invalid_seed", "Seed is outside supported range.")
            if not 1 <= max_iter <= 100:
                error("invalid_max_iter", "spaCy CPU updates must be between 1 and 100.")
            if precision != "fp64" or optimizer != "lbfgs" or class_weight != "balanced":
                error("unsupported_configuration", "This spaCy CPU trainer uses its own optimizer; leave legacy UI options at defaults.")
            if evidence.get("mode") == "textcat":
                counts = evidence.get("class_counts", {})
                if any(count < 2 for count in counts.values()):
                    error("split_class_support", "Every text category needs at least two rows for train/test splitting.")
                # Executor stratifies independently per label: one row is held out
                # per category even for small datasets. Validate this same contract.
                if not counts:
                    error("split_class_support", "Text categorization must contain labeled classes.")
            return {
                "ready": not failures,
                "checks": failures,
                "warnings": warnings,
                "evidence": evidence,
                "execution": {"engine": engine, "task": task},
            }

        if not math.isfinite(test_split) or not (0.05 <= test_split <= 0.5):
            error("invalid_test_split", "Test split must be between 0.05 and 0.5.")
        if not (10 <= max_samples <= 10_000_000):
            error("invalid_sample_limit", "Sample limit must be between 10 and 10000000.")
        if not (0 <= seed <= 2**32 - 1):
            error("invalid_seed", "Seed is outside supported range.")
        if not (100 <= max_iter <= 10000):
            error("invalid_max_iter", "Maximum iterations must be between 100 and 10000.")
        if class_weight not in {"balanced", "none"}:
            error("unsupported_class_weight", "Class weight must be balanced or none.")
        if optimizer != "lbfgs":
            error("unsupported_optimizer", "Current executor only supports lbfgs.")
        if precision != "fp64":
            error("unsupported_precision", "Current sklearn executor only supports CPU float64.")

        examples = 0
        labels: dict[str, int] = {}
        features: tuple[str, ...] | None = None
        seen_feature_version: str | None = None
        if path is not None and path.is_file() and not path.is_symlink():
            import json
            with path.open("r", encoding="utf-8") as source:
                for index, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    if examples >= max_samples:
                        break
                    try:
                        entry = json.loads(line)
                        if not isinstance(entry, dict):
                            raise ValueError("training record must be an object")
                        if not isinstance(entry.get("example_id"), str) or not entry["example_id"]:
                            raise ValueError("example_id is required by the dataset loader")
                        if not isinstance(entry.get("feature_version"), str) or not entry["feature_version"]:
                            raise ValueError("feature_version is required by the dataset loader")
                        feature_map = entry["features"]
                        label = entry["target"]
                        if not isinstance(feature_map, dict) or not feature_map:
                            raise ValueError("features must be a non-empty object")
                        if not isinstance(label, str) or not label:
                            raise ValueError("target must be a non-empty class label")
                        if seen_feature_version is None:
                            seen_feature_version = entry["feature_version"]
                        elif entry["feature_version"] != seen_feature_version:
                            raise ValueError("feature_version differs across examples")
                        names = tuple(feature_map.keys())
                        if features is None:
                            features = names
                        elif names != features:
                            raise ValueError("feature order differs across examples")
                        if not all(
                            isinstance(v, (int, float, bool))
                            and math.isfinite(float(v))
                            for v in feature_map.values()
                        ):
                            raise ValueError("feature values must be finite numeric scalars")
                        labels[label] = labels.get(label, 0) + 1
                        examples += 1
                    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                        error("invalid_dataset_record", f"Invalid record {index}: {exc}")
                        break
            if examples < 10:
                error("insufficient_samples", "At least ten valid training samples are required.")
            if len(labels) < 2:
                error("insufficient_classes", "Classification needs at least two distinct classes.")
            if test_split >= 0.05 and examples:
                test_count = math.ceil(examples * test_split)
                if test_count < len(labels):
                    error("test_split_too_small", "Test split does not contain enough rows for all classes.")
                if min(labels.values(), default=0) < 2:
                    error(
                        "rare_classes",
                        "Every class needs at least two examples for stratified training.",
                    )
                elif examples - test_count < len(labels):
                    error(
                        "training_split_too_small",
                        "Training split must retain an example from every class.",
                    )

        return {
            "ready": not failures,
            "checks": failures,
            "warnings": warnings,
            "evidence": {
                "dataset_version": dataset_version,
                "examples_scanned": examples,
                "class_counts": labels,
                "feature_count": len(features or ()),
            },
            "execution": {
                "engine": engine,
                "task": task,
                "max_samples": max_samples,
                "seed": seed,
                "test_split": test_split,
                "optimizer": optimizer,
                "precision": precision,
                "max_iter": max_iter,
                "class_weight": class_weight,
            },
        }
