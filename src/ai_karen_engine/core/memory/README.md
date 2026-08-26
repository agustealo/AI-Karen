# Unified Memory System - AI Karen

**Status:** Active canonical Core memory domain  
**Architecture:** Local-first, adapter-driven, tenant-scoped, auditable

## Purpose

`ai_karen_engine.core.memory` is the single Core authority for memory semantics, contracts, subsystem orchestration, recall coordination, and memory writeback policy.

The memory system is intentionally backend-neutral at the Core boundary. Storage technology is accessed through adapters and configuration rather than embedded into memory-domain contracts.

For the detailed ownership model for NeuroRecall and NeuroVault, see [NEURO_MEMORY_ARCHITECTURE.md](./NEURO_MEMORY_ARCHITECTURE.md).

## Current Backend Truth

The live canonical adapter surface currently includes:

- **PostgreSQL** for durable, ledger-backed memory state.
- **Redis** for bounded/session-oriented memory where enabled.
- runtime-manager adapters for integration with the memory subsystem.

**Milvus and Elasticsearch are not part of the current memory architecture.** Core code and documentation must not assume them.

Backend choices must remain config-driven and replaceable behind memory ports/adapters.

## Authority Model

```text
ChatRuntime
    |
    v
MemoryRuntimeManager
    |-------------------------------|
    v                               v
NeuroRecall                     writeback policy
retrieval intelligence              |
    |                               v
    v                           NeuroVault
memory retrieval ports        governed durability
    |                               |
    +---------- PostgreSQL ---------+

STM/session continuity may use Redis through its canonical adapter.
```

### ChatRuntime

Owns overall chat execution. Memory is one subsystem used by ChatRuntime and must not become a competing chat orchestrator.

### MemoryRuntimeManager

Owns memory-subsystem orchestration, including recall coordination, memory candidate/writeback coordination, promotion flows, lifecycle integration, and explicit degraded behavior.

It must not own provider/model routing, prompt construction, plugin execution, or physical database implementation.

### NeuroRecall

Owns retrieval intelligence: activation, scoped candidate selection, scoring, fusion, reranking, temporal/staleness handling, diversity, token-budget selection, provenance, and recall diagnostics.

NeuroRecall never owns durable persistence.

### NeuroVault

Owns governed durability: approved writes, retention, deletion, tombstones, export, backup/restore, integrity/recovery, privacy enforcement, durable-write idempotency, and persistence audit.

NeuroVault never decides recall ranking or query strategy.

## Memory Layers

Memory classes describe semantics, not databases.

### STM

Short-horizon continuity such as recent context, active goals, session state, and bounded working memory.

### Episodic

Meaningful events and interactions: what happened, when it happened, decisions, outcomes, and event provenance.

### Semantic / LTM

Durable facts, preferences, relationships, stable knowledge, and curated assertions.

### Procedural

Learned procedures, reusable workflows, execution lessons, and tool-use knowledge.

## Current Package Responsibilities

The existing package contains canonical and transitional modules. New work should extend the strongest existing owner before creating new files or folders.

Important active surfaces include:

- `memory_runtime_manager.py` - memory subsystem runtime authority and compatibility surface during convergence.
- `contracts.py`, `protocols.py`, `types.py` - shared memory contracts.
- `adapters/postgres_adapter.py` - PostgreSQL adapter.
- `adapters/redis_adapter.py` - Redis/session adapter.
- `adapters/runtime_manager_adapter.py` - runtime integration adapter.
- `stm/` - short-term/session memory.
- `episodic/` - episodic/event-oriented memory.
- `retrieval/` - canonical destination for production recall intelligence.
- `evaluation/` - memory evaluation support.
- `guards.py` - memory safety/governance guards.
- ledger/writeback/scoring modules - durable memory candidate and write-path support.

Some legacy files remain and must be converged through reference audits rather than duplicated or deleted blindly.

## Read Path

The intended production read path is:

```text
ChatRuntime
    -> MemoryRuntimeManager
    -> NeuroRecall
    -> authorized/scoped memory ports
    -> PostgreSQL and/or bounded cache adapters
    -> RecallResult
    -> prompt/context assembly
```

Direct database fallback logic inside the runtime is transitional and should shrink as the canonical NeuroRecall path becomes complete.

Recall must be tenant-scoped and fail closed when required authorization/scope context is missing.

## Write Path

The intended durable write path is:

```text
interaction
    -> memory signal/candidate extraction
    -> worthiness / eligibility
    -> policy + tenant + consent gates
    -> canonical ledger/write
    -> NeuroVault governance
    -> PostgreSQL durable state
    -> optional rebuildable projections/cache
```

No UI, agent, plugin, route, or retrieval helper may claim a memory was saved if durable persistence failed.

## Storage Rules

1. PostgreSQL is the current durable memory source of truth through adapters.
2. Redis is bounded/session infrastructure and is not the durable long-term source of truth.
3. Core contracts remain vendor-neutral.
4. Optional indexes or projections must be rebuildable and must not become a second memory authority.
5. Storage failures must be observable and truthfully reported.
6. No cross-tenant fallback is permitted.

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
- `core/recall/` must not remain a competing recall authority after useful behavior is migrated;
- the existing `core/neuro_recall/` labs harness remains research/evaluation-only and should eventually move under an explicit labs owner;
- the existing `core/neuro_vault/` monolith must not remain a second complete memory system;
- fake or compatibility ML implementations must not be presented as real embedding/reranking capabilities;
- deletion happens only after reference audit, import migration, security review, and tests.

## Architecture Invariants

- One memory domain: `core/memory/`.
- One memory subsystem coordinator: `MemoryRuntimeManager`.
- One retrieval-intelligence concept: NeuroRecall.
- One governed-durability concept: NeuroVault.
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
```

Tests should cover tenant isolation, recall scope, degraded behavior, durable persistence, retention/deletion, provenance, and architecture invariants when those surfaces change.

## Further Reading

- [NeuroRecall and NeuroVault Architecture](./NEURO_MEMORY_ARCHITECTURE.md)
- `src/ai_karen_engine/core/README.md` for Core ownership rules
- repository memory-unification and migration documents where still applicable

## Final Boundary

```text
MemoryRuntimeManager orchestrates memory.
NeuroRecall decides what memory to retrieve.
NeuroVault governs how approved memory becomes and remains durable.
PostgreSQL and Redis are adapters, not architectural authorities.
```
