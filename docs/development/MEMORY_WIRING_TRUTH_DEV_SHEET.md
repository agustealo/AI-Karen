# MEMORY-WIRING-TRUTH Developer Sheet

> **Status:** READY FOR EXECUTION
> **Priority:** P0 architecture correction before MEMORY-GRAPH-2 implementation
> **Scope:** memory recall composition, retired dependency cleanup, graph ownership, associative-memory wiring, PostgreSQL/Supabase graph path, tests, telemetry
> **Authority:** `PROJECT_DEV_MANIFEST.md`, `docs/development/MEMORY.md`
> **Core rule:** Fix authority and runtime truth before adding graph sophistication or dependencies.

---

## 1. Objective

Collapse the current memory read path into one coherent, test-proven architecture before implementing the temporal cognitive graph.

The sprint must prove:

1. one canonical memory runtime owner;
2. one recall-policy owner: NeuroRecall;
3. candidate sources do not perform competing global fusion/ranking;
4. retired Kuzu/Redis dependency paths are removed, replaced, or explicitly classified;
5. graph state is represented through PostgreSQL/Supabase-compatible canonical data paths;
6. existing KAREN spreading activation is reused rather than duplicated;
7. no new graph/database/queue dependency is introduced without benchmark-backed need;
8. tenant, provenance, degradation, audit, and telemetry contracts remain intact.

This sprint precedes the implementation phases in `MEMORY_GRAPH_DEV_SHEET.md`.

---

## 2. Live findings that triggered this sprint

### MWT-F01 — Runtime dependency truth conflicts with active memory imports

`requirements.txt` records `kuzu`, `redis/fakeredis`, `neo4j`, `duckdb`, `sqlalchemy`, `asyncpg`, and `hnswlib` as retired.

Active memory retrieval still imports:

- `get_leangraph_service()`;
- the deprecated `core.memory.redis_connection_manager` compatibility shim.

The Kuzu-named adapter is also not a real Kuzu persistence implementation.

**Risk:** runtime behavior and dependency policy disagree; developers may re-add retired packages to satisfy legacy imports and accidentally resurrect dead architecture.

**Required outcome:** live imports match the canonical dependency policy.

### MWT-F02 — NeuroRecall and HybridRetrievalRouter overlap retrieval authority

`MemoryRuntimeManager` composes:

- `PostgresRecallRetriever`;
- `HybridRetrievalRouter`;

under NeuroRecall.

`HybridRetrievalRouter` then performs its own source selection, reciprocal-rank fusion, guardrails, blended scoring, and reranking before NeuroRecall receives the results and performs another cross-retriever selection/sort.

**Risk:** duplicate recall policy, inconsistent scoring domains, difficult observability, and split responsibility.

**Required outcome:** NeuroRecall owns cross-source recall strategy/fusion/ranking/abstention. Candidate retrievers own only bounded candidate generation and retrieval-local scoring.

### MWT-F03 — Several router candidate sources are placeholders

Current router surfaces include:

- `lexical = []`;
- `_query_profile() -> []`;
- `_query_procedural() -> []`.

Graph lookup effectively uses the full query text as an entity lookup key.

**Risk:** architecture appears broader than actual capability and hides which retrieval paths are real.

**Required outcome:** either wire a real canonical source or remove the placeholder from production composition.

### MWT-F04 — Existing spreading activation already provides associative traversal

`core/memory/associative/spreading_activation.py` implements bounded activation propagation and an in-memory `AssociationGraph`.

**Risk:** adding NetworkX now would duplicate an existing capability before proving that implementation insufficient.

**Required outcome:** keep one associative algorithm contract and remove duplicate graph state from `AssociationGraph` by feeding bounded neighborhoods from the canonical graph repository.

### MWT-F05 — AssociationGraph duplicates graph state

The associative subsystem owns separate dictionaries for nodes, edges, and concept indexes.

**Risk:** temporal truth, deletion, tenant isolation, and graph projection can diverge from the associative graph.

**Required outcome:** associative computation consumes graph neighborhoods/candidates; it does not maintain a second authoritative graph.

### MWT-F06 — Memory sophistication is ahead of storage/wiring truth

The repo contains consolidation, activation, graph, procedural, episodic, prospective, reflection, and projection concepts, but the graph persistence and candidate plumbing are incomplete.

**Risk:** adding more cognitive features increases breadth without integration.

**Required outcome:** prove the minimal memory loop end to end before widening ontology or algorithms.

---

## 3. Canonical target after this sprint

```text
CORTEX
  |
  | recall eligibility / scope / depth hints
  v
Runtime / MemoryRuntimeManager
  |
  v
NeuroRecall                         <- ONE recall-policy authority
  |
  +--> Postgres semantic/episodic candidates
  +--> Postgres graph candidates
  +--> profile candidates            only when real
  +--> procedural candidates         only when real
  +--> bounded associative expansion using existing KAREN algorithm
  |
  v
NeuroRecall fusion / rank / guard / abstain
  |
  v
Prompt/context assembly

write side
Runtime
  |
  v
memory candidate policy
  |
  v
NeuroVault
  |
  v
PostgreSQL/Supabase canonical memory
  |
  +--> graph projection in the same canonical durable substrate
```

No candidate source becomes a second recall router.

---

## 4. Technology decision for this sprint

### Keep

- PostgreSQL/Supabase as canonical durable memory;
- existing `psycopg` data path;
- pgvector where already enabled/configured for semantic retrieval;
- PostgreSQL relational graph tables;
- recursive CTEs for bounded graph traversal;
- PostgreSQL RLS/tenant constraints;
- pg_trgm only when entity-resolution work begins;
- pgTAP where available for database-level invariants;
- existing KAREN spreading activation.

### Defer

- `pg_cron` until a concrete recurring consolidation/maintenance workload needs DB scheduling;
- durable queueing until retry/backpressure/restart-survival requirements are demonstrated;
- Personalized PageRank implementation until existing spreading activation is benchmarked.

### Do not add in this sprint

- NetworkX;
- pgmq client/runtime dependency;
- Kuzu;
- Neo4j;
- Memgraph;
- FalkorDB;
- Graphiti;
- Mem0;
- Apache AGE client dependencies;
- Elasticsearch/Milvus;
- another vector DB;
- another memory manager/facade/router.

---

# Phase 1 — AUTHORITY-COLLAPSE

## Task 1.1 — Map every production memory read path

### Do

Trace all imports/callers of:

- `MemoryRuntimeManager`;
- `NeuroRecall`;
- `HybridRetrievalRouter`;
- `PostgresRecallRetriever`;
- `get_retrieval_router`;
- `get_leangraph_service`;
- Redis memory shims/managers;
- associative spreading activation;
- direct repository/database reads used for recall.

For each path classify:

- canonical;
- candidate source;
- compatibility shim;
- misplaced policy;
- duplicate;
- dead/unused;
- test-only.

### Avoid

- adding adapters before ownership is known;
- deleting security or tenant checks;
- keeping duplicate routes “for compatibility” without a sunset.

### Proof

```bash
git grep -n "MemoryRuntimeManager"
git grep -n "NeuroRecall"
git grep -n "HybridRetrievalRouter"
git grep -n "PostgresRecallRetriever"
git grep -n "get_retrieval_router"
git grep -n "get_leangraph_service"
git grep -n "redis_connection_manager"
git grep -n "SpreadingActivation"
```

Produce a short ownership table in the implementation PR/commit notes.

---

## Task 1.2 — Make NeuroRecall the only cross-source recall policy

### Do

Refactor retrievers so each returns bounded candidates with retrieval-local metadata only.

Move/centralize under NeuroRecall or its canonical policy collaborators:

- cross-source fusion;
- duplicate resolution;
- global guardrail disposition where appropriate;
- final cross-source reranking;
- recall budget enforcement;
- recall abstention/degradation disposition;
- final provenance selection.

Candidate retrievers may expose:

- local similarity;
- local path/activation score;
- temporal validity;
- source confidence/provenance;
- retrieval reason.

They must not decide final recall disposition.

### Files

Likely:

- `src/ai_karen_engine/core/memory/retrieval/neuro_recall.py`
- `src/ai_karen_engine/core/memory/retrieval/retrieval_router.py`
- `src/ai_karen_engine/core/memory/retrieval/fusion.py`
- `src/ai_karen_engine/core/memory/retrieval/rerank.py`
- relevant tests.

### Proof

- one test where two candidate sources conflict and NeuroRecall owns final order;
- one partial-source-failure test;
- one tenant-mismatch rejection test;
- one duplicate-memory-source test;
- one empty-source abstention/degraded test;
- architecture grep showing no second cross-source fusion owner.

---

## Task 1.3 — Remove fake production candidate sources

### Do

For `lexical`, `profile`, and `procedural` paths:

- wire the existing canonical implementation if one already exists;
- otherwise remove/disable the production source until implemented;
- report unavailable capability honestly in metadata/telemetry when relevant.

### Avoid

- empty placeholder functions that make telemetry claim the source was operational;
- mock candidate data in production;
- implementing a new store to fill the placeholder.

### Proof

- source list in telemetry matches actually queried sources;
- no zero-value placeholder source is advertised as functional.

---

# Phase 2 — DEPENDENCY-AND-GRAPH-TRUTH

## Task 2.1 — Remove retired dependency resurrection paths

### Do

Audit and correct active imports that imply retired dependencies.

For Redis:

- determine whether platform Redis remains an intentionally optional ephemeral runtime capability despite removal from root requirements;
- if not required, remove it from production memory recall;
- if required elsewhere through an optional deployment extra, document/package it through the correct optional boundary rather than silently re-adding to root requirements.

For Kuzu:

- stop instantiating or naming a Kuzu backend in production graph composition;
- classify `kuzu_adapter.py` as replaced/dead or test/compatibility code;
- do not re-add `kuzu` package.

### Proof

```bash
git grep -n "import redis\|from redis"
git grep -n "KuzuGraphAdapter"
git grep -n "KARI_GRAPH_BACKEND"
git grep -n "kuzu"
```

- import check passes without retired packages;
- production startup does not claim a backend that is not present.

---

## Task 2.2 — Introduce canonical PostgreSQL graph repository

### Objective

Use the existing PostgreSQL/Supabase data layer for graph relationships rather than creating another memory store.

### Do

Create/complete one `GraphRepository` interface with a PostgreSQL implementation supporting:

- scoped node upsert/read;
- scoped edge upsert/read;
- deterministic stable IDs;
- provenance/source IDs;
- lifecycle state;
- temporal fields needed by the next graph sprint;
- bounded 1/2/3-hop traversal;
- relationship allow/deny filtering;
- cycle protection;
- result/path metadata;
- deletion/tombstone respect.

Reuse canonical Postgres session/connection/config services already in the repo. Do not instantiate a new DB pool or config authority inside graph code.

### Minimum relational shape

Use existing tables if equivalent structures already exist. Only add migrations after reference/schema audit proves no canonical table can be extended.

Conceptually required:

```text
memory_graph_nodes
  id
  tenant_id
  user_id / scope
  node_type
  source_memory_id
  lifecycle_state
  provenance
  created/updated temporal metadata

memory_graph_edges
  id
  tenant_id
  user_id / scope
  from_node_id
  to_node_id
  relationship_type
  weight
  source_memory_id
  lifecycle_state
  temporal/provenance metadata
```

Exact schema must reuse project-wide UUID/time/confidence/lifecycle conventions.

### Avoid

- graph database dependency;
- separate DB URL/config;
- implicit `tenant_id="default"`;
- storage fallback to Python dicts in production;
- arbitrary JSON for fields already covered by canonical typed columns/contracts.

### Proof

- write -> close connection/process simulation -> read;
- 1-hop, 2-hop, 3-hop fixtures;
- cycle fixture;
- cross-tenant traversal negative test;
- deleted/quarantined source exclusion;
- deterministic rebuild/idempotence test.

---

## Task 2.3 — Collapse LeanGraph naming and service ownership

### Do

Decide whether `LeanGraphService` has useful orchestration behavior.

Preferred outcome:

- keep one small `MemoryGraphService` only if a domain service is needed above `GraphRepository` for projection/query contracts;
- otherwise let canonical graph projection/query services use the repository directly through typed interfaces.

If renamed/replaced:

- update all imports;
- remove stale aliases after compatibility audit;
- delete dead Kuzu/Memgraph adapter stubs when references are zero;
- update env examples/docs.

### Proof

```bash
git grep -n "LeanGraphService"
git grep -n "leangraph"
git grep -n "KARI_GRAPH_"
```

No misleading backend name remains in production telemetry.

---

# Phase 3 — ASSOCIATIVE-INTEGRATION

## Task 3.1 — Reuse KAREN spreading activation against canonical graph neighborhoods

### Do

Refactor `SpreadingActivation` so graph state is supplied through a bounded neighborhood/candidate contract rather than a separately maintained `AssociationGraph` dictionary.

Target:

```text
query cues
  -> canonical entity/candidate lookup
  -> GraphRepository bounded neighborhood
  -> SpreadingActivation
  -> associative candidate scores + paths
  -> NeuroRecall
```

Preserve:

- activation decay;
- max propagation depth;
- bounded runtime;
- explainable activated paths.

Improve only where tests justify:

- relationship-specific weights;
- temporal validity multiplier;
- stale/contradiction inhibition;
- salience/importance weight;
- depth penalty.

### Avoid

- NetworkX dependency;
- second graph state;
- treating activation strength as confidence/truth;
- letting spreading activation choose final recall results.

### Proof

- indirect cue retrieves a relevant memory vector-only misses;
- stale/invalid relation is suppressed;
- dense/cyclic fixture stays within visit/depth budget;
- activation score is distinct from confidence;
- tenant filter applies to every traversed candidate.

---

## Task 3.2 — Establish the benchmark gate for external graph compute

Before adding NetworkX or another compute library, record benchmarks for KAREN's implementation.

Measure at minimum:

- graph neighborhood sizes: 100, 1k, 10k relevant nodes where practical;
- depth 1/2/3;
- sparse vs dense local neighborhood;
- latency p50/p95;
- memory use;
- candidate precision/recall on indirect-cue fixtures;
- effect on final task/answer quality.

An external graph-compute dependency may be proposed only if it demonstrates a meaningful improvement that exceeds dependency/maintenance cost.

ADR required before addition.

---

# Phase 4 — HANDOFF TO MEMORY-GRAPH-2

After this sprint passes, continue the existing memory-graph plan in this order:

1. bi-temporal assertions/relations;
2. entity identity + aliases + ambiguity;
3. epistemic separation;
4. pattern separation/completion;
5. experience graph;
6. consolidation/reconsolidation;
7. adaptive forgetting;
8. memory-to-behavior transfer benchmarks.

Do not begin those features while recall/storage authority is still duplicated.

---

## 5. Security/RBAC invariants

Every change must preserve or strengthen:

- mandatory tenant scope;
- user/workspace/project scope where applicable;
- no cross-tenant graph traversal;
- no cross-tenant entity resolution;
- deletion/quarantine lifecycle before candidate return;
- governed write path through Runtime/memory policy/NeuroVault;
- audit for destructive lifecycle or graph rebuild/migration operations;
- no secrets/tokens projected into graph logs;
- no graph or recall fallback that bypasses policy because a preferred source failed.

Critical tests:

- malicious cross-tenant node ID;
- cross-tenant edge attempt;
- alias collision across tenants;
- deleted source still referenced by graph;
- partial retriever failure cannot leak unscoped candidates.

---

## 6. Observability requirements

Keep structured memory events and add/standardize only where needed.

Required fields where applicable:

```text
correlation_id
request_id
tenant_id
user_id
conversation_id
recall_source
candidate_source
candidate_count
selected_count
retriever_count
failed_retriever_count
graph_depth
graph_visited_nodes
graph_visited_edges
activation_mode
latency_ms
degraded_mode
degradation_reason
status
error_type
error_code
```

Do not create a second metrics registry.

Telemetry must report actual queried sources, not configured-but-empty placeholders.

---

## 7. Files to audit/touch

Primary:

- `requirements.txt`
- `src/ai_karen_engine/core/memory/memory_runtime_manager.py`
- `src/ai_karen_engine/core/memory/retrieval/neuro_recall.py`
- `src/ai_karen_engine/core/memory/retrieval/retrieval_router.py`
- `src/ai_karen_engine/core/memory/retrieval/fusion.py`
- `src/ai_karen_engine/core/memory/retrieval/rerank.py`
- `src/ai_karen_engine/core/memory/associative/spreading_activation.py`
- `src/ai_karen_engine/core/memory/graph/`
- `src/ai_karen_engine/platform/memory/postgres/`
- `src/ai_karen_engine/platform/memory/redis/` only for retirement/optional-capability audit
- `src/ai_karen_engine/core/memory/neuro/consolidation.py`
- NeuroVault/governed persistence path
- app/runtime composition.

Tests:

- memory consumer contract tests;
- NeuroRecall tests;
- graph tests;
- tenant/isolation tests;
- startup/import tests;
- persistence/restart tests;
- telemetry contract tests.

Docs/config:

- `docs/development/MEMORY.md`
- `docs/development/MEMORY_GRAPH_DEV_SHEET.md`
- `PROJECT_DEV_MANIFEST.md` only if an authority contract changes;
- `.env*.example` after stale graph/Redis configuration audit.

---

## 8. Proof commands

Run at minimum:

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q
```

Focused:

```bash
pytest tests/ -q -k "neuro_recall or recall"
pytest tests/ -q -k "memory and tenant"
pytest tests/ -q -k "memory and graph"
pytest tests/ -q -k "memory and persistence"
pytest tests/ -q -k "memory and telemetry"
```

Reference/dependency audit:

```bash
git grep -n "KuzuGraphAdapter"
git grep -n "LeanGraphService"
git grep -n "get_leangraph_service"
git grep -n "redis_connection_manager"
git grep -n "HybridRetrievalRouter"
git grep -n "reciprocal_rank_fusion"
git grep -n "SpreadingActivation"
git grep -n "AssociationGraph"
git grep -n "networkx\|neo4j\|kuzu\|falkordb\|memgraph\|graphiti\|mem0"
```

Deployment/config if touched:

```bash
docker compose config
```

---

## 9. Exit criteria

The sprint is complete only when:

- [ ] `requirements.txt` and live production imports agree;
- [ ] no retired dependency is silently required by canonical memory startup;
- [ ] NeuroRecall is the only cross-source recall-policy owner;
- [ ] candidate retrievers do not perform competing global fusion/ranking;
- [ ] empty placeholder sources are removed or honestly disabled;
- [ ] PostgreSQL/Supabase is the canonical graph persistence/projection path;
- [ ] no production graph state lives only in Python dictionaries;
- [ ] 1/2/3-hop traversal is real, bounded, cycle-safe, tenant-safe;
- [ ] existing spreading activation consumes canonical graph neighborhoods;
- [ ] `AssociationGraph` is no longer a second durable/authoritative graph state;
- [ ] no NetworkX/pgmq/dedicated graph DB added without ADR/benchmark;
- [ ] graph/recall failures degrade honestly;
- [ ] provenance and tenant scope survive fusion/selection;
- [ ] memory tests and architecture reference audits pass;
- [ ] MEMORY-GRAPH-2 can proceed without cementing legacy wiring.

---

## 10. Risks

### High

- deleting Redis/Kuzu-facing code before proving callers are dead;
- moving fusion policy without preserving guardrails/provenance;
- accidentally changing recall ranking behavior without regression fixtures;
- creating new PostgreSQL graph tables before auditing existing canonical schemas;
- breaking optional local/dev memory behavior while fixing production truth.

### Medium

- migration cost for graph projection;
- performance of recursive traversal under dense relationships;
- entity query quality once graph source stops exact-query-text lookup.

### Low if rules are followed

- future graph backend portability, because the repository boundary remains small;
- external graph-compute adoption later, because it stays behind associative/candidate contracts.

---

## 11. Final architecture decision

The next step is **not** to add more memory technology.

The next step is to make the memory technology already in KAREN obey one runtime path:

```text
one durable truth
one graph projection
one recall-policy owner
one associative graph state
one governed write path
```

Only after those five are proven should MEMORY-GRAPH-2 add temporal cognition, richer associations, and experience-driven memory evolution.
