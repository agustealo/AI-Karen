"""Governed local-only LoRA adapter fine-tuning.

Requires installed torch, transformers and peft. No remote code, downloads, model
publishing, or implicit license acceptance. Input JSONL uses {"text": "..."}.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingArtifact, TrainingJob
from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory


class TransformerLoRAExecutor:
    def execute(self, job: TrainingJob) -> TrainingArtifact:
        cfg = job.metadata.get("advanced_config") or {}
        base = cfg.get("base_model_path")
        if not isinstance(base, str) or not base:
            raise ValueError("An explicit local base_model_path is required")
        base_path = Path(base).resolve(strict=True)
        if not base_path.is_dir() or not (base_path / "config.json").is_file():
            raise ValueError("Base model must be a local Hugging Face model directory")
        if not cfg.get("license_accepted") or not isinstance(cfg.get("license_id"), str) or not cfg["license_id"].strip():
            raise PermissionError("Explicit base-model license identity and acknowledgement required")
        if cfg.get("license_model_path") != str(base_path):
            raise PermissionError("License acknowledgement does not match selected model")
        tenant = str(job.metadata.get("tenant_id") or "")
        if not tenant or tenant == "default":
            raise ValueError("Explicit tenant required for governed LoRA training")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import LoraConfig, TaskType, get_peft_model
        except ImportError as exc:
            raise RuntimeError("Install torch, transformers and peft in the training worker") from exc
        version = job.dataset_version
        if not version or version in {".", ".."} or any(not (c.isascii() and (c.isalnum() or c in "._-")) for c in version):
            raise ValueError("Invalid dataset version")
        path = Path(get_ml_registry_dir()) / "datasets" / (version + ".jsonl")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Canonical fine-tuning dataset missing")
        limit = int(cfg.get("max_samples", 1000))
        epochs = int(cfg.get("epochs", 1))
        max_length = int(cfg.get("sequence_length", 256))
        if not 16 <= limit <= 100000 or not 1 <= epochs <= 10 or not 32 <= max_length <= 2048:
            raise ValueError("Invalid bounded fine-tuning budget")
        texts = []
        with path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict) or not isinstance(obj.get("text"), str) or not obj["text"].strip():
                    raise ValueError("LoRA training records require nonempty text")
                texts.append(obj["text"])
                if len(texts) > limit:
                    raise ValueError("Dataset exceeds configured maximum samples")
        if len(texts) < 16:
            raise ValueError("Fine-tuning requires at least 16 nonempty examples")
        if len(set(texts)) != len(texts):
            raise ValueError("Duplicate text records can contaminate the held-out evaluation")
        seed = int(cfg.get("seed", job.seed))
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("Invalid training seed")
        random.Random(seed).shuffle(texts)
        holdout_count = max(3, math.ceil(len(texts) * float(cfg.get("test_split", 0.2))))
        if holdout_count >= len(texts) - 8:
            raise ValueError("Insufficient train and evaluation text examples")
        training_texts, validation_texts = texts[:-holdout_count], texts[-holdout_count:]
        if not torch.cuda.is_available() and not cfg.get("allow_cpu_training", False):
            raise RuntimeError("CUDA is unavailable; CPU training requires explicit opt-in")
        tokenizer = AutoTokenizer.from_pretrained(str(base_path), local_files_only=True, trust_remote_code=False)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(str(base_path), local_files_only=True, trust_remote_code=False)
        model.config.use_cache = False
        rank = int(cfg.get("lora_rank", 8))
        if rank not in (4, 8, 16, 32):
            raise ValueError("Unsupported LoRA rank")
        adapter = get_peft_model(model, LoraConfig(
            r=rank, lora_alpha=rank * 2, lora_dropout=0.05,
            task_type=TaskType.CAUSAL_LM,
        ))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        adapter.to(device).train()
        optimizer = torch.optim.AdamW((p for p in adapter.parameters() if p.requires_grad), lr=2e-4)
        losses = []
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        for _ in range(epochs):
            for text in training_texts:
                batch = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
                if batch["input_ids"].shape[1] < 2:
                    continue
                batch = {k: v.to(device) for k, v in batch.items()}
                labels = batch["input_ids"].clone()
                labels[batch["attention_mask"] == 0] = -100
                output = adapter(**batch, labels=labels)
                loss = output.loss
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(adapter.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                losses.append(float(loss.detach().cpu()))
        if not losses:
            raise ValueError("No trainable text sequences")
        adapter.eval()
        evaluation_losses = []
        with torch.no_grad():
            for text in validation_texts:
                batch = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
                if batch["input_ids"].shape[1] < 2:
                    continue
                batch = {k: v.to(device) for k, v in batch.items()}
                labels = batch["input_ids"].clone()
                labels[batch["attention_mask"] == 0] = -100
                loss = adapter(**batch, labels=labels).loss
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite holdout loss")
                evaluation_losses.append(float(loss.detach().cpu()))
        if not evaluation_losses:
            raise ValueError("Held-out examples produced no evaluable language-model tokens")
        key = hashlib.sha256(tenant.encode()).hexdigest()[:16]
        model_id = f"tenant-{key}-{job.task}-{job.job_id[:12]}"
        model_version = f"train-{job.job_id[:8]}"
        artifact = Path(get_ml_registry_dir()) / "topology" / model_id / model_version
        if artifact.exists():
            raise FileExistsError("Fine-tuning artifact version exists")
        artifact.mkdir(parents=True)
        adapter.save_pretrained(str(artifact), safe_serialization=True)
        tokenizer.save_pretrained(str(artifact))
        metadata = {
            "executor": "transformers", "artifact_type": "peft_lora_adapter",
            "base_model_path": str(base_path), "license_id": cfg["license_id"],
            "license_accepted": True, "training_samples": len(training_texts),
            "training_loss": sum(losses) / len(losses), "optimizer_steps": len(losses),
            "test_samples": len(evaluation_losses), "holdout_loss": sum(evaluation_losses) / len(evaluation_losses),
            "evaluation_method": "seeded_disjoint_text_holdout", "canonical_benchmark_status": "not_run",
            "model_id": model_id, "model_version": model_version, "task": job.task,
            "tenant_key": key, "tenant_scoped": True, "training_job_id": job.job_id,
            "dataset_version": version, "feature_version": "causal-lm-lora-v1",
        }
        (artifact / "training_metadata.json").write_text(json.dumps(metadata, sort_keys=True))
        return TrainingArtifact(
            artifact_path=str(artifact), artifact_hash=_hash_directory(artifact),
            model_id=model_id, model_version=model_version, task=job.task,
            dataset_version=version, training_config_version=job.training_config_version,
            metrics=metadata, resource_usage={"optimizer_steps": len(losses)},
        )
