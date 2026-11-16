# 02 | Repository audit and gap register

[← Index](README.md) · [Previous](01-mission-scope.md) · [Next →](03-architecture.md)

## Provenance of this audit

Inspected **read-only** via the connected GitHub repository tools on 2026-11-16. Baseline branch `main` commit `e570d950501915a9fce9e089ac91e583a71eb80e`. These are source-level observations, **not** runtime executions, exhaustive call-graph analysis or CI results. Reconfirm exact-head before making changes.

## Existing owners: retain and extend

| Current path | Observed contract | KCM treatment |
|---|---|---|
| [`core/memory/NEURO_MEMORY_ARCHITECTURE.md`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/NEURO_MEMORY_ARCHITECTURE.md) | NeuroRecall retrieval, NeuroVault durability, memory orchestrator | Treat as canonical memory decision |
| [`core/memory/types/base.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/types/base.py) | `ArtifactTrainingEligibility` with `ELIGIBLE/REVIEW/INELIGIBLE`; `ArtifactPrivacyTag.NO_TRAINING/NO_EXPORT`; memory types episodic/semantic/procedural | Reuse enums; introduce separate dataset admission status through **appropriate existing owner**, not a duplicate memory enum |
| [`core/memory/guards.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/guards.py) | Origin, trust class, sensitivity, consent and deletion propagation | Hard policy gate; do not duplicate privacy rules |
| [`core/memory/formation/evaluator.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/formation/evaluator.py) | Extracts signals, evaluates worthiness and privacy, canonical memory admission | Leave retention admission here |
| [`core/memory/scoring/`](https://github.com/agustealo/AI-Karen/tree/main/src/ai_karen_engine/core/memory/scoring) | Memory salience, ranking, reinforcement, contradiction scoring | Use for memory, never conflate with training objective utility |
| [`core/cognitive/state.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/cognitive/state.py) | CognitiveState and belief/learning/meta/adaptive snapshots | Extend derived projections, not competing cognitive-state store |
| [`core/personalization/runtime.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/personalization/runtime.py) | UserModelRuntime is a projection from existing user state and repository | Reuse for user-specific views; avoid copying user facts into weights |
| [`echocore/contracts.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/echocore/contracts.py) | Echo policy and `EchoTrainingCandidate` | Strengthen eligibility admission and schema |
| [`echocore/production_fine_tuner.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/echocore/production_fine_tuner.py) | Loads logs, builds text dataset, trains `AutoModelForCausalLM` when available | Must consume approved versioned datasets; remove fake-success training path |
| [`learning/training_data_manager.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/learning/training_data_manager.py) | Dataset create/list/delete, validation, versioning | Audit and secure; preserve strong functionality; do not make competing dataset manager |
| [`config/learning.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/config/learning.py) | LearningSettings: dataset dir, label quality, retention, feature flags, config validation | Extend centrally, disabled-by-default training admission and promotion |
| [`core/expression/gateway.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/expression/gateway.py) | Model expression gateway with model receipts and failure handling | No KCM provider bypass |
| [`docs/MODEL_LIFECYCLE_ARCHITECTURE.md`](https://github.com/agustealo/AI-Karen/blob/main/docs/MODEL_LIFECYCLE_ARCHITECTURE.md) | discover -> authorize -> acquire -> verify -> register -> activate -> execute | Bind KCM adapters/checkpoints to existing lifecycle |
| [`docs/ADR-001-karen-cognitive-runtime-architecture.md`](https://github.com/agustealo/AI-Karen/blob/main/docs/ADR-001-karen-cognitive-runtime-architecture.md) | Four-plane division: cognitive decisions, governance, execution, capabilities | Keep as overarching architecture; KCM is a capability/projection |

## Confirmed source-level findings

**F-01: Importance may trigger training queue.** `EchoPolicyEngine.evaluate()` admits some durable facts/preferences/projects when `importance_score >= .75` and episodic events at `importance_score >= .85`. No independent validity, purpose-bound consent or trained-model utility check is visible at that branch. **Severity: high** for any active training pipeline.

**F-02: Importance masquerades as quality.** `DefaultEchoCoreManager.ingest()` constructs `EchoTrainingCandidate.quality_score = max(importance_score, retention_score)`. **Severity: high**. Replace this proxy; keep memory importance in its original domain.

**F-03: Mock training success.** `ProductionFineTuner.fine_tune()` uses `_mock_training` if Transformers dependencies are unavailable, then marks its run completed. **Severity: critical** if that result qualifies a model for promotion. Production training must fail closed when dependencies are missing.

**F-04: Broad log-derived SFT source.** `ProductionFineTuner.prepare_dataset()` extracts `text`/`content`/`message` directly from logs and uses an ordered split. There is no demonstrated source-level authorization, record provenance, correct target label, conversation-group split, or held-out lineage check on this path. **Severity: high**. Do not enable it as KCM supervised training.

**F-05: Dataset tenancy placeholder.** `TrainingDataManager.list_datasets()` contains `del tenant_id  # Reserved for future tenant-aware dataset partitioning`. **Severity: critical** wherever accessible from a tenant-facing or mixed-tenant service. Inventory other methods and callers before reuse; enforce scope in storage queries, not only UI.

**F-06: Legacy overlapping types.** Memory domain and EchoCore both define artifact- and tier-like types. **Severity: medium**. Choose canonical memory input contract, create explicit audited conversion adapter at the boundary, prevent semantic drift.

**F-07: Enforcement already exists in memory types.** `NO_TRAINING`, `NO_EXPORT` and `ArtifactTrainingEligibility.REVIEW` already exist. **Severity: potential duplication**. KCM must consume them. `REVIEW` is not proof that training is allowed.

**F-08: Existing memory architecture differs from some historical diagrams.** Canonical memory documentation names PostgreSQL as durable backend and Redis as optional STM/session backend; specifically says **not to assume Milvus or Elasticsearch** as current architecture. **Severity: documentation drift**. Keep vendor ports configurable and do not invent deployed storage.

**F-09: Repeated-use reinforcement is heuristic.** `core/memory/scoring/reinforcement_scoring.py` currently uses word overlap and a simple negation check for reinforcement hints. **Severity: medium** if repurposed for correctness evidence. Never turn heuristic reinforcement into verified training ground truth.

## Must verify in the actual implementation phase

- Full call-site/reference audit: whether EchoCore training queue, generic DataManager and `fine_tuner.py` are reachable, feature-flagged or legacy.
- Current DB migrations, RLS policies, dataset artifact storage and deletion propagation.
- Actual model-training availability, hardware, retention controls, user opt-ins and deployment worker behavior.
- Current CI gates and exact-head release requirements.
- Whether model library and dataset manager already expose suitable admin UI and endpoints.

**No code was changed, no test was executed, and no PR was opened in this wiki-preparation task.**
