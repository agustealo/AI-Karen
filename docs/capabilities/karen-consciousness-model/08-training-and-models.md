# 08 | Training strategy, adapters and model lifecycle

[← Index](README.md) · [Previous](07-datasets-and-curation.md) · [Next →](09-self-model.md)

## 1. Start with no neural training

First build the **KCM operational self-model projection** and quality-admission instrumentation. Demonstrate that memory and verified outcomes improve self-assessment through retrieval and typed state. Train a compact generator only where a benchmark shows measurable unmet need. This prevents spending compute on a feature that could be handled by context/prompt or procedural memory.

## 2. Model and task selection

Never hardcode the provider/model family into CORTEX. Benchmark locally approved candidate models for: CPU/RAM/VRAM cost, instruction following, target-task accuracy, Persona fidelity, factual correctness, refusal/abstention behavior, continual-training stability, license, downloadable revision and actual available hardware.

Evaluate compact instruction-tuned models for expression tasks, but **do not set a fixed parameter ceiling for all skills**. The smallest model meeting quality and capability requirements wins. A small model can still be called an LLM technically; KCM does not depend on terminology or parameter count.

## 3. Parameter-efficient fine-tuning

Recommended initial adaptation: **supervised fine-tuning (SFT) with LoRA** on a curated, frozen, approved task dataset, plus baseline comparison. Keep base model immutable and save versioned adapter artifacts. Prefer task- or Persona-specific adapters over creating a separate per-user neural model. Train user-specific adapters only after a distinct privacy and erasure review.

Official tooling: [Transformers TRL SFTTrainer](https://huggingface.co/docs/trl/sft_trainer) documents model-native conversational datasets, assistant-only loss where template supports masking, PEFT/LoRA integration and packing. **Pin the deployed library versions and verify parameter compatibility at implementation time.** Default to assistant/completion target loss, not next-token prediction over raw conversation logs (which would train on user prompts and sensitive context).

Configuration for reproducible runs: base model revision+SHA, tokenizer/template version, adapter rank/alpha/dropout, selected modules, optimizer, precision, epochs/steps, learning rate, warmup, gradient accumulation, max length, max tokens, seed, device and compiler/runtime versions. Verify weight loading security and trusted model sources; never activate arbitrary remote code.

## 4. Why no automatic continual LoRA updates?

Repeated small-batch fine-tuning can overfit, catastrophically forget and bias toward recent/noisy data. [Continual Learning survey (ACM, 2025)](https://doi.org/10.1145/3735633) and [ProCL (EMNLP 2026)](https://aclanthology.org/2026.findings-emnlp.1048/) describe the difficulty and research solutions. KCM v1 should batch offline adaptation, preserve a representative replay set **only if permitted**, and run backward-compatibility tests before every promotion.

Longer term: isolated adapter banks, regularization and controlled replay can be benchmarked; do not copy research architecture wholesale before seeing measured gains.

## 5. Training worker lifecycle

`requested -> admitted -> queued -> preparing -> training -> checkpointing -> validating -> evaluated -> pending_approval -> approved -> published -> healthy -> active`, with `failed`, `cancelled`, `rejected`, `quarantined`, `revoked` as explicit terminal/fenced states.

- Training jobs are durable, cancellable, idempotent and resource-budgeted.
- Reject missing dependencies, corrupted datasets, invalid licenses, missing permissions and unavailable hardware **with real errors**.
- Never substitute `_mock_training` and mark job successful; test doubles belong only in explicit unit tests.
- Real checkpoint must exist, hash-match and pass load/health probe before evaluation.
- Hold promotion behind independent evaluator, model readiness and RuntimePolicy authorization.
- Rollback references previous approved checkpoint and disables unsafe descendant artifacts.

## 6. Adapter isolation

- Persona adapters express stable styles; personal facts/preferences remain live memory-backed.
- Task/skill adapters are selected from registered capability metadata, **not** an LNTG-created second router.
- Do not merge personal/tenant adapters into shared base model without rights, lineage and verified erasure policy.
- Every inference result records actual `provider`, `model`, `runtime_engine`, `adapter_id/version`, `response_source`, degraded flags and correlation ID.
- Preserve `ExpressionGateway` streaming semantics; never silently switch models after partially streamed output.

## 7. Promotion gates

A model must improve a frozen target benchmark by a predefined effect size and confidence band, with no unacceptable regression on safety, factuality, general skills, Persona continuity, memory privacy, tenant isolation or tail latency. Distinguish *data quality*, *successful training*, *evaluated improvement* and *production deployment* as separate facts.

The existing [`MODEL_LIFECYCLE_ARCHITECTURE.md`](https://github.com/agustealo/AI-Karen/blob/main/docs/MODEL_LIFECYCLE_ARCHITECTURE.md) is authoritative for acquisition, verification, publication and activation. The new KCM design must fit into it.
