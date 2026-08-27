# Unified Memory System - AI Karen

**Status:** Active canonical Core memory domain  
**Architecture:** Local-first, adapter-driven, tenant-scoped, auditable

## Purpose

`ai_karen_engine.core.memory` is the single Core authority for memory semantics,
contracts, subsystem orchestration, recall coordination, and memory writeback
policy.

The memory system is backend-neutral at the Core boundary. Runtime composes
platform implementations behind Core contracts. Core memory code must not
construct Redis/PostgreSQL clients or embed backend-specific persistence logic.

For the detailed NeuroRecall/NeuroVault ownership model, see
[NEURO_MEMORY_ARCHITECTURE.md](./NEURO_MEMORY_ARCHITECTURE.md).

## Current Backend Truth

- **Redis** is the current physical backing for bounded/session STM through
  `STMPort` and `RedisSTMAdapter`.
- **Supabase-hosted PostgreSQL** is the durable memory source of truth.
- **SQLAlchemy/PostgresEngine** owns canonical PostgreSQL engine/session
  lifecycle.
- **pgvector/PostgreSQL-native indexes** provide durable semantic/search
  capabilities where enabled.
- Milvus and Elasticsearch are not part of the current canonical memory runtime.

Backends remain config-driven and replaceable behind ports/adapters.

## Authority Model

```text
ChatRuntime
    |
    v
MemoryRuntimeManager
    |----------------------------------|
    |                                  |
    v                                  v
NeuroRecall                       MemoryFormationService
recall intelligence                    |
    |                                  v
    |                              NeuroVault
    |                         governed durability
    |                                  |
    |                                  v
    |                         Supabase/PostgreSQL
    |
    +-- candidate sources
          |
          +-- STMPort ----------> RedisSTMAdapter -> Redis
          +-- Postgres retrievers
          +-- graph/event/entity source ports
```

`MemoryRuntimeManager` is the explicit dependency-composition boundary for the
memory subsystem. Core retrieval/projection components receive contracts;
Runtime wires platform implementations.

## Memory Layers

### STM

STM owns bounded cross-request continuity such as:

- recent context;
- active episode;
- active goal;
- active project;
- bounded working state;
- tool state where explicitly required by runtime execution.

Canonical STM contract:

```text
core/memory/stm
    -> STMPort
    -> STMScope
    -> STMSlot
```

Current physical backing:

```text
STMPort
    -> RedisSTMAdapter
    -> RedisConnectionManager
    -> Redis
```

Redis is infrastructure, not the semantic owner of STM.

Active memory-domain code must not bypass `STMPort` through legacy
`set_short_term/get_short_term/set_session/get_session` helpers. Those methods
remain compatibility surfaces until repository-wide reference proof permits
retirement.

STM is session-scoped. A durable event without a session must not create
synthetic user-global STM.

### Episodic

Episodic memory owns event/experience boundaries, outcomes, temporal grouping,
and provenance. Active episode continuity may be represented in STM, while
committed episode/event history remains durable PostgreSQL truth.

### Semantic / LTM

Durable facts, preferences, relationships, stable knowledge, and curated
assertions live in PostgreSQL and may use pgvector/lexical indexes as derived
retrieval capabilities.

### Procedural

Learned procedures, successful workflows, tool-use lessons, and reusable
execution knowledge are durable PostgreSQL-backed memory with canonical event
provenance.

## Recall Authority

NeuroRecall is the sole final recall authority. Candidate-source components may
activate and retrieve bounded candidates, but they must not independently own:

- final fusion;
- guardrails;
- cross-source deduplication;
- final reranking;
- abstention/selection.

The hybrid source router is dependency-injected and backend-neutral. It consumes
`STMPort`, graph/event source contracts, and entity-resolution contracts rather
than constructing Redis/Postgres implementations.

STM recall is typed by slot. `TOOL_STATE` is not automatically converted into a
memory candidate.

## Durable Write Authority

The intended durable path is:

```text
interaction
    -> MemoryFormationService
    -> worthiness / policy / tenant / consent gates
    -> NeuroVault
    -> PostgreSQL durable commit
    -> rebuildable projections
```

A durable commit happens before derived projections. Projection failure may
produce degraded status but must never erase the truth that durable persistence
succeeded.

Current rebuildable projections include:

- bounded STM recent-context projection through `STMPort`;
- canonical memory graph projection.

Core projection coordination is backend-neutral. Runtime injects concrete
workers/adapters.

## Tenant and Security Invariants

- Trusted memory scope requires explicit tenant and user identity.
- The literal tenant value `default` is forbidden as trusted runtime/memory
  scope.
- Authentication tokens and trusted principals must carry explicit non-default
  tenant scope.
- Anonymous/public requests carry no trusted tenant rather than a manufactured
  default tenant.
- Development auth bypass requires explicit `KAREN_DEV_TENANT_ID`.
- No cross-tenant recall, persistence, graph traversal, or degraded fallback is
  permitted.

## Configuration Truth

Canonical bounded-memory runtime configuration lives in:

`src/ai_karen_engine/config/memory.py`

Current settings include:

- `MEMORY_STM_SESSION_TTL_SECONDS`
- `MEMORY_STM_MAX_SLOT_BYTES`

`core/memory/chat_memory_config.py` is legacy compatibility debt and must not be
used as a canonical Runtime/STM/recall configuration authority. It still
contains historical Redis/vector/Milvus-era settings and requires a separate
reference audit before deletion.

## Legacy Convergence

The repository still contains historical compatibility surfaces. Rules:

- extend the strongest existing owner before adding new files/services;
- do not create another STM manager, recall router, Redis manager, or memory
  persistence facade;
- no direct Redis/Postgres construction inside Core memory cognition;
- compatibility helpers remain only until reference audits prove their removal
  safe;
- retired graph/vector providers must not reappear through configuration or
  fallback logic;
- deletion requires reference audit, security review, import migration, and
  tests.

## Observability

Memory paths should emit structured, scoped events for:

- STM read/write/degraded/rejected operations;
- recall activation/source completion;
- durable persistence;
- projection success/failure/degradation;
- tenant/scope rejection;
- graph/entity resolution and traversal;
- request/correlation IDs where available.

No print-based observability and no silent broad exception fallback are allowed
on canonical paths.

## Architecture Invariants

1. `core/memory/` is the one memory-domain authority.
2. `MemoryRuntimeManager` is the memory execution/composition authority.
3. `STMPort` is the canonical bounded-memory contract.
4. Redis is an STM/platform adapter, not a cognitive authority.
5. NeuroRecall is the sole final recall-selection authority.
6. NeuroVault is the sole governed durable-mutation boundary.
7. PostgreSQL is the durable memory source of truth.
8. Core memory components do not construct physical storage clients.
9. Trusted tenant scope is explicit and fail-closed.
10. Projection/cache/index state is rebuildable and never outranks durable truth.
11. Compatibility shims have a migration path and may not become new authority.
12. Persistence and recall failures are observable and truthfully reported.

## Proof

Relevant changes should be proven with:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
```

Targeted memory proof should cover tenant isolation, STM slot scope, degraded
behavior, durable persistence, graph provenance, recall authority, projection
truth, and architecture guards preventing direct backend leaks.

## Final Boundary

```text
MemoryRuntimeManager composes and executes memory.
STM owns bounded continuity semantics.
Redis backs STM through a platform adapter.
NeuroRecall decides what memory to retrieve.
NeuroVault governs durable persistence.
PostgreSQL owns durable memory truth.
Core owns semantics; Platform owns infrastructure.
```
