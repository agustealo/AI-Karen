# NeuroRecall and NeuroVault Architecture

**Status:** Canonical memory architecture direction  
**Scope:** AI Karen memory subsystem  
**Rule:** One memory domain, one recall intelligence path, one governed persistence path.

## Purpose

AI Karen uses `core/memory/` as the canonical memory domain. Two named capabilities sit inside that domain boundary:

- **NeuroRecall** is the retrieval-intelligence capability. It decides what memory should be recalled and how candidates are ranked, fused, filtered, and explained.
- **NeuroVault** is the governed durability capability. It controls how approved memory becomes durable, how it is retained, deleted, restored, exported, and audited.

Neither capability is a second memory system.

## Authority Model

```text
ChatRuntime
    |
    v
MemoryRuntimeManager
    |------------------------------|
    v                              v
NeuroRecall                    writeback policy
(retrieval intelligence)          |
    |                              v
    |                         NeuroVault
    |                    (governed durability)
    v                              |
Memory ports                       v
    |                         persistence adapters
    |                              |
    +-----------> PostgreSQL <-----+

STM/session continuity may use Redis through the canonical memory adapter.
```

### Ownership

`ChatRuntime` remains the overall chat-execution authority.

`MemoryRuntimeManager` owns orchestration inside the memory subsystem. It coordinates recall, writeback, promotion, and degraded behavior, but it does not implement persistence engines or provider/model routing.

`NeuroRecall` owns retrieval strategy.

`NeuroVault` owns governed durable persistence.

## Current Backend Truth

The current canonical memory adapter surface is:

- **PostgreSQL** for durable memory records and ledger-backed memory state.
- **Redis** for bounded/session-oriented memory where enabled.
- Runtime-manager adapters for integration with the memory runtime.

Milvus and Elasticsearch are not part of the current architecture and must not be assumed by Core contracts, documentation, fallback logic, or runtime routing.

Backend choices must remain adapter-driven and config-driven. Core memory contracts describe capabilities, not vendor products.

## NeuroRecall

### Responsibility

NeuroRecall answers one question:

> Given this request and authorized memory scope, what memory should Karen recall now?

It should own:

- recall activation and memory-need decisions;
- tenant/user/session/conversation scope enforcement before retrieval;
- query decomposition where useful;
- candidate-source selection;
- lexical, semantic, temporal, importance, confidence, and relationship scoring when those capabilities are available;
- score normalization and fusion;
- reranking;
- contradiction/staleness handling;
- diversity and redundancy control;
- token-budget-aware selection;
- provenance and evidence preservation;
- recall explanation and structured diagnostics.

### NeuroRecall must not own

- durable writes;
- PostgreSQL schema ownership;
- Redis lifecycle ownership;
- backup/restore;
- retention/deletion policy;
- provider/model selection;
- prompt construction;
- plugin execution;
- global RBAC authority;
- chat orchestration.

### Target flow

```text
RecallRequest
    -> scope gate
    -> activation decision
    -> retrieval plan
    -> candidate retrieval through ports
    -> score normalization
    -> fusion
    -> reranking
    -> contradiction/staleness checks
    -> token-budget selection
    -> RecallResult + provenance + telemetry
```

### Recall scope

Recall must fail closed when required tenant context is absent.

A recall request should be able to carry explicit scope such as:

- `tenant_id`
- `user_id`
- `conversation_id`
- `session_id`
- `agent_id`
- `workspace_id`
- `project_id`
- memory namespace/type constraints

No missing scope may silently expand into cross-tenant or cross-user retrieval.

### Async contract

The canonical runtime path should be async-safe. NeuroRecall must not call `asyncio.run()` inside an active runtime path and must not hide retrieval failures with broad `except Exception: pass` fallbacks.

Degraded behavior must be explicit and observable.

## NeuroVault

### Responsibility

NeuroVault answers a different question:

> Once a memory candidate is approved for durability, how is it persisted and governed safely throughout its lifecycle?

It should own or enforce through canonical platform adapters:

- governed durable writes;
- tenant and user ownership checks at the persistence boundary;
- consent enforcement;
- retention policy;
- deletion and tombstones;
- export;
- backup and restore;
- integrity verification;
- migration/recovery controls;
- PII/privacy handling before or during persistence;
- persistence audit events;
- idempotency for durable writes;
- durable-memory lifecycle metadata.

### NeuroVault must not own

- recall ranking;
- query decomposition;
- retrieval planning;
- embedding-model authority;
- reranking-model authority;
- memory-domain type authority separate from `core/memory/`;
- chat orchestration;
- provider/model routing.

### Source of truth

Durable memory records must have one authoritative persistence path. Secondary indexes, caches, or derived projections may exist only as rebuildable projections behind adapters.

The current durable source of truth is PostgreSQL-backed memory state. Redis is not a durable source of truth for long-term memory.

## Memory Classes

Memory classes describe semantics, not storage products.

### STM

Short-horizon continuity such as recent context, active goals, session state, and bounded working memory.

### Episodic

Events and interactions: what happened, when it happened, what decision was made, and what outcome followed.

### Semantic / LTM

Durable facts, preferences, relationships, stable knowledge, and curated assertions.

### Procedural

Learned procedures, successful workflows, tool-use lessons, and reusable execution knowledge.

These classes must not be hard-bound to a particular database technology.

## Temporal and Provenance Requirements

Durable memory should preserve temporal validity rather than only creation time. Where applicable, contracts should support concepts such as:

- `observed_at`
- `valid_from`
- `valid_until`
- `last_verified_at`
- `superseded_at`
- `supersedes_id`
- `contradicts_id`

Durable memory should also preserve provenance such as:

- source type and source ID;
- conversation/message IDs;
- agent or tool origin;
- extraction capability/version;
- evidence references;
- explicit vs inferred origin;
- confidence;
- correlation/request identifiers.

## Migration Direction

The current repository contains overlapping legacy surfaces. Convergence should preserve useful behavior while eliminating duplicate authority.

### Production recall

Useful retrieval behavior from legacy `core/recall/`, legacy retrieval managers, and related recall helpers should converge behind canonical `core/memory/retrieval/` contracts and the NeuroRecall service. After reference migration, duplicate recall authorities should be retired.

### NeuroRecall labs harness

The current `core/neuro_recall/` package documents itself as a labs/research harness. That research capability should remain non-production and should eventually move under an explicit labs/evaluation owner rather than occupy a competing runtime namespace.

### Legacy NeuroVault monolith

The current `core/neuro_vault/` package should not remain a second complete memory system. Preserve any stronger governance, retention, privacy, recovery, or audit behavior by migrating it into canonical memory contracts and platform persistence adapters. Retire duplicate memory types, retrieval logic, fake/compatibility ML components, and alternate runtime authority after consumers are migrated.

## Forbidden Architecture

Do not introduce:

- another top-level recall authority;
- another independent memory runtime;
- vendor-specific storage assumptions in Core contracts;
- hidden fallback from one memory authority to another;
- direct database access from NeuroRecall;
- retrieval/ranking logic inside NeuroVault;
- durable writes that bypass NeuroVault governance;
- fake model implementations presented as real ML capabilities;
- cross-tenant recall or persistence fallback;
- silent memory-save success when persistence failed.

## Target Package Direction

```text
core/memory/
    runtime/
    contracts/
    stm/
    episodic/
    semantic/
    procedural/
    retrieval/
        neuro_recall.py
        activation.py
        planner.py
        fusion.py
        reranking.py
        temporal.py
        explanation.py
    writeback/
        extraction.py
        eligibility.py
        promotion.py
        contradiction.py
    ports/
        persistence.py
        cache.py
        retrieval.py
        vault.py

platform/memory/
    postgres/
    redis/
    neuro_vault/
        retention.py
        deletion.py
        backup.py
        restore.py
        governance.py

labs/memory/
    neuro_recall/
    benchmarks/
    evaluation/
```

Exact folders should only be created when implementation work requires them. Extend existing canonical modules first and avoid directory churn for naming alone.

## Architectural Invariants

1. `core/memory/` is the single memory domain authority.
2. `MemoryRuntimeManager` orchestrates memory subsystem execution.
3. NeuroRecall retrieves and ranks; it never owns durable persistence.
4. NeuroVault governs durable persistence; it never decides recall.
5. PostgreSQL is the current durable memory backend through adapters.
6. Redis is bounded/session infrastructure, not the long-term source of truth.
7. Milvus and Elasticsearch are not current dependencies or architectural assumptions.
8. Tenant scope is explicit and fail-closed.
9. Memory writes are auditable and truthfully report persistence failure.
10. Vendor/backend changes occur behind ports and configuration, not by changing Core authority.

## Proof Expectations

Any convergence change should include, as applicable:

- repository-wide reference audit before deletion;
- unit tests for recall scope and ranking behavior;
- tenant-isolation tests;
- memory write/persistence tests;
- retention/deletion tests;
- degraded-mode tests;
- architecture tests preventing duplicate recall or vault authority;
- import/compile checks;
- telemetry assertions for recall and durable write paths.

Recommended baseline commands:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

## Final Boundary

```text
MemoryRuntimeManager orchestrates memory.
NeuroRecall decides what memory to retrieve.
NeuroVault governs how approved memory becomes and remains durable.
PostgreSQL and Redis are adapters, not architectural authorities.
```
