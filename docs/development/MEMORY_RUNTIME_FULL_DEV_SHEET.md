# MEMORY-RUNTIME-FULL Developer Sheet

> **Status:** READY FOR EXECUTION
> **Priority:** P0 architecture closure + P1 cognitive memory hardening
> **Scope:** Redis STM, Supabase/PostgreSQL durable memory, SQLAlchemy/PostgresEngine persistence, memory formation, episodic memory, temporal graph, NeuroRecall, NeuroVault, consolidation, associative recall, security, observability, benchmarks
> **Authority:** `docs/development/MEMORY.md`, `PROJECT_DEV_MANIFEST.md`
> **Core rule:** One memory domain, one recall authority, one durable persistence authority, one STM authority, one graph projection path.

---

# 1. Objective

Bring KAREN's memory system to a proven, production-grade architecture without adding unnecessary databases or competing memory frameworks.

The target system must:

- keep Redis as bounded STM/session/working memory;
- keep Supabase-hosted PostgreSQL as canonical durable memory;
- keep SQLAlchemy/PostgresEngine as the canonical Postgres engine/session/ORM layer;
- keep NeuroRecall as recall strategy/fusion authority;
- keep NeuroVault as durable memory governance authority;
- add first-class memory formation and episodic event segmentation;
- store temporal, provenance-rich durable memories;
- represent relationships through rebuildable PostgreSQL graph projections;
- support semantic, lexical, temporal, episodic, procedural and associative recall;
- reconstruct source evidence instead of inventing pseudo-memories;
- consolidate experiences into facts, procedures, lessons and strategies;
- prove that prior experience changes future behavior;
- preserve tenant isolation, auditability, deletion, degraded-mode truth and telemetry.

Do not add another graph database, vector database, memory SaaS/framework, or graph-compute dependency until a benchmark-backed ADR proves the existing stack insufficient.

---

# 2. Canonical architecture

```text
                         CORTEX
              recall eligibility / intent / policy
                            |
                            v
                         Runtime
                            |
              +-------------+-------------+
              |                           |
              v                           v
        Redis-backed STM          Memory Formation
      current/session state     events/state/provenance
              |                           |
              |                           v
              |                       NeuroVault
              |                  governed durable write
              |                           |
              |                           v
              |                Supabase-hosted Postgres
              |                      durable truth
              |                           |
              |              +------------+------------+
              |              |            |            |
              |              v            v            v
              |          pgvector      temporal      graph
              |          semantics      state       projection
              |              |            |            |
              +--------------+------------+------------+
                             |
                             v
                         NeuroRecall
                  strategy / fusion / rank
                             |
                             v
                    prompt/context assembly
                             |
                             v
                     provider/model runtime
```

Physical persistence stack:

```text
Supabase PostgreSQL
        |
        v
PostgresEngine
SQLAlchemy engine/session authority
        |
        +-- sync SQLAlchemy -> psycopg/psycopg2
        |
        +-- async SQLAlchemy -> asyncpg (current)
```

Redis is not durable LTM. PostgreSQL is not STM. SQLAlchemy is not a second database authority. The graph is not an independent memory source of truth.

---

# 3. Canonical ownership matrix

| Responsibility | Canonical owner | Must not own |
|---|---|---|
| Current/session working memory | Redis platform adapter | durable facts, graph truth |
| Durable memory | memory domain + NeuroVault over PostgreSQL | provider routing, intent |
| DB engine/session lifecycle | `persistence/postgres/PostgresEngine` | memory policy |
| ORM/query implementation | platform/persistence repositories using SQLAlchemy | recall strategy |
| Memory formation | `core/memory` formation/episodic subsystem | final durable write authority |
| Event segmentation | `core/memory/episodic` | global intent authority |
| Recall strategy | NeuroRecall | persistence, graph mutation |
| Graph projection | `core/memory/graph` | final recall ranking |
| Associative activation | memory retrieval primitive | truth confidence |
| Durable governance | NeuroVault | CORTEX decisions |
| Intent/policy | CORTEX | database execution |
| Runtime orchestration | Runtime | duplicate storage logic |
| Schema changes | Supabase/Alembic migrations | runtime table creation |

---

# 4. Live architecture truths to preserve

## 4.1 Redis remains active

Canonical Redis implementation belongs under:

```text
src/ai_karen_engine/platform/memory/redis/
```

The old core import path is a compatibility shim and must be removed by its sunset once consumers are migrated.

Redis responsibilities:

- current conversation/session state;
- bounded recent context;
- hot summaries;
- working state;
- short-lived retrieval hints;
- TTL-governed temporary state;
- optional degraded in-process fallback when Redis is unavailable.

Redis must not become:

- canonical episodic storage;
- semantic LTM;
- durable graph storage;
- source of durable user preferences/facts;
- cross-session truth after TTL expiration.

## 4.2 SQLAlchemy remains canonical

`PostgresEngine` owns:

- sync engine;
- async engine;
- connection pooling;
- session factories;
- commit/rollback lifecycle;
- database health checks.

Do not replace SQLAlchemy merely to reduce dependency count. Direct psycopg access is allowed only behind a proven infrastructure/hot-path need and must not create a parallel repository authority.

## 4.3 Supabase means hosted Postgres + platform capabilities

Backend application code should not introduce a competing Supabase SDK repository layer for data already owned by SQLAlchemy/PostgresEngine.

Supabase provides:

- managed PostgreSQL;
- migrations/deployment path;
- RLS/platform security capabilities where configured;
- pgvector and approved Postgres extensions;
- storage/realtime/auth platform services where separately enabled.

Memory persistence remains ordinary canonical Postgres access through KAREN's data adapters.

---

# 5. Architecture defects to close first

## MR-F01 — dependency manifest drift

Redis, SQLAlchemy and asyncpg were previously marked retired despite active canonical imports.

**Action:** preserve them as active dependencies until their owning runtime paths are replaced by explicit ADR-backed changes.

## MR-F02 — deprecated Redis import path remains reachable

Consumers still importing `core.memory.redis_connection_manager` must migrate to the platform adapter.

**Action:** audit imports, update consumers, preserve shim until its declared sunset, then remove after reference proof.

## MR-F03 — recall authority is layered awkwardly

NeuroRecall is canonical, but `HybridRetrievalRouter` also performs activation, source selection, fusion, guardrails and reranking.

**Action:** define exactly which responsibilities stay in source adapters/router and which move to NeuroRecall. Final source fusion/ranking/abstention must remain NeuroRecall-owned.

## MR-F04 — lexical/profile/procedural retrieval is incomplete

Current retrieval contains empty/stub paths.

**Action:** either implement them through canonical repositories or remove false capability claims until implemented.

## MR-F05 — graph backend truth is false

Current Kuzu-named adapter is in-memory and non-durable.

**Action:** replace with Postgres graph repository/projection or explicitly named in-memory test adapter. No fake durable telemetry.

## MR-F06 — episodic formation authority is missing

`core/memory/episodic` has no real event construction system.

**Action:** create canonical event/episode contracts and deterministic-first segmentation.

## MR-F07 — graph retrieval loses provenance

Graph result dictionaries are wrapped as new pseudo-memory entries.

**Action:** graph candidates return canonical source IDs/path metadata, then NeuroRecall reconstructs original evidence.

## MR-F08 — existing spreading activation is isolated and under-hardened

Existing implementation must be corrected, scoped and integrated before adding NetworkX/PPR frameworks.

---

# 6. Target memory layers

## 6.1 STM / working memory

Backing: Redis.

Contains:

- recent messages/context summaries;
- session state;
- transient task state;
- active conversational entities;
- unresolved local goals;
- short-lived tool/workflow state.

Required properties:

- TTL;
- bounded size;
- tenant/user/session key isolation;
- explicit degraded mode;
- no fake durability claims;
- configurable retention limits.

## 6.2 Episodic memory

Backing: PostgreSQL.

Stores meaningful episodes such as:

- task attempts;
- decisions;
- failures;
- successes;
- corrections;
- commitments;
- workflow sequences;
- significant interaction events.

## 6.3 Semantic/LTM

Backing: PostgreSQL + pgvector where useful.

Stores:

- durable facts;
- preferences;
- project state;
- identities/entities;
- learned stable state;
- generalized knowledge.

## 6.4 Procedural memory

Backing: PostgreSQL.

Stores:

- successful procedures;
- reusable workflows;
- failure avoidance patterns;
- learned execution lessons;
- strategy variants with outcome evidence.

## 6.5 Prospective memory

Backing: PostgreSQL for durable intentions; Redis may cache active near-term triggers.

Stores:

- future commitments;
- deadlines;
- conditional tasks;
- deferred actions;
- unresolved promises.

---

# 7. Memory formation pipeline

```text
incoming message / action / tool result / environment observation
        |
        v
runtime observation envelope
        |
        v
MemoryFormationService
        |
        +-- EventSegmenter
        +-- ContextualStateEncoder
        +-- EpistemicClassifier
        +-- TemporalNormalizer
        +-- ProvenanceBinder
        |
        v
StructuredMemoryEvent / EpisodeFrame
        |
        v
memory policy / eligibility
        |
        v
NeuroVault
        |
        v
PostgreSQL durable commit
        |
        +-- embedding/index update
        +-- graph projection
        +-- consolidation candidate
```

Do not persist every message as durable cognition. Raw transcript/message persistence, when required for conversation history, is distinct from promotion into durable cognitive memory.

---

# 8. Structured event contract

Reuse canonical IDs/time/confidence/evidence contracts where they already exist.

Required concepts:

```text
event_id
episode_id
tenant_id
user_id
conversation_id
session_id
workspace_id / project_id where applicable

started_at
ended_at
observed_at
recorded_at
valid_from
valid_to

goal_id / contextual_intent
action_class
outcome_class
state_before_ref
state_after_ref

entities
constraints
actions
observations
outcomes
feedback
source_refs
causal_parent_ids
confidence
importance
lifecycle_state
schema_version
```

Never store hidden chain-of-thought as event content.

---

# 9. Event segmentation

Start deterministic-first.

Boundary signals:

- goal change;
- project/workspace change;
- task completion;
- success/failure outcome;
- meaningful correction;
- user decision/commitment;
- tool workflow completion;
- material environment state change;
- significant time/session boundary.

Optional model-assisted segmentation must use a versioned prompt contract and explicit budget/config gate.

Proof cases:

- multi-turn same task stays one episode;
- task switch starts another;
- correction can attach to prior episode;
- identical entities under different goals remain separate experiences;
- low-value chat does not create durable episodes.

---

# 10. Durable PostgreSQL model

Prefer extending existing canonical ledger/models rather than creating a second memory database schema.

Expected durable concepts may include:

- memory events;
- assertions;
- episodes;
- entities;
- entity aliases;
- graph relationships;
- experience/outcome records;
- procedures/lessons;
- source/provenance references.

Graph tables are projection/index structures referencing canonical source IDs, not duplicate copies of memory text.

Every durable row must preserve applicable:

- tenant_id;
- user_id;
- conversation/session/project scope;
- provenance;
- consent/privacy state;
- lifecycle state;
- created/updated timestamps;
- temporal validity where applicable.

---

# 11. Postgres graph projection

Do not add a graph database in this sprint.

Use PostgreSQL tables and recursive CTE traversal behind one `GraphRepository` interface.

Core relationship record:

```text
edge_id
tenant_id
user_id
source_id
target_id
relationship_type
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
schema_version
```

Core relationship families:

- identity/alias;
- mention/participation;
- temporal ordering;
- support/evidence/derivation;
- contradiction/correction/supersession;
- causal/contributed/resulted;
- goal/task/action/outcome;
- procedure/lesson;
- project/artifact/component.

---

# 12. Graph traversal contract

Inputs:

```text
tenant_id
user_id
seed_ids / entity cues
as_of
allowed_relationships
allowed_memory_classes
max_depth
fanout_limit
visited_budget
candidate_limit
```

Outputs:

```text
source_memory_ids
source_event_ids
graph_path
relationship_types
depth
local_graph_score
temporal_match
confidence
provenance
```

Rules:

- tenant/user filter every hop;
- bounded depth;
- cycle suppression;
- bounded fan-out;
- bounded visited count;
- explicit relationship allowlist;
- path-length penalty;
- stale/invalid edge filtering;
- no pseudo-memory creation.

---

# 13. Entity resolution

One canonical `EntityResolver` under memory graph/domain.

Pipeline:

```text
raw mention
 -> normalize
 -> exact canonical lookup
 -> alias lookup
 -> lexical candidate search
 -> semantic candidate search where needed
 -> context disambiguation
 -> confidence gate
 -> existing | new | ambiguous/abstain
```

Use PostgreSQL capabilities first:

- exact indexes;
- FTS;
- `pg_trgm` where enabled;
- pgvector where semantic disambiguation earns its cost.

Do not silently merge uncertain entities.

Entity merge/split must be auditable and reversible.

---

# 14. NeuroRecall target design

NeuroRecall owns final retrieval strategy.

Candidate sources may include:

```text
Redis STM
Postgres lexical
Postgres semantic / pgvector
Postgres episodic
Postgres temporal
Postgres graph
procedural/experience
profile/preferences
```

Target flow:

```text
RecallRequest
 -> validate tenant/user scope
 -> plan source budget
 -> query selected sources
 -> source-local scoring
 -> provenance expansion for graph/event hits
 -> contradiction/current-validity filtering
 -> dedupe
 -> fusion
 -> associative expansion where useful
 -> final rerank
 -> evidence diversity
 -> budget-aware packing / abstention
```

Source adapters return candidates. They must not independently become final recall authorities.

---

# 15. Redis + durable recall interaction

Redis should contribute current context without masking durable truth.

Example priority logic:

```text
current-session state -> Redis
historical fact       -> Postgres
stable preference     -> Postgres
active unfinished task-> Redis + durable prospective state when needed
recent correction     -> Redis immediately, Postgres after governed formation
```

Never promote Redis cache content to durable truth merely because it exists in STM.

---

# 16. Provenance reconstruction

Graph/event retrieval should reconstruct evidence from source records.

```text
graph candidate
 -> canonical source IDs
 -> bounded source fetch
 -> episode-neighbor expansion if necessary
 -> temporal ordering
 -> dedupe
 -> evidence bundle
 -> NeuroRecall final ranking
```

Every recalled durable result should be able to explain:

- where it came from;
- when it was observed;
- when it was valid;
- whether it is current/superseded;
- why it was selected;
- what graph/path/semantic cue contributed.

---

# 17. Temporal state

Use explicit world/semantic time, not only message timestamp.

Required fields where applicable:

```text
valid_from
valid_to
observed_at
recorded_at
invalidated_at
```

State update behavior:

```text
new observation
 -> compatible active state? reinforce/extend
 -> conflicting state? close prior interval + create new
 -> uncertain evidence? preserve separate observation
```

Historical facts must remain queryable after supersession.

---

# 18. Epistemic classes

Do not flatten cognition into one generic assertion class.

At minimum distinguish:

- world fact;
- observation;
- user belief;
- user preference;
- KAREN hypothesis/opinion;
- experience/outcome;
- procedure/lesson.

Truth confidence and retrieval activation are separate quantities.

---

# 19. Consolidation and abstraction

Current promotion heuristics remain useful gates but must grow into evidence-backed consolidation.

Target hierarchy:

```text
L0 raw source/reference
L1 observation/action
L2 episode
L3 semantic fact/state/preference
L4 procedure/lesson
L5 generalized strategy
```

Promotion evidence may include:

- repeated independent episodes;
- repeated successful outcomes;
- user confirmation;
- correction history;
- temporal stability;
- cross-context transfer;
- source confidence;
- contradiction count.

Do not promote solely because a memory was frequently recalled.

---

# 20. Reconsolidation / belief revision

Canonical revision decisions:

```text
UNCHANGED
STRENGTHEN
WEAKEN
REVISE
SUPERSEDE
SPLIT
QUARANTINE
```

Inputs:

- prior memory/assertion;
- new evidence;
- provenance quality;
- temporal compatibility;
- support/contradiction;
- user correction;
- observed outcome.

Revisions preserve historical state and provenance.

---

# 21. Associative memory

First harden the existing Karen spreading activation implementation.

Required behavior:

- use canonical graph neighborhoods rather than maintaining a competing graph truth;
- support typed edge weights;
- enforce tenant scope;
- respect temporal validity;
- include recency, confidence, salience and depth penalties;
- avoid cycles;
- bounded activation budget;
- return explainable paths/reasons.

Do not add NetworkX or PPR libraries until benchmark comparison proves measurable value.

Possible later benchmark:

```text
SQL bounded traversal
vs
Karen weighted spreading activation
vs
Personalized PageRank
```

---

# 22. SQLAlchemy / driver policy

Canonical rule:

> Application persistence uses SQLAlchemy through the canonical PostgresEngine/repositories. Drivers are implementation details, not parallel persistence authorities.

Current:

```text
sync  -> SQLAlchemy + psycopg/psycopg2
async -> SQLAlchemy + asyncpg
```

Future optional ADR:

Evaluate SQLAlchemy + psycopg3 for both sync and async to reduce driver duplication.

Do not change drivers during memory architecture work unless tests/benchmarks prove a problem.

Audit direct imports of:

```text
psycopg
psycopg2
asyncpg
sqlalchemy.create_engine
sqlalchemy.create_async_engine
```

Only the canonical engine layer should create engines/pools.

---

# 23. Redis authority cleanup

Tasks:

- migrate all active imports to `platform/memory/redis`;
- preserve compatibility shim until sunset;
- verify Redis package is declared in dependencies;
- centralize Redis URL/pool/TTL config;
- verify tenant/user/session key structure;
- define STM retention defaults;
- prove degraded-mode behavior;
- delete shim after reference audit and sunset criteria.

Do not remove Redis itself.

---

# 24. Supabase/Postgres migration strategy

Schema is migration-owned.

Rules:

- no runtime `create_all()` in production;
- migrations idempotent/reviewed;
- preserve existing memory ledger data;
- add graph/event structures through migration files;
- preserve RLS/tenant constraints;
- indexes added intentionally;
- extension use documented and validated per deployment.

Potential Postgres capabilities:

```text
pgvector
Postgres FTS
pg_trgm
recursive CTEs
RLS
pgTAP
```

`pg_cron` remains optional and should be introduced only when scheduled consolidation/maintenance has a proven runtime requirement.

---

# 25. Security / tenancy

Every memory operation requires explicit tenant/user scope.

Prove:

- Redis keys cannot collide across tenants/users/sessions;
- SQL queries always scope tenant/user;
- recursive traversal filters every hop;
- entity aliases cannot bridge tenants;
- graph rebuild preserves scope;
- deletion invalidates projections;
- quarantined/invalid evidence cannot re-enter through graph paths;
- secret/token values are not promoted into memory;
- no hidden reasoning is persisted;
- administrative lifecycle operations are audited.

Never use a production `tenant_id="default"` fallback.

---

# 26. Observability

Required structured event families:

```text
memory.stm.read
memory.stm.write
memory.stm.degraded
memory.formation.started/completed
memory.event.boundary_detected
memory.episode.created/extended
memory.durable.write.started/completed/failed
memory.graph.projection.started/completed/failed
memory.graph.recall.started/completed/abstained
memory.entity.resolution.started/completed/ambiguous
memory.recall.started/completed/degraded
memory.recall.provenance_expanded
memory.consolidation.decided
memory.revision.decided
memory.behavior_transfer.recorded
```

Include applicable:

- correlation_id;
- request_id;
- tenant_id;
- user_id;
- session_id;
- conversation_id;
- source IDs;
- backend;
- operation;
- candidate counts;
- traversal depth;
- latency;
- degraded mode;
- error type/code.

No raw secrets in logs.

---

# 27. Execution phases

## Phase 0 — MEMORY-WIRING-TRUTH

**Objective:** make existing memory paths honest before adding capabilities.

Do:

1. audit all Redis imports;
2. migrate canonical consumers to platform Redis adapter;
3. audit all SQLAlchemy/driver imports;
4. prove PostgresEngine is sole engine/session factory owner;
5. remove false dependency-retirement comments;
6. map NeuroRecall vs HybridRetrievalRouter responsibilities;
7. identify all Kuzu/LeanGraph references;
8. fix current spreading activation defects;
9. remove false capability claims for empty retrieval sources.

Proof:

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q

git grep -n "core.memory.redis_connection_manager"
git grep -n "create_engine\|create_async_engine"
git grep -n "psycopg\|asyncpg"
git grep -n "KuzuGraphAdapter\|LeanGraphService\|get_leangraph_service"
```

Exit:

- dependency manifest matches runtime;
- one Redis authority;
- one Postgres engine authority;
- one recall authority boundary documented/tested.

---

## Phase 1 — MEMORY-FORMATION

**Objective:** turn live interaction into structured experience.

Do:

1. implement canonical episodic contracts;
2. implement deterministic event segmentation;
3. implement contextual state cues;
4. bind exact provenance;
5. classify epistemic type;
6. normalize temporal fields;
7. persist governed episodes through NeuroVault/Postgres;
8. add tests for topic/goal/task boundaries.

Reuse:

- existing memory types/contracts;
- CORTEX goal/intent signals;
- canonical temporal/confidence authorities;
- PostgresEngine sessions.

Avoid:

- new orchestrator;
- new memory DB;
- LLM call per message;
- duplicate intent classifier.

---

## Phase 2 — POSTGRES TEMPORAL GRAPH

**Objective:** replace fake/in-memory graph persistence with durable/rebuildable Postgres projection.

Do:

1. define `GraphRepository` contract;
2. implement `PostgresGraphRepository`;
3. create migration-backed relationship tables;
4. add temporal/provenance fields;
5. add typed relationship registry;
6. implement deterministic projection/rebuild;
7. implement bounded recursive traversal;
8. return source IDs/path evidence;
9. retire Kuzu-named adapter after audit.

Avoid:

- second graph DB;
- graph-specific memory copies;
- silent in-memory production fallback.

Proof:

- write -> restart -> read;
- rebuild -> equivalent projection;
- tenant isolation every hop;
- max depth enforced;
- stale edges excluded for current-state recall.

---

## Phase 3 — RETRIEVAL CLOSURE

**Objective:** make NeuroRecall the real multi-source retrieval authority.

Do:

1. implement real lexical source;
2. implement pgvector semantic source;
3. implement episodic source;
4. implement temporal source;
5. implement graph source;
6. implement procedural/experience source;
7. define Redis STM source;
8. move final fusion/ranking/abstention into NeuroRecall;
9. implement provenance expansion;
10. add contradiction/current-validity filtering.

Proof:

- each source independently testable;
- source failures yield honest degraded metadata;
- NeuroRecall remains final selector;
- no cross-tenant candidate survives.

---

## Phase 4 — MEMORY EVOLUTION

**Objective:** turn repeated experience into learned state and procedures.

Do:

1. durative state formation;
2. consolidation across episodes;
3. belief revision;
4. contradiction/supersession;
5. procedure/lesson promotion;
6. abstraction levels;
7. forgetting/retention lifecycle;
8. deletion propagation into derived projections.

Proof:

- prior state closes when new state becomes valid;
- historical query still returns prior state;
- user correction revises rather than duplicates blindly;
- repeated success can produce procedure with evidence;
- repeated failure can produce avoidance lesson.

---

## Phase 5 — ASSOCIATIVE RECALL

**Objective:** integrate existing spreading activation with canonical graph neighborhoods.

Do:

1. fix current implementation defects;
2. remove independent graph truth from associative layer;
3. consume GraphRepository neighborhoods;
4. use weighted typed/temporal edges;
5. bound depth/fanout/activation;
6. surface explanation metadata;
7. feed associative score into NeuroRecall without treating it as confidence.

Benchmark before any NetworkX/PPR dependency.

---

## Phase 6 — BEHAVIORAL PROOF

**Objective:** prove memory changes future action, not merely answers questions.

Minimum scenarios:

1. preference changes over time;
2. same entity under different projects/goals;
3. prior tool failure avoided later;
4. successful procedure reused later;
5. false belief corrected by observation;
6. fragmented episode reconstructed from provenance;
7. stale state excluded from present but returned historically;
8. current plan changes because of previous outcome;
9. semantically similar irrelevant memory suppressed;
10. tenant isolation during multi-hop recall;
11. Redis session state expires without deleting durable memory;
12. Redis outage degrades STM while durable Postgres recall remains honest.

External benchmark inspiration:

- LongMemEval / LongMemEval-V2;
- MemoryArena;
- temporal reasoning;
- multi-session agent behavior;
- workflow/gotcha retention.

---

# 28. Files likely involved

Canonical existing areas:

```text
src/ai_karen_engine/core/memory/
src/ai_karen_engine/core/memory/episodic/
src/ai_karen_engine/core/memory/graph/
src/ai_karen_engine/core/memory/associative/
src/ai_karen_engine/core/memory/retrieval/
src/ai_karen_engine/platform/memory/redis/
src/ai_karen_engine/platform/memory/postgres/
src/ai_karen_engine/persistence/postgres/
src/ai_karen_engine/config/database.py
src/ai_karen_engine/database/client.py
requirements.txt
supabase/migrations/ or canonical migration directory
```

Search before adding any file. Extend existing owners where possible.

---

# 29. Explicit avoid list

Do not add during this program without benchmark-backed ADR:

- Neo4j;
- Memgraph;
- FalkorDB/FalkorDBLite;
- Kuzu/Ladybug as production authority;
- Graphiti runtime;
- Mem0 runtime;
- Hindsight runtime;
- Zep runtime;
- Elasticsearch;
- Milvus;
- NetworkX;
- pgmq;
- new vector database;
- new memory manager;
- new recall orchestrator;
- new Supabase SDK persistence facade for data already owned by SQLAlchemy.

Research systems are design references, not new runtime authorities.

---

# 30. Required proof commands

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q

pytest tests/ -q -k "memory or recall or redis or postgres"
pytest tests/ -q -k "tenant or rbac or isolation"
pytest tests/ -q -k "graph or temporal or episodic"
pytest tests/ -q -k "consolidation or revision or lifecycle"

git grep -n "core.memory.redis_connection_manager"
git grep -n "platform.memory.redis"
git grep -n "create_engine\|create_async_engine"
git grep -n "psycopg\|psycopg2\|asyncpg"
git grep -n "KuzuGraphAdapter\|LeanGraphService\|get_leangraph_service"
git grep -n "RELATED_TO\|SUPERSEDES\|CONTRADICTS"

docker compose config
```

If UI/API response shape changes:

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

---

# 31. Definition of done

The memory program is complete when all are true:

- Redis is the single intentional STM/session authority;
- Redis compatibility imports are removed after sunset;
- PostgreSQL/Supabase is the single durable memory authority;
- SQLAlchemy/PostgresEngine is the single engine/session authority;
- no direct persistence path silently bypasses canonical repositories;
- episodic formation exists and is test-proven;
- durable memories preserve provenance and temporal truth;
- graph projection is Postgres-backed or deterministically rebuildable;
- graph traversal is real, bounded and tenant-safe;
- graph hits reconstruct canonical evidence;
- pgvector semantic recall is integrated where enabled;
- lexical, episodic, temporal, procedural and graph recall are real, not stubs;
- NeuroRecall owns final fusion/ranking/abstention;
- associative activation uses canonical graph neighborhoods;
- memory consolidation/revision preserves evidence/history;
- user corrections update memory honestly;
- deletion propagates to derived indexes/projections;
- degraded Redis/Postgres states are observable and honest;
- previous experiences demonstrably change later decisions/actions;
- no external graph/memory framework is required to satisfy baseline goals.

---

# 32. Final architecture invariant

KAREN's memory system should always be able to answer four questions:

1. **What is happening right now?** -> Redis STM / current runtime state.
2. **What is true, and what was true before?** -> Supabase/Postgres temporal durable memory.
3. **How are these memories, entities, actions and outcomes connected?** -> Postgres graph projection + associative retrieval.
4. **What did prior experience teach, and should it change what KAREN does now?** -> episodic/procedural memory + NeuroRecall + Runtime/CORTEX decision use.

If a proposed new technology does not materially improve one of these questions under benchmark, do not add it.
