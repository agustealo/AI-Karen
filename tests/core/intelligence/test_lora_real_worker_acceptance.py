"""Opt-in genuine LoRA worker acceptance using locally constructed test weights.

No downloads, no synthetic executor, no mocked optimizer or evaluation.
This runs only in the dedicated PEFT CI lane, never the default API image.
"""
from __future__ import annotations

import json

import pytest

from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.job_worker import TrainingJobWorker
from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline
from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench


@pytest.mark.asyncio
async def test_local_lora_worker_produces_real_candidate(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("peft")
    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
    import ai_karen_engine.core.intelligence.ml.training.transformer_executor as lora
    import ai_karen_engine.core.intelligence.ml.training.pipeline as pipeline_module

    torch.set_num_threads(1)
    root = tmp_path / "registry"
    (root / "datasets").mkdir(parents=True)
    base = tmp_path / "test-only-base"
    base.mkdir()
    vocabulary = {"<pad>": 0, "<eos>": 1, "<unk>": 2}
    vocabulary.update({word: idx + 3 for idx, word in enumerate(
        ["training", "example", "topic", "alpha", "beta", "gamma",
         "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen",
         "fourteen", "fifteen", "sixteen", "seventeen", "eighteen"]
    )})
    engine = Tokenizer(WordLevel(vocabulary, unk_token="<unk>"))
    engine.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=engine, eos_token="<eos>", pad_token="<pad>",
        unk_token="<unk>",
    )
    tokenizer.save_pretrained(str(base))
    GPT2LMHeadModel(GPT2Config(
        vocab_size=len(vocabulary), n_positions=64, n_ctx=64,
        n_embd=32, n_layer=1, n_head=2,
        bos_token_id=1, eos_token_id=1,
    )).save_pretrained(str(base), safe_serialization=True)
    dataset = root / "datasets" / "lora-test.jsonl"
    dataset.write_text("".join(
        json.dumps({"text": f"training example topic {word} one two three"}) + "\n"
        for word in list(vocabulary)[3:23]
    ), encoding="utf-8")
    config = {
        "engine": "transformers", "task": "intent",
        "dataset_version": "lora-test", "test_split": 0.2,
        "max_samples": 20, "seed": 42,
        "base_model_path": str(base.resolve()),
        "license_id": "locally-generated-test-weights",
        "license_accepted": True,
        "license_model_path": str(base.resolve()),
        "epochs": 1, "sequence_length": 32, "lora_rank": 4,
        "allow_cpu_training": True,
    }
    monkeypatch.setattr(lora, "get_ml_registry_dir", lambda: str(root))
    monkeypatch.setattr(pipeline_module, "get_ml_registry_dir", lambda: str(root))
    workbench = AdvancedTrainingWorkbench(dataset_root=root / "datasets")
    preflight = workbench.preflight(**config)
    assert preflight["ready"], preflight["checks"]
    ledger = TrainingJobLedger(database=tmp_path / "jobs.sqlite3")
    registry = MLModelRegistry(registry_dir=str(root))
    job = TrainingJob(
        job_id="lora-local-proof", task="intent", base_model="transformers",
        dataset_version="lora-test",
        metadata={"tenant_id": "tenant-a", "advanced_config": config},
    )
    assert ledger.submit(job, tenant_id="tenant-a", user_id="operator")["status"] == "QUEUED"
    assert ledger.get(job.job_id, tenant_id="tenant-b") is None
    worker = TrainingJobWorker(
        ledger=ledger, workbench=workbench,
        pipeline=TrainingPipeline(registry=registry),
    )
    result = await worker.run_claimed(job.job_id, tenant_id="tenant-a")
    assert result["status"] == "SUCCEEDED"
    metrics = result["job"]["metrics"]
    assert metrics["artifact_type"] == "peft_lora_adapter"
    assert metrics["optimizer_steps"] > 0
    assert metrics["test_samples"] >= 3
    assert metrics["holdout_loss"] >= 0
    assert result["job"]["artifact_hash"]
    candidates = registry.list_all()
    assert len(candidates) == 1
    assert candidates[0].status == "CANDIDATE"
    assert registry.validate_artifact(candidates[0])
