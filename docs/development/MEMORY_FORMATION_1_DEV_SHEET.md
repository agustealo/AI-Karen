# MEMORY-FORMATION-1 Developer Sheet

> **Status:** READY FOR EXECUTION
> **Priority:** P0 memory architecture closure before additional graph technology
> **Scope:** memory formation, episodic segmentation, Redis STM integration, Supabase/PostgreSQL durable persistence, temporal state, provenance reconstruction, belief revision, recall evidence packing, behavioral proof
> **Authority:** `docs/development/MEMORY.md`, `docs/development/MEMORY_GRAPH_DEV_SHEET.md`, `PROJECT_DEV_MANIFEST.md`
> **Core rule:** Redis is KAREN's bounded STM/runtime-memory substrate. Supabase-hosted PostgreSQL is the durable episodic/LTM source of truth. Memory formation converts live interaction into governed events before graph projection. NeuroRecall remains recall-policy authority and NeuroVault remains durable-persistence governance.

---

## 1. Objective

Build the missing protocol that converts live interaction, action, tool output, and environment changes into coherent, governed memory while preserving KAREN's actual two-tier storage architecture:

```text
live interaction
   -> Redis STM / session continuity
   -> event boundary detection
   -> contextual state + intent cues
   -> structured episode/event
   -> memory policy
   -> NeuroVault
   -> Supabase/PostgreSQL durable commit
   -> pgvector / lexical / temporal indexes
   -> PostgreSQL graph projection
   -> consolidation / revision
   -> NeuroRecall reconstruction
   -> future behavior
```

Do not add another memory store, graph database, queue, or graph-compute library during this sprint.

---

## 2. Actual stack contract

### Redis

Canonical owner:

`src/ai_karen_engine/platform/memory/redis/`

Use Redis for:

- bounded recent-turn/session state;
- working-memory summaries;
- hot context required to decide whether an event continues or closes;
- short-lived runtime coordination data explicitly owned by memory/runtime;
- low-latency STM candidate retrieval.

Do not use Redis as:

- canonical episodic persistence;
- canonical semantic/LTM persistence;
- graph truth;
- durable user preference/fact authority;
- proof that memory was permanently saved.

The legacy `core.memory.redis_connection_manager` import is a compatibility shim only. New work imports the canonical platform adapter.

### Supabase/PostgreSQL

Canonical durable path:

```text
Memory domain
 -> platform/memory/postgres adapters
 -> database.client compatibility facade where still required
 -> persistence.postgres.PostgresEngine
 -> Supabase-hosted PostgreSQL
```

Reuse existing async SQLAlchemy sessions and migration ownership.

Do not create:

- a second Supabase client repository;
- runtime table creation;
- a duplicate memory schema;
- a graph-specific durable DB connection layer.

Use native Postgres/Supabase capabilities first:

- pgvector;
- FTS;
- pg_trgm where approved;
- recursive CTEs;
- RLS + explicit tenant predicates;
- pgTAP where useful.

---

## 3. Why this sprint exists

The live repository already contains NeuroRecall, Postgres durable recall, Redis STM retrieval, graph projection, associative spreading activation, and consolidation rules.

The missing production bridge is:

```text
raw interaction
   != coherent event
   != durable episode
   != semantic state
   != graph relation
```

Today `core/memory/episodic/` is effectively empty as a first-class episodic authority. Consolidation is still primarily a shallow promotion rule set. Graph recall can lose source narrative by wrapping relationship dictionaries as new memory objects.

This sprint fixes formation before adding more graph sophistication.

---

## 4. Canonical formation pipeline

### Stage A — live STM context

Runtime writes/updates bounded session state through the canonical Redis platform adapter.

Redis context may include:

- recent messages;
- current task/goal cues;
- active project/workspace;
- recent actions/tool results;
- current episode candidate ID;
- bounded session summary;
- unresolved state transitions.

Requirements:

- tenant + user + session scope mandatory;
- TTL explicit;
- bounded payload size;
- no secrets persisted beyond policy;
- degraded fallback is explicit and non-durable.

### Stage B — event segmentation

`core/memory/episodic/` becomes canonical owner of event/episode segmentation contracts.

Boundary signals may include:

- task/goal change;
- project/workspace change;
- meaningful time gap;
- action/tool sequence completion;
- success/failure outcome;
- decision/commitment;
- user correction;
- environment state transition;
- session boundary.

Start deterministic-first. Model-assisted segmentation must be prompt-contract + budget gated.

### Stage C — structured event formation

Create/reuse canonical typed event contracts carrying:

```text
event_id / episode_id
tenant_id
user_id
conversation_id
session_id
project/workspace scope
started_at
ended_at
observed_at
recorded_at
valid_from
valid_to
goal/action/state cues
entities
constraints
actions
observations
outcomes
feedback
source_refs
causal_parent_ids
confidence
salience
lifecycle_state
schema_version
```

Do not duplicate raw message/tool payloads when canonical source references exist.

### Stage D — governed durable commit

Runtime submits eligible candidates to memory policy + NeuroVault.

NeuroVault commits through the canonical Postgres path into Supabase-hosted PostgreSQL.

A Redis write must never be interpreted as successful durable commit.

### Stage E — derived indexes/projections

After durable commit:

- create/update pgvector representation where enabled;
- update lexical/entity indexes;
- project graph relationships into PostgreSQL-native graph tables;
- enqueue in-process/normal async consolidation candidates through existing runtime mechanisms where sufficient.

Do not add pgmq until throughput/reliability benchmarks demonstrate an actual queue requirement.

---

## 5. Contextual state and intent cues

Store compact retrieval cues, not hidden reasoning:

```text
goal_class
action_class
entity_ids/entity_types
project_id/workspace_id
environment/domain
constraint_keys
outcome_class
state_fingerprint
```

CORTEX may provide current goal/intent signals. MemoryFormation stores bounded historical cues. NeuroRecall uses compatibility as one retrieval signal.

MemoryFormation must not become a second intent classifier/cognitive head.

---

## 6. Temporal and durative state

Support both point events and intervals.

```text
new observation
 -> find compatible active durable state in Postgres
 -> same state? extend/reinforce interval
 -> changed state? close old interval + create new state
 -> uncertain? retain observation without forced transition
```

Redis may hold the unresolved live state while an episode is still open. Once durable truth is committed, PostgreSQL is authoritative.

Examples:

- user preference changes and later reverts;
- project provider changes;
- active development branch changes;
- repeated workflow remains stable over time;
- uncertain update remains unconfirmed.

---

## 7. Provenance-first graph and recall

Graph projection stores references to canonical durable events/memories.

Graph candidates must return:

```text
source_memory_ids
source_event_ids
graph_path
relationship_types
depth
graph_score
temporal_match
scope_match
```

NeuroRecall then performs reverse provenance expansion:

```text
graph/event candidate
 -> canonical Postgres IDs
 -> fetch canonical durable event/memory
 -> bounded neighboring episode expansion
 -> temporal ordering
 -> dedupe
 -> evidence packing
```

Do not turn graph dictionaries into pseudo-memory content.

Redis STM can be fused separately when current-session context is relevant.

---

## 8. Epistemic classes and belief revision

At minimum distinguish:

- world fact;
- observation;
- user preference/belief;
- KAREN hypothesis/opinion;
- experience/outcome;
- procedure/lesson.

Revision decisions:

```text
UNCHANGED
STRENGTHEN
WEAKEN
REVISE
SUPERSEDE
SPLIT
QUARANTINE
```

Inputs include prior durable assertion, new observation, provenance strength, contradiction/support, temporal compatibility, user correction, and outcome verification.

Durable revisions pass through NeuroVault and Postgres. Redis may cache current state after commit but does not own revision history.

---

## 9. Hierarchical consolidation

Target abstraction ladder:

```text
L0 source reference
L1 observation/action
L2 event/episode
L3 semantic state/fact/preference
L4 procedure/lesson
L5 generalized strategy/pattern
```

Promotion requires evidence such as:

- repetition across independent durable episodes;
- successful outcomes;
- user confirmation;
- correction history;
- temporal stability;
- cross-context transfer success;
- source confidence;
- contradiction count.

Recall frequency alone is not sufficient.

Redis TTL expiration is not consolidation or forgetting.

---

## 10. Implementation tasks

### Task 1 — Redis STM truth

Do:

- move new imports to `platform.memory.redis` canonical path;
- document key schema + TTL ownership;
- prove tenant/user/session isolation;
- prove Redis unavailable -> explicit bounded degraded mode;
- ensure no Redis-only write produces durable-save metadata/UI truth.

Avoid:

- deleting Redis because the legacy shim is deprecated;
- expanding Redis into durable LTM.

### Task 2 — Episodic authority

Do:

- build canonical event/episode contracts under `core/memory/episodic`;
- implement deterministic-first segmentation;
- use bounded Redis context as formation input;
- bind exact source provenance.

### Task 3 — MemoryFormationService

Do:

- create one subordinate formation service;
- accept runtime observations + bounded STM context;
- emit typed candidates/events;
- incorporate temporal, epistemic, state, and provenance contracts.

Do not create another memory manager/orchestrator.

### Task 4 — Supabase/Postgres durable persistence

Do:

- reuse `PostgresEngine` / canonical async session path;
- use migrations for new event/relationship structures;
- preserve tenant/user scopes;
- add temporal/provenance/cue indexes;
- reuse existing ledger concepts where they already own the data.

Avoid direct Supabase SDK persistence beside the canonical DB layer.

### Task 5 — Semantic + lexical retrieval closure

Do:

- connect pgvector through canonical storage where enabled;
- close real lexical retrieval rather than empty router branches;
- use pg_trgm/FTS only where demonstrated useful;
- keep NeuroRecall as fusion/ranking authority.

### Task 6 — PostgreSQL graph projection

Do:

- replace pseudo-Kuzu durability with Postgres-native relation persistence;
- reference canonical durable IDs;
- implement bounded recursive CTE traversal;
- preserve temporal validity + provenance;
- make projection rebuildable from durable memory.

### Task 7 — associative integration

Do:

- fix/harden existing KAREN spreading activation;
- feed it canonical Postgres graph neighborhoods;
- remove its role as an independent graph truth store;
- benchmark before adding NetworkX/PPR dependency.

### Task 8 — temporal consolidation + belief revision

Do:

- extend/close validity intervals;
- form durative state;
- implement contradiction/supersession;
- produce evidence-backed higher-level candidates.

### Task 9 — behavioral proof

Minimum longitudinal scenarios:

1. STM continuity across turns via Redis;
2. Redis outage with durable Postgres recall still working;
3. preference change over time;
4. repeated entity under different goals/projects;
5. tool failure learned and avoided later;
6. successful procedure reused later;
7. incorrect prior belief revised by evidence;
8. multi-turn episode reconstructed from graph/provenance;
9. tenant isolation across Redis + Postgres + multi-hop traversal;
10. stale state excluded from current answer but historically recallable;
11. process restart preserves durable memory even when Redis is empty;
12. Redis cache success never masquerades as durable save success.

---

## 11. Security and observability

Required dimensions:

```text
correlation_id
request_id
tenant_id
user_id
session_id
conversation_id
memory_source
redis_degraded
postgres_degraded
formation_stage
source_event_id
source_memory_id
graph_depth
candidate_count
persistence_status
latency_ms
```

Required event families include:

```text
memory.stm.read/write/degraded
memory.formation.started/completed
memory.event.boundary_detected
memory.episode.created/extended
memory.persistence.started/completed/failed
memory.graph.projected
memory.recall.provenance_expanded
memory.consolidation.decided
memory.revision.decided
memory.behavior_transfer.recorded
```

Never log secrets or raw sensitive payloads unnecessarily.

---

## 12. Dependency policy

During MEMORY-FORMATION-1 do not add:

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

Redis and the canonical PostgreSQL/SQLAlchemy stack are existing architecture and must be represented truthfully in dependency manifests/deployment images.

If `redis.asyncio` or SQLAlchemy are imported by active production paths but absent from the canonical dependency manifest, fix the manifest rather than pretending the capability is retired.

---

## 13. Exit criteria

MEMORY-FORMATION-1 is complete only when:

- Redis is formally proven as bounded STM/runtime memory;
- deprecated Redis compatibility imports are no longer used by new code;
- raw interaction forms coherent typed episodes;
- episode formation uses bounded live STM context where needed;
- durable episodes/facts persist through canonical Supabase/Postgres sessions;
- schema changes are migration-owned;
- graph projection is Postgres-native/rebuildable and provenance-linked;
- graph hits reconstruct canonical evidence;
- current vs historical state is distinguishable;
- beliefs can strengthen/weaken/revise/supersede;
- consolidation produces provenance-backed abstractions;
- prior experience measurably changes later behavior;
- tenant isolation holds across Redis, Postgres, vector retrieval, and graph traversal;
- no second durable memory authority exists;
- no new external memory/graph dependency was added without benchmark evidence.

---

## 14. Proof commands

```text
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Add targeted proof for:

- Redis STM/TTL/degraded-mode behavior;
- Postgres restart durability;
- Supabase migration contract;
- tenant isolation;
- pgvector/lexical retrieval where enabled;
- event segmentation;
- temporal state transitions;
- graph recursive traversal;
- provenance reconstruction;
- behavioral transfer.