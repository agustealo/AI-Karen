# MEMORY-GRAPH-2 Developer Sheet

> **Status:** READY AFTER MEMORY-FORMATION-1 / MEMORY-WIRING-TRUTH
> **Priority:** P1 temporal-associative memory hardening
> **Scope:** PostgreSQL-native graph relations, temporal state, provenance, entity resolution, bounded multi-hop traversal, associative activation, NeuroRecall graph candidates, tests, observability
> **Authority:** `docs/development/MEMORY.md`, `docs/development/MEMORY_FORMATION_1_DEV_SHEET.md`, `PROJECT_DEV_MANIFEST.md`
> **Core rule:** Redis is STM. Supabase-hosted PostgreSQL is durable memory truth. The graph is a typed relational/temporal projection over that durable truth, not another database authority.

---

## 1. Objective

Replace the current shallow/Kuzu-shaped graph projection with a production-grade **PostgreSQL-native Temporal Cognitive Memory Graph** that works with Karen's actual storage architecture:

```text
Redis STM
   -> live session context
   -> MemoryFormation
   -> NeuroVault
   -> Supabase/PostgreSQL durable memory
        -> pgvector / lexical indexes
        -> temporal assertions/state
        -> memory/entity relationship tables
        -> recursive CTE traversal
   -> NeuroRecall graph candidates
   -> existing KAREN associative activation
```

Do not introduce another graph database or graph-compute library unless benchmarks later prove Postgres insufficient.

---

## 2. Live findings

### MG-F01 — current Kuzu adapter is not durable Kuzu

The existing adapter creates a directory but keeps nodes/edges in Python memory. Treat it as legacy/test scaffolding, not production graph persistence.

### MG-F02 — current traversal is one hop

`max_depth` is accepted but not honored as a true bounded multi-hop traversal.

### MG-F03 — graph vocabulary is thin

Current graph models/edge types do not fully represent temporal state, causality, action/outcome, procedure, goal, belief, observation, provenance, aliasing, or revision.

### MG-F04 — graph recall is weakly grounded

Current graph lookup can wrap relationship dictionaries as new memory entries instead of reconstructing canonical durable source evidence.

### MG-F05 — associative logic is disconnected

KAREN already has spreading activation, but it currently maintains an independent in-memory association graph rather than consuming canonical durable graph neighborhoods.

### MG-F06 — Redis is not graph truth

Redis remains active STM/hot context. It may help seed current recall but must never be used as the sole owner of durable graph edges or long-term entity relationships.

---

## 3. Physical storage target

Use Supabase-hosted PostgreSQL through Karen's canonical PostgresEngine/session path.

Do not create a direct Supabase SDK graph repository.

Recommended minimal durable structures:

```text
memory_edges
entity_aliases
```

Add dedicated tables only when a first-class domain concept cannot be represented safely by canonical memory/event tables plus typed relationships.

### `memory_edges` concept

```text
id
source_id
target_id
relationship_type
tenant_id
user_id
conversation_id? / project_id? / workspace_id?
valid_from
valid_to
observed_at
recorded_at
confidence
weight
salience
source_memory_id
source_event_id
lifecycle_state
metadata/version fields only where truly necessary
```

Requirements:

- canonical source/target IDs reference governed records;
- no duplicated full memory text;
- tenant/user scope mandatory;
- foreign keys where compatible with canonical schemas;
- indexes for source, target, relationship, scope, and temporal validity;
- migration-owned schema;
- deterministic rebuild from canonical durable memory where practical.

### `entity_aliases` concept

```text
alias_id
entity_id
tenant_id
user_id?
normalized_alias
alias_type
confidence
source_memory_id
valid_from
valid_to
lifecycle_state
```

Opaque stable entity IDs only. Do not derive canonical identity from lowercase display text.

---

## 4. Relationship ontology

Keep bounded and registry-driven.

### Identity

- SAME_AS
- ALIAS_OF
- REFERS_TO

### Context/occurrence

- MENTIONS
- PARTICIPATED_IN
- OCCURRED_IN
- BELONGS_TO

### Temporal

- PRECEDES
- FOLLOWS
- OVERLAPS
- SUPERSEDES

### Evidence/epistemic

- ASSERTS
- OBSERVED_FROM
- SUPPORTED_BY
- CONTRADICTS
- REINFORCES
- DERIVED_FROM

### Causal/experience

- CAUSED
- CONTRIBUTED_TO
- RESULTED_IN
- ATTEMPTED_FOR
- FAILED_BECAUSE
- SUCCEEDED_WITH
- LEARNED_FROM

### Task/procedure

- PURSUED_GOAL
- USED_PROCEDURE
- REQUIRES
- DEPENDS_ON
- APPLIES_TO

Do not add free-form edge labels outside the registry without schema/test updates.

---

## 5. Temporal contract

Required fields for mutable truth/relationships:

```text
valid_from
valid_to
observed_at
recorded_at
invalidated_at? / lifecycle_state
source_memory_id
source_event_id
confidence
schema_version
```

Semantics:

- `valid_*` = represented world time;
- `observed_at` = when Karen/user/system learned it;
- `recorded_at` = persistence time;
- superseded facts remain historically queryable;
- unknown times stay unknown;
- use canonical timezone-aware temporal types.

---

## 6. PostgreSQL traversal

Start with native recursive CTE traversal.

Requirements:

- enforce max depth;
- scope-filter every expansion;
- cycle prevention;
- fan-out cap;
- total visited node/edge cap;
- relationship allow/deny lists;
- path-length penalty;
- temporal-as-of filtering;
- explainable path output;
- timeout/budget handling.

Target initial depth: 1-4 hops depending on recall plan and budget.

Do not add AGE, FalkorDB, Memgraph, Neo4j, or NetworkX merely to get multi-hop traversal.

---

## 7. Entity resolution

One canonical `EntityResolver` under the memory graph domain.

Pipeline:

```text
raw mention
 -> normalization
 -> exact canonical/alias lookup in Postgres
 -> pg_trgm / lexical candidates where approved
 -> pgvector semantic candidates where available
 -> contextual disambiguation
 -> confidence gate
 -> existing entity | new entity | ambiguous/abstain
```

Requirements:

- tenant scope mandatory;
- project/workspace context participates where useful;
- merges are auditable/reversible;
- splits preserve provenance;
- uncertain identity never silently merges.

---

## 8. Graph candidate contract for NeuroRecall

Input:

```text
scope
query cues/entities
current goal/action cues
as_of / temporal constraints
allowed memory classes
max_depth
candidate budget
relationship filters
```

Output:

```text
source_memory_ids
source_event_ids
graph_path
relationship_types
depth
local_graph_score
temporal_validity
scope_match
confidence/provenance metadata
```

The graph does not return invented pseudo-memory text.

NeuroRecall owns final candidate fusion, ranking, contradiction handling, diversity, budget packing, and abstention.

---

## 9. Associative activation

Reuse existing KAREN spreading activation first.

Refactor it so that:

```text
Postgres graph neighborhood
   -> AssociationGraph-compatible bounded view
   -> spreading activation
   -> source-local associative score
   -> NeuroRecall
```

The in-memory `AssociationGraph` becomes a bounded compute view, not an independent memory store.

Fix existing correctness/type issues before extension.

Score features may include:

```text
edge weight
x temporal validity
x recency/decay
x source confidence
x salience
x transfer utility
x depth penalty
x scope match
```

Activation score is separate from truth confidence.

Benchmark existing spreading activation before considering Personalized PageRank or NetworkX.

---

## 10. Redis integration

Redis participates only as current-context seed data.

Examples:

- active session entity cues;
- current project/task/goal cues;
- recent unresolved episode ID;
- short-term salience/context.

Possible flow:

```text
Redis STM cues
 + durable Postgres semantic candidates
 + durable Postgres graph traversal
 -> NeuroRecall fusion
```

Redis must not persist durable graph edges or act as long-term graph recovery source.

Redis outage should degrade STM/current-context richness while durable graph recall remains available from Postgres.

---

## 11. Experience graph

Durable experience relationships should support:

```text
Goal
 -> Plan/Strategy
 -> Actions
 -> Tools/Models
 -> Environment/State
 -> Outcome
 -> Success/Failure
 -> Lesson/Procedure
 -> Transfer evidence
```

Examples Karen must eventually handle:

- what failed last time this project was deployed;
- what tool caused repeated failures;
- what strategy succeeded for this class of task;
- what changed since the prior attempt;
- what prior outcome should change the current plan.

Procedure/lesson promotion remains a consolidation + NeuroVault decision, not a graph-side write heuristic.

---

## 12. Implementation phases

### Phase 1 — POSTGRES-GRAPH-TRUTH

Objective: replace fake/ephemeral graph persistence with truthful Postgres-native graph relations.

Do:

- typed edge/temporal/provenance contracts;
- migration-owned relationship tables;
- Postgres graph repository adapter;
- bounded recursive traversal;
- tenant/user scope enforcement;
- graph rebuild path;
- retire Kuzu production default/claims;
- keep in-memory adapter only for explicit tests/dev.

Proof:

- write -> process restart -> read;
- 1/2/3/4-hop traversal correctness;
- no cross-tenant traversal;
- as-of temporal query correctness;
- graph source IDs resolve to canonical durable memory.

### Phase 2 — ENTITY + PROVENANCE

Do:

- entity alias/resolution pipeline;
- canonical source refs;
- reverse provenance expansion;
- contradiction/reinforcement/supersession;
- point-in-time current vs historical truth.

Proof:

- alias resolution;
- same-name ambiguity abstains;
- historical fact remains recallable after supersession;
- graph candidate reconstructs original durable evidence.

### Phase 3 — ASSOCIATIVE + EXPERIENCE

Do:

- feed Postgres neighborhoods to existing spreading activation;
- benchmark activation benefit;
- connect goal/action/outcome/procedure relations;
- test pattern separation/completion;
- record transfer utility when prior experience changes later action.

Proof:

- useful recall improves versus semantic-only baseline;
- prior failed strategy is avoided later;
- prior successful procedure transfers later;
- no separate associative truth store remains.

---

## 13. Dependency policy

Do not add during MEMORY-GRAPH-2:

- NetworkX;
- pgmq;
- Kuzu;
- Neo4j;
- Memgraph;
- FalkorDB;
- Graphiti;
- Mem0;
- Apache AGE clients;
- Elasticsearch;
- Milvus;
- another vector store.

Allowed existing/native capabilities:

- Redis through canonical platform adapter for STM;
- canonical SQLAlchemy/PostgresEngine path;
- Supabase-hosted PostgreSQL;
- pgvector;
- PostgreSQL FTS;
- pg_trgm where approved;
- recursive CTEs;
- RLS;
- pgTAP where useful.

Any future graph-compute/storage dependency requires a benchmark-backed ADR proving a real bottleneck under Karen workloads.

---

## 14. Security / RBAC

Prove:

- tenant/user scope on every graph insert/query/traversal;
- source references cannot cross tenant boundaries;
- Redis cues cannot widen durable recall scope;
- deletion/retention propagates into graph projections;
- invalid/quarantined source evidence cannot re-enter through graph paths;
- entity merge/split actions are auditable;
- no secret/raw hidden reasoning is persisted.

---

## 15. Observability

Emit structured graph events with:

```text
correlation_id
request_id
tenant_id
user_id
session_id
conversation_id
graph_operation
source_memory_id
source_event_id
relationship_types
max_depth
visited_count
candidate_count
latency_ms
postgres_degraded
redis_degraded
status
error_type/code
```

Required event families:

```text
memory.graph.projection.started/completed/failed
memory.graph.traversal.started/completed/abstained
memory.graph.entity_resolution.completed/conflict
memory.graph.supersession.completed
memory.graph.rebuild.completed/failed
memory.graph.associative_activation.completed
```

---

## 16. Exit criteria

MEMORY-GRAPH-2 is complete only when:

- graph persistence is PostgreSQL-native or explicitly justified otherwise by ADR;
- graph survives process restart;
- graph uses canonical durable IDs/provenance;
- recursive multi-hop traversal is real and bounded;
- temporal as-of queries work;
- entity aliases/ambiguity are safe;
- graph candidates reconstruct canonical durable evidence;
- existing spreading activation consumes canonical graph neighborhoods;
- Redis participates only as bounded current-context seed data;
- NeuroRecall remains final recall-policy authority;
- experience graph demonstrably improves later behavior;
- tenant isolation and deletion propagation are test-proven;
- no second durable memory authority exists.

---

## 17. Proof commands

```text
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Plus targeted:

- Redis STM + degraded-mode tests;
- Postgres graph repository tests;
- Supabase migration contract tests;
- recursive CTE traversal tests;
- temporal point-in-time tests;
- entity resolution tests;
- provenance reconstruction tests;
- NeuroRecall graph-fusion tests;
- associative-memory behavioral tests;
- tenant/RBAC tests.