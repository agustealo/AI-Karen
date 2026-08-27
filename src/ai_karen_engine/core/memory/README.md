# Unified Memory System - AI Karen

**Status:** Active canonical Core memory domain  
**Architecture:** Local-first, adapter-driven, tenant-scoped, auditable

## Purpose

`ai_karen_engine.core.memory` is the single Core authority for memory semantics, contracts, subsystem orchestration, recall coordination, STM semantics, episodic formation, and memory writeback policy.

Storage technology stays outside the Core boundary. Core describes capabilities and scope; platform adapters implement PostgreSQL and Redis mechanics.

For the detailed ownership model for NeuroRecall and NeuroVault, see [NEURO_MEMORY_ARCHITECTURE.md](./NEURO_MEMORY_ARCHITECTURE.md).

## Current Backend Truth

The live canonical platform adapter surface is:

- **PostgreSQL** for durable, ledger-backed memory state through `platform/memory/postgres/`.
- **Redis** for bounded/session-oriented STM through `platform/memory/redis/`.
- **SQLAlchemy/PostgresEngine** for canonical Postgres engine/session ownership.

Milvus and Elasticsearch are not part of the current memory architecture. Core code and documentation must not assume them.

Backend choices remain config-driven and replaceable behind memory ports/adapters.

## Authority Model

```text
ChatRuntime
    |
    v
MemoryRuntimeManager
    |-------------------------------|
    |                               |
    v                               v
STM / formation                 NeuroRecall
    |                       retrieval intelligence
    v                               |
NeuroVault                          v
governed durability          scoped source adapters
    |                               |
    +---------- PostgreSQL <--------+

STM/session continuity
    -> core/memory/stm semantics
    -> platform/memory/redis backing
```

### ChatRuntime

Owns overall chat execution. Memory is one subsystem used by ChatRuntime and must not become a competing chat orchestrator.

### MemoryRuntimeManager

Owns memory-subsystem orchestration, including recall coordination, formation/writeback coordination, lifecycle integration, and explicit degraded behavior.

It must not own provider/model routing, prompt construction, plugin execution, or physical database implementation.

### STM

`core/memory/stm/` owns bounded cross-request continuity semantics.

The live STM contract is slot-based. Independent slots include active episode, active goal, active project, recent context, working state, and tool state. Each slot has explicit tenant/user/session scope.

Redis is the current physical backing through `RedisSTMAdapter`. Redis does not own STM semantics.

The slot model is intentional: one writer updating active episode state must not overwrite unrelated tool or working state.

### Episodic memory

`core/memory/episodic/` owns event and episode semantics, including deterministic episode-boundary decisions.

An active episode may be cached through the STM contract. Completed/durable episodic history belongs to governed PostgreSQL memory, not Redis.

### NeuroRecall

Owns retrieval intelligence: activation, scoped candidate selection, scoring, fusion, reranking, temporal/staleness handling, diversity, token-budget selection, provenance, and recall diagnostics.

NeuroRecall never owns durable persistence.

### NeuroVault

Owns governed durability: approved writes, retention, deletion, tombstones, export, backup/restore, integrity/recovery, privacy enforcement, durable-write idempotency, and persistence audit.

NeuroVault never decides recall ranking or query strategy.

## Memory Layers

Memory classes describe semantics, not databases.

### STM

Short-horizon continuity such as recent context, active goals, active episode state, session state, tool state, and bounded working memory.

### Episodic

Meaningful events and interactions: what happened, when it happened, decisions, outcomes, boundaries, and event provenance.

### Semantic / LTM

Durable facts, preferences, relationships, stable knowledge, and curated assertions.

### Procedural

Learned procedures, reusable workflows, execution lessons, and tool-use knowledge.

## Current Package Responsibilities

Important active Core surfaces include:

- `memory_runtime_manager.py` - memory subsystem execution authority.
- `contracts.py`, `protocols.py`, `types/` - shared memory contracts.
- `stm/` - bounded short-term/session semantics.
- `episodic/` - episodic/event contracts and deterministic segmentation.
- `formation/` - governed memory candidate formation before NeuroVault.
- `retrieval/` - production recall intelligence and NeuroRecall.
- `graph/` - backend-neutral relationship projection/traversal semantics.
- `associative/` - bounded associative activation primitives.
- `evaluation/` - memory evaluation support.
- `guards.py`, scoring and claim modules - policy/scoring/lifecycle support.

Concrete storage belongs outside Core:

- `platform/memory/redis/` - Redis connection management and `RedisSTMAdapter`.
- `platform/memory/postgres/` - durable memory repositories, projections, recall sources and NeuroVault adapter.
- `persistence/postgres/` - canonical engine/session/transaction authority.

Do not reintroduce concrete Redis or PostgreSQL adapters under `core/memory/adapters/`.

## STM Rules

1. STM scope always includes explicit tenant, user, and session identity.
2. STM state is bounded and TTL-governed.
3. STM slots are physically independent so unrelated updates do not clobber each other.
4. Redis outage may use the connection manager's bounded in-process fallback, but this is process-local degraded continuity, not distributed durability.
5. Redis expiration is not durable forgetting.
6. STM success never means durable memory was saved.
7. Episode formation may consume STM, but episodic semantics do not belong to Redis.
8. `CognitiveState` is a current-request cognitive envelope, not the STM persistence model.

Canonical STM configuration is owned by `ai_karen_engine.config.memory`:

```text
MEMORY_STM_SESSION_TTL_SECONDS
MEMORY_STM_MAX_SLOT_BYTES
```

## Read Path

```text
ChatRuntime
    -> MemoryRuntimeManager
    -> NeuroRecall
    -> authorized/scoped memory sources
         -> Redis-backed STM candidate source where applicable
         -> PostgreSQL durable sources
    -> RecallResult
    -> prompt/context assembly
```

Recall must be tenant-scoped and fail closed when required authorization/scope context is missing.

## Write Path

```text
interaction
    -> memory formation
         -> bounded STM continuity
         -> deterministic episode segmentation
         -> signal extraction / worthiness
    -> policy + tenant + consent gates
    -> NeuroVault
    -> PostgreSQL durable state
    -> optional rebuildable projections/cache
```

No UI, agent, plugin, route, or retrieval helper may claim a memory was saved if durable persistence failed.

## Storage Rules

1. PostgreSQL is the current durable memory source of truth through adapters.
2. Redis is bounded/session infrastructure and is not durable long-term memory.
3. Core contracts remain vendor-neutral.
4. Optional indexes or projections must be rebuildable and must not become a second memory authority.
5. Storage failures must be observable and truthfully reported.
6. No cross-tenant fallback is permitted.
7. Core must not import concrete platform storage implementations.

## Temporal Memory

Memory should represent validity over time rather than only creation time. Where applicable, memory contracts should support:

- observation time;
- validity start/end;
- last verification;
- supersession;
- contradiction relationships;
- provenance/source references.

This allows Karen to distinguish current truth from historical truth and prevents stale memory from silently dominating recall.

## Provenance

Durable memory should preserve enough provenance to answer:

- where did this memory come from;
- was it explicit or inferred;
- which conversation/message/event produced it;
- which capability or agent extracted it;
- what evidence supported it;
- what confidence was assigned;
- which request/correlation IDs produced the write.

## Legacy Convergence

The repository still contains overlapping historical memory/recall implementations.

Convergence rules:

- production recall behavior belongs behind `core/memory/retrieval/` and NeuroRecall;
- governed durable persistence belongs behind NeuroVault contracts/platform adapters;
- Redis-specific memory behavior belongs under `platform/memory/redis/`, not Core;
- the temporary `platform/memory/redis/episode_state.py` compatibility alias must disappear after consumers migrate to `RedisSTMAdapter`;
- `core/recall/` must not remain a competing recall authority after useful behavior is migrated;
- the existing `core/neuro_recall/` labs harness remains research/evaluation-only;
- the existing `core/neuro_vault/` monolith must not remain a second complete memory system;
- fake or compatibility ML implementations must not be presented as real embedding/reranking capabilities;
- deletion happens only after reference audit, import migration, security review, and tests.

## Architecture Invariants

- One memory domain: `core/memory/`.
- One memory subsystem coordinator: `MemoryRuntimeManager`.
- One STM semantic authority: `core/memory/stm/`.
- One current STM platform adapter: `platform/memory/redis/RedisSTMAdapter`.
- One retrieval-intelligence concept: NeuroRecall.
- One governed-durability concept: NeuroVault.
- PostgreSQL remains durable truth.
- Redis remains bounded/session infrastructure.
- No provider/model authority in memory.
- No direct plugin execution from memory.
- No vendor-specific Core contracts.
- Tenant scope is explicit and fail-closed.
- Persistence and recall are observable.
- Compatibility shims must have a migration path and retirement target.

## Proof

Memory changes should be proven with the relevant subset of:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src

pytest tests/memory/test_stm_contracts.py -q
pytest tests/memory/test_redis_stm_adapter.py -q
```

Tests should cover tenant isolation, slot isolation, TTL/size bounds, degraded behavior, recall scope, durable persistence, retention/deletion, provenance, and architecture invariants when those surfaces change.

## Further Reading

- [NeuroRecall and NeuroVault Architecture](./NEURO_MEMORY_ARCHITECTURE.md)
- `src/ai_karen_engine/core/README.md` for Core ownership rules
- repository memory-unification and migration documents where still applicable

## Final Boundary

```text
MemoryRuntimeManager orchestrates memory.
STM owns bounded continuity semantics.
Redis backs STM through a platform adapter.
Episodic memory owns experience boundaries.
NeuroRecall decides what durable/temporary memory to retrieve.
NeuroVault governs how approved memory becomes and remains durable.
PostgreSQL is durable truth.
```
