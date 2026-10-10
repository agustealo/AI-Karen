"""Fail-closed, engine-specific checks before durable training queue admission."""
from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


def preflight_advanced_engine(
    *, dataset_root: Path, engine: str, task: str, dataset_version: str,
    test_split: float, max_samples: int, base_model_path: str | None,
    license_id: str | None, license_accepted: bool,
    license_model_path: str | None, epochs: int, sequence_length: int,
    lora_rank: int, allow_cpu_training: bool, lags: int, horizon: int,
    dependency_availability: dict[str, bool] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    evidence: dict[str, Any] = {"dataset_version": dataset_version}
    def reject(code: str, detail: str) -> None:
        checks.append({"code": code, "message": detail})

    needed = ("numpy", "sklearn") if engine == "timeseries" else ("torch", "transformers", "peft")
    for module in needed:
        try:
            available = (dependency_availability.get(module, False)
                         if dependency_availability is not None
                         else importlib.util.find_spec(module) is not None)
        except (ImportError, ValueError):
            available = False
        if not available:
            reject("missing_dependency", f"Required training worker package missing: {module}")
    if not dataset_version or dataset_version in {".", ".."} or any(
        not (c.isascii() and (c.isalnum() or c in "._-")) for c in dataset_version
    ):
        reject("invalid_dataset_version", "Invalid dataset name")
        dataset = None
    else:
        dataset = dataset_root / (dataset_version + ".jsonl")
        if not dataset.is_file() or dataset.is_symlink():
            reject("dataset_missing", "Versioned JSONL dataset not found")
            dataset = None
    if not isinstance(max_samples, int) or not 16 <= max_samples <= 100000:
        reject("invalid_sample_limit", "Sample limit must be 16 to 100000")
    if not math.isfinite(test_split) or not 0.05 <= test_split <= 0.5:
        reject("invalid_test_split", "Holdout must be 0.05 to 0.5")
    if engine == "timeseries":
        if task != "outcome_forecast":
            reject("unsupported_task", "Temporal training requires outcome_forecast")
        if not isinstance(lags, int) or not 2 <= lags <= 128:
            reject("invalid_lags", "Lags must be 2 to 128")
        if not isinstance(horizon, int) or not 1 <= horizon <= 32:
            reject("invalid_horizon", "Forecast horizon must be 1 to 32")
    else:
        if task not in {"intent", "domain", "complexity", "ambiguity", "memory_relevance",
                        "capability", "execution_topology", "affect", "preference",
                        "outcome_forecast", "behavior_pattern"}:
            reject("unsupported_task", "Unknown ML task")
        if not base_model_path:
            reject("base_model_missing", "Select a locally installed model directory")
        else:
            base = Path(base_model_path).resolve()
            if not base.is_dir() or not (base / "config.json").is_file():
                reject("base_model_missing", "Local model config.json not found")
            if not license_accepted or not license_id or license_model_path != str(base):
                reject("license_not_accepted", "Accept the identified terms for this exact model")
        if not isinstance(epochs, int) or not 1 <= epochs <= 10:
            reject("invalid_epochs", "Epochs must be 1 to 10")
        if not isinstance(sequence_length, int) or not 32 <= sequence_length <= 2048:
            reject("invalid_sequence_length", "Token length must be 32 to 2048")
        if lora_rank not in (4, 8, 16, 32):
            reject("invalid_lora_rank", "Unsupported LoRA rank")
        if not allow_cpu_training:
            try:
                import torch
                if not torch.cuda.is_available():
                    reject("gpu_unavailable", "CUDA unavailable; opt in to CPU training explicitly")
            except ImportError:
                pass
    count = 0
    last = None
    seen_texts: set[str] = set()
    if dataset is not None:
        try:
            with dataset.open(encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    count += 1
                    if count > max_samples:
                        reject("sample_limit_exceeded", "Dataset exceeds configured sample limit")
                        break
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError("Each line must contain an object")
                    if engine == "timeseries":
                        stamp = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
                        if stamp.tzinfo is None or stamp.utcoffset() is None:
                            raise ValueError("Timezone-aware timestamps required")
                        value = obj["value"]
                        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                            raise ValueError("Finite numeric value required")
                        if obj.get("series_id", "default") != "default":
                            raise ValueError("Only one series per dataset is supported")
                        if last is not None and stamp.timestamp() <= last:
                            raise ValueError("Timestamps must be strictly increasing")
                        last = stamp.timestamp()
                    else:
                        if not isinstance(obj.get("text"), str) or not obj["text"].strip():
                            raise ValueError("Nonempty text required for LoRA dataset")
                        if obj["text"] in seen_texts:
                            raise ValueError("Duplicate text examples compromise the holdout")
                        seen_texts.add(obj["text"])
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            reject("invalid_dataset_record", str(exc))
    evidence["examples_scanned"] = count
    if count < (30 if engine == "timeseries" else 16):
        reject("insufficient_samples", "Dataset is too small")
    if engine == "timeseries" and isinstance(lags, int) and isinstance(horizon, int) and 2 <= lags <= 128 and 1 <= horizon <= 32 and count:
        windows = count - lags - horizon + 1
        holdout = max(5, math.ceil(windows * test_split))
        if windows - holdout - horizon < 10:
            reject("insufficient_temporal_windows", "Not enough embargoed train and test windows")
        evidence["holdout_windows"] = holdout
    return {
        "ready": not checks, "checks": checks, "warnings": [], "evidence": evidence,
        "execution": {"engine": engine, "task": task, "dataset_version": dataset_version},
    }
