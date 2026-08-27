# MEMORY-GRAPH-2 Developer Sheet

> **Status:** READY FOR EXECUTION
> **Priority:** P0/P1 memory architecture hardening
> **Scope:** `src/ai_karen_engine/core/memory/graph`, graph projections, NeuroRecall graph candidates, memory lifecycle, tests, configuration, observability
> **Authority:** `docs/development/MEMORY.md` + `PROJECT_DEV_MANIFEST.md`
> **Core rule:** The Memory Graph is a temporal/associative projection of governed memory. It is not a second memory source of truth and not a second recall authority.

---

## 1. Objective

Replace the current flat LeanGraph projection with a production-grade, local-first, backend-neutral **Temporal Cognitive Memory Graph** that supports:

- durable graph projection or deterministic rebuild;
- typed semantic relationships;
- bi-temporal fact validity;
- provenance and source tracing;
- entity resolution and aliases;
- contradiction/reinforcement/supersession;
- multi-hop retrieval;
- associative activation;
- episodic + semantic + procedural + prospective relationships;
- action/outcome/lesson experience memory;
- graph candidate generation for NeuroRecall;
- tenant-safe point-in-time queries;
- observable graph lifecycle;
- benchmarkable improvement in recall and future behavior.

Do **not** add Mem0, Graphiti, Zep, A-MEM, Hindsight, HippoRAG, or another memory framework as a competing runtime. Reuse their validated design ideas inside KAREN's canonical memory boundaries.

---

## 2. Live forensic findings

### MG-F01 — `KuzuGraphAdapter` is not a Kuzu persistence adapter

Current implementation creates the configured directory but stores nodes in Python dictionaries and edges in an in-memory set.

Consequences:

- graph state disappears on process restart;
- the configured graph DB path is misleading;
- telemetry identifies backend as Kuzu without proving Kuzu storage;
- graph recovery/backups are undefined;
- a successful projection does not prove durable projection.

**Severity:** CRITICAL

### MG-F02 — `max_depth` is accepted but not implemented

`find_related_events(..., max_depth=...)` only inspects direct incident edges and always returns `depth: 1`.

Consequences:

- graph recall is one-hop only;
- pattern completion cannot exploit multi-hop association;
- advertised graph traversal semantics are false;
- graph structure adds little over relational joins/tag indexes.

**Severity:** HIGH

### MG-F03 — graph models are structurally thin

Current first-class models are only:

- `MemoryEventNode`;
- `EntityNode`;
- `AssertionNode`;
- `GraphEdge`.

Missing first-class temporal, provenance, epistemic, experience, procedural, goal, decision, outcome, and lifecycle contracts.

**Severity:** HIGH

### MG-F04 — temporal knowledge is not modeled

Current nodes carry `created_at`, but there is no canonical world-valid interval, observation time, invalidation time, or point-in-time query contract.

Consequences:

- stale and current facts can coexist ambiguously;
- `SUPERSEDES` is a structural edge but not a temporal truth transition;
- historical questions cannot be answered reliably;
- graph cannot distinguish "was true" from "is true".

**Severity:** CRITICAL for human-like memory

### MG-F05 — entity resolution is lexical and unsafe for cognition

Default entity IDs are derived from `tenant_id:text.lower()` and entity lookup uses exact normalized text.

Consequences:

- aliases are fragmented;
- same-name entities may collide;
- typo/variant resolution is absent;
- entity merges/splits cannot be represented safely;
- cross-conversation identity continuity is weak.

**Severity:** HIGH

### MG-F06 — edge vocabulary is too flat

Schema includes broad relations such as `MENTIONS`, `ASSERTS`, `RELATED_TO`, `CONTRADICTS`, `REINFORCES`, and `SUPERSEDES`, but lacks a typed domain vocabulary for causality, tasks, goals, decisions, outcomes, procedures, ownership, preferences, temporal ordering, aliases, and derivation.

**Severity:** HIGH

### MG-F07 — graph evolution is projection-only

`project_memory_event` primarily appends/project nodes and edges. There is no canonical graph-evolution service for:

- fact invalidation;
- validity interval closure;
- confidence revision;
- entity merge/split;
- observation generalization;
- procedure/lesson derivation;
- lifecycle propagation from canonical memory.

**Severity:** HIGH

### MG-F08 — epistemic classes are flattened

An assertion can carry confidence/polarity, but graph semantics do not cleanly distinguish:

- externally grounded fact;
- user belief;
- user preference;
- KAREN hypothesis/opinion;
- observation;
- experience/outcome;
- generalized lesson.

**Severity:** HIGH

### MG-F09 — backend strategy is stale

Current configuration defaults to `kuzu`. The upstream Kuzu project was archived in October 2025.

KAREN must not bind its cognitive-memory design to an archived backend. Preserve the adapter boundary and make backend selection an ADR with live maintenance/performance/durability proof.

**Severity:** HIGH strategic risk

### MG-F10 — graph is not yet proven to improve behavior

Current proof should not stop at "retrieved the right fact." Human-like agent memory must demonstrate that previous experience changes later planning/action.

**Severity:** HIGH

---

## 3. Research alignment

### 3.1 Graphiti / Zep

Reuse concepts:

- temporal knowledge graph;
- valid-time + ingestion/observation-time semantics;
- fact invalidation rather than destructive overwrite;
- episode/source provenance;
- hybrid semantic/lexical/graph retrieval;
- historical point-in-time state.

Do not adopt as a second memory authority.

### 3.2 A-MEM

Reuse concepts:

- dynamic linking when new memory arrives;
- evolving contextual representations;
- memory organization that adapts as new evidence is integrated;
- network formation beyond static similarity links.

KAREN adaptation: graph evolution must remain deterministic/governed where persistence or user truth changes.

### 3.3 HippoRAG 2

Reuse concepts:

- associative retrieval over a graph;
- Personalized-PageRank-like activation/ranking where justified;
- factual + associative + sense-making retrieval balance;
- graph retrieval as continual non-parametric learning substrate.

KAREN adaptation: page-rank/activation is a retrieval primitive beneath NeuroRecall, not recall authority.

### 3.4 Hindsight

Reuse concepts:

- separate logical networks/classes for world state, experience, observations, and opinions/beliefs;
- parallel retrieval strategies;
- temporal filtering;
- evolving opinion/confidence state.

KAREN adaptation: preserve KAREN's broader semantic/procedural/prospective model instead of copying Hindsight's taxonomy verbatim.

### 3.5 MemoryOS

Reuse concepts:

- explicit memory lifecycle;
- hierarchical movement/consolidation;
- memory management as an operating concern rather than passive storage.

KAREN adaptation: existing STM/episodic/LTM/procedural/prospective authorities remain canonical.

### 3.6 LongMemEval-V2 / MemoryArena

Use as evaluation guidance:

- static state recall;
- dynamic state tracking;
- workflow knowledge;
- environment gotchas;
- premise awareness;
- interdependent multi-session tasks;
- experience altering later action.

KAREN must test **memory-to-behavior transfer**, not only QA recall.

---

## 4. Target authority model

```text
                    CORTEX
             recall eligibility/scope
                       |
                       v
                   Runtime
                       |
                       v
                 NeuroRecall
           recall strategy + fusion
        /        |         |         \
       v         v         v          v
 semantic    episodic   temporal    graph
 retrieval    recall    retrieval   candidates
                                      |
                                      v
                           Temporal Memory Graph
                                      |
                     +----------------+----------------+
                     |                |                |
                  entities         assertions      experiences
                     |                |                |
                  aliases       valid intervals     outcomes
                     |                |                |
                  relations      provenance        procedures
                                      |
                                      v
                              governed source refs
                                      |
                                      v
                                 NeuroVault
                                      |
                                      v
                         canonical durable memory
```

The graph does not bypass NeuroVault on committed memory changes. NeuroRecall does not mutate graph truth while retrieving.

---

## 5. Target graph ontology

### Core node classes

- `MemoryEvent`
- `Episode`
- `Entity`
- `Assertion`
- `Observation`
- `Belief`
- `Preference`
- `Goal`
- `Task`
- `Decision`
- `Action`
- `Outcome`
- `Procedure`
- `Lesson`
- `Artifact`
- `Project`
- `Conversation`
- `User`
- `Tenant`
- `SourceReference`

Do not create a new node class where a typed property/relationship is sufficient. Keep ontology bounded and registry-driven.

### Relationship families

Identity:

- `SAME_AS`
- `ALIAS_OF`
- `REFERS_TO`

Occurrence/context:

- `MENTIONS`
- `PARTICIPATED_IN`
- `OCCURRED_IN`
- `BELONGS_TO`

Temporal:

- `PRECEDES`
- `FOLLOWS`
- `OVERLAPS`
- `SUPERSEDES`

Evidence/epistemic:

- `ASSERTS`
- `OBSERVED_FROM`
- `SUPPORTED_BY`
- `CONTRADICTS`
- `REINFORCES`
- `DERIVED_FROM`

Causal/experience:

- `CAUSED`
- `CONTRIBUTED_TO`
- `RESULTED_IN`
- `ATTEMPTED_FOR`
- `FAILED_BECAUSE`
- `SUCCEEDED_WITH`
- `LEARNED_FROM`

Task/procedure:

- `PURSUED_GOAL`
- `USED_PROCEDURE`
- `REQUIRES`
- `DEPENDS_ON`
- `APPLIES_TO`

Ontology additions require registry/schema update and tests.

---

## 6. Canonical temporal contract

Introduce typed temporal/provenance fields rather than hiding them in arbitrary `metadata`.

Required concept set:

```text
valid_from
valid_to
observed_at
recorded_at
invalidated_at
source_memory_id
source_event_id
source_type
confidence
lifecycle_state
schema_version
```

Semantics:

- `valid_*` describes truth in the represented world;
- `observed_at` describes when KAREN/user/system learned/observed it;
- `recorded_at` describes persistence/projection time;
- a superseded fact remains historically queryable;
- unknown times remain `None`, never fabricated;
- all timestamps use canonical timezone-aware temporal types chosen by the project-wide temporal contract.

---

## 7. Entity resolution

Create one canonical `EntityResolver` under the memory graph domain.

Resolution pipeline:

```text
raw mention
 -> normalization
 -> exact canonical/alias lookup
 -> typed candidate lookup
 -> semantic/lexical candidate scoring
 -> context disambiguation
 -> confidence gate
 -> existing entity | new entity | abstain/ambiguous
```

Requirements:

- tenant scope is mandatory;
- user/project scope participates where applicable;
- aliases are explicit relationships/records;
- merges are auditable and reversible;
- splits preserve source provenance;
- uncertain identity must not silently merge;
- entity IDs are opaque stable IDs, not normalized user text.

---

## 8. Retrieval design

### Graph candidate generator

Provide a typed graph candidate API for NeuroRecall.

Inputs:

- authorized scope;
- query cues/entities;
- temporal/as-of constraints;
- allowed memory classes;
- max depth;
- candidate budget;
- activation/traversal strategy.

Outputs:

- canonical source memory/event IDs;
- graph path/reason;
- edge types;
- depth;
- local graph score;
- temporal validity;
- confidence/provenance metadata.

NeuroRecall remains responsible for final fusion/ranking/abstention.

### Multi-hop traversal

Implement true bounded traversal.

Requirements:

- enforce `max_depth`;
- avoid cycles;
- scope-filter every expansion;
- cap fan-out;
- cap total visited nodes/edges;
- support relationship allow/deny lists;
- penalize path length;
- preserve explainable paths.

### Associative activation

Evaluate two local strategies behind a shared interface:

1. weighted spreading activation;
2. personalized PageRank / random-walk ranking.

Select through benchmark, not taste.

Score features may include:

```text
edge_semantic_weight
x temporal_validity
x recency_or_decay
x source_confidence
x memory_salience
x outcome_transfer_utility
x depth_penalty
x scope_match
```

Do not convert activation score into truth confidence.

---

## 9. Experience graph

Human-like memory for KAREN requires action/outcome memory.

Canonical experience envelope should be able to represent:

```text
Experience
  goal
  task/context
  plan/strategy
  actions
  tools/plugins/models used
  environment state
  constraints
  outcome
  success/failure
  errors/gotchas
  user feedback
  lesson candidates
  transfer evidence
```

Graph links allow later recall such as:

- "what failed the last time we deployed this project?"
- "which strategy worked for this class of task?"
- "what changed since the prior attempt?"
- "which tool caused repeated failures?"

Procedure/Lesson promotion must go through consolidation + governed persistence.

---

## 10. Graph backend decision

### Current state

`KARI_GRAPH_BACKEND=kuzu` is legacy/default configuration, but the upstream Kuzu repository is archived. Current adapter also does not use Kuzu persistence.

### Required ADR

Benchmark at least:

- **LadybugDB** or maintained Kuzu-compatible successor for embedded/local-first use;
- **FalkorDB/FalkorDBLite** where appropriate for GraphRAG/low-latency traversal;
- **Memgraph** for maintained Cypher/server deployment;
- optional PostgreSQL graph extension/relational projection only if it can meet traversal and operational requirements without creating architectural contortions.

Do not add all of them. Select one primary local backend and at most one production/service backend if scale requires it.

ADR metrics:

- upstream maintenance/release health;
- Python support;
- local/offline install;
- Cypher/property graph capability;
- restart durability;
- write concurrency;
- read latency p50/p95;
- 1/2/3/4-hop traversal latency;
- graph size scaling;
- temporal property filtering;
- backup/rebuild story;
- memory footprint;
- packaging complexity;
- license;
- Windows/Linux support;
- tenant partitioning/isolation.

Until ADR completion, code against `GraphRepository`/adapter contracts only.

---

## 11. Implementation phases

# Phase 1 — GRAPH-TRUTH

**Objective:** Make the graph honest, durable/rebuildable, typed, and correctly traversable before adding cognitive sophistication.

### Task 1.1 — Canonical graph contracts

Do:

- replace stringly/untyped graph payload surfaces with typed graph contracts;
- introduce stable node/edge IDs;
- introduce temporal/provenance/lifecycle contracts;
- introduce relationship registry/enums or equivalent canonical typed authority;
- validate tenant/user scope at public graph boundaries.

Reuse:

- existing `core/memory/graph/models.py`;
- existing project-wide temporal/confidence types where canonical versions already exist.

Avoid:

- parallel graph model packages;
- duplicate time/confidence enums;
- graph-specific tenant defaults.

Files:

- `src/ai_karen_engine/core/memory/graph/models.py`
- `src/ai_karen_engine/core/memory/graph/schema.py`
- canonical shared cognitive/temporal type files only where reuse requires extension.

Proof:

- import/compile;
- schema validation tests;
- tenant-required tests;
- no duplicate authority search.

### Task 1.2 — Real repository/adapter boundary

Do:

- define a complete `GraphRepository` protocol/ABC;
- move storage behavior behind it;
- remove misleading backend claims;
- implement real persistence for the selected backend after ADR;
- provide a deterministic in-memory adapter **only for tests/dev explicitly configured as ephemeral**.

Avoid:

- production fallback from durable backend to silent in-memory state;
- fake successful durability telemetry.

Files:

- `src/ai_karen_engine/core/memory/graph/adapters/base.py`
- `src/ai_karen_engine/core/memory/graph/adapters/*`
- `src/ai_karen_engine/core/memory/graph/config.py`

Proof:

- write -> process restart -> read;
- backend-unavailable degraded result;
- no implicit in-memory production fallback.

### Task 1.3 — True bounded multi-hop traversal

Do:

- implement BFS/weighted traversal or backend-native equivalent;
- enforce `max_depth`;
- cycle suppression;
- relationship filters;
- visited-node/edge budgets;
- path/reason metadata.

Proof:

- 1-hop/2-hop/3-hop fixtures;
- depth cap;
- cycle fixture;
- tenant leakage negative test;
- latency budget benchmark.

### Task 1.4 — Projection rebuild

Do:

- make graph projection deterministic from canonical memory/event records;
- implement rebuild command/service under governed maintenance path;
- idempotent upserts;
- progress + failure telemetry;
- no duplicate relationships after rebuild.

Proof:

- wipe graph -> rebuild -> equivalent semantic graph;
- repeated rebuild stable;
- deletion/tombstone behavior preserved.

**Phase 1 exit gate:** restart durability or deterministic rebuild proven, multi-hop real, tenant-safe, no false Kuzu backend claim.

---

# Phase 2 — TEMPORAL-ASSOCIATIVE

**Objective:** Give the graph evolving truth and human-like cue association.

### Task 2.1 — Bi-temporal assertions/relations

Do:

- valid-time and observed/recorded-time support;
- point-in-time lookup;
- close old validity interval on supersession;
- maintain source links;
- distinguish unknown from open-ended time.

Proof scenarios:

1. user works at Company A;
2. later user works at Company B;
3. current query returns B;
4. historical as-of query returns A;
5. both remain auditable.

### Task 2.2 — Epistemic separation

Do:

- distinguish world facts, observations, user beliefs/preferences, KAREN hypotheses/opinions, experiences, procedures;
- confidence belongs to the appropriate epistemic object;
- belief changes do not invalidate unrelated world facts.

Proof:

- conflicting user belief vs external observation does not collapse into one assertion;
- opinion confidence evolves without rewriting source evidence.

### Task 2.3 — Entity resolver

Do:

- canonical/alias resolution;
- ambiguous-name abstention;
- merge/split operations with audit trail;
- typed entity namespaces;
- stable IDs.

Proof:

- aliases converge;
- same-name different-person fixture stays separated;
- typo/variant can resolve with confidence;
- low-confidence case abstains.

### Task 2.4 — Associative retrieval

Do:

- weighted spreading activation interface;
- evaluate Personalized PageRank alternative;
- temporal + confidence + salience + depth weighting;
- inhibition for contradiction/stale paths where justified;
- activation budget and reason paths.

Proof:

- indirect cue retrieves target episode that vector top-k misses;
- stale edge does not dominate current relation;
- bounded runtime on dense graph;
- activation score remains separate from truth confidence.

### Task 2.5 — Pattern separation / completion

Do:

- protect similar episodes by event/time/context identity;
- partial cues may retrieve likely episode clusters;
- inferred completion marked as inferred/uncertain;
- no completion automatically persisted as fact.

Proof:

- two similar Detroit jobs remain distinct;
- partial cue identifies the right job using graph/context;
- ambiguous cue returns multiple candidates or abstains.

**Phase 2 exit gate:** temporal truth, entity continuity, associative cue recall, and uncertainty behavior all pass.

---

# Phase 3 — EXPERIENCE-EVOLUTION

**Objective:** Make memory change future behavior and self-organize without creating an autonomous truth-mutating subsystem.

### Task 3.1 — Experience memory envelope

Do:

- goal/plan/action/outcome/failure/lesson structure;
- source action/tool/model metadata;
- environment state/gotcha fields;
- transfer evidence.

Reuse:

- existing episodic/procedural memory contracts;
- runtime telemetry/outcome records;
- canonical GoalState and evidence types.

Avoid:

- duplicate agent trajectory store if canonical telemetry already contains source data.

### Task 3.2 — Consolidation into observations/lessons

Do:

- group repeated related episodes;
- generate typed generalized-memory candidates;
- require evidence/provenance support;
- NeuroVault governs durable promotion;
- graph links generalized memory back to source episodes.

Proof:

- repeated preference episodes create one supported preference memory;
- repeated failure mode creates one lesson candidate;
- source episodes remain traceable.

### Task 3.3 — Reconsolidation

Do:

- recall + new evidence can propose a revised version;
- old state remains historical;
- confidence can rise/fall;
- contradiction does not silently erase evidence.

Proof:

- correction scenario;
- retracted preference scenario;
- conflicting evidence scenario.

### Task 3.4 — Adaptive forgetting

Do:

- policy considers age, redundancy, confidence, recurrence, utility, significance, user deletion/pinning, legal/security retention;
- graph projections follow lifecycle changes;
- no retrieval of deleted/quarantined memory.

Proof:

- redundant low-value traces age out;
- important repeated memory retained;
- explicit deletion wins;
- graph path cannot resurrect deleted memory.

### Task 3.5 — Memory-to-behavior transfer benchmark

Do:

Build KAREN-native scenarios inspired by LongMemEval-V2 and MemoryArena:

- prior deployment failure changes next deployment plan;
- learned UI/environment gotcha avoids repeated failure;
- project procedure learned across sessions;
- evolving user preference changes planning;
- stale preference does not override current preference;
- previous tool/model failure influences eligible routing hint without violating provider authority.

Measure:

- task success delta with memory on/off;
- retrieval precision/recall;
- evidence faithfulness;
- stale-memory error rate;
- graph contribution rate;
- transfer utility;
- latency/token cost;
- abstention quality.

**Phase 3 exit gate:** memory demonstrably improves later action, not merely factual QA.

---

## 12. Required files to audit before implementation

Primary:

- `src/ai_karen_engine/core/memory/graph/models.py`
- `src/ai_karen_engine/core/memory/graph/schema.py`
- `src/ai_karen_engine/core/memory/graph/service.py`
- `src/ai_karen_engine/core/memory/graph/config.py`
- `src/ai_karen_engine/core/memory/graph/adapters/base.py`
- `src/ai_karen_engine/core/memory/graph/adapters/kuzu_adapter.py`
- `src/ai_karen_engine/core/memory/graph/adapters/memgraph_adapter.py`

Consumers/producers:

- `src/ai_karen_engine/core/memory/retrieval/`
- `src/ai_karen_engine/core/memory/associative/`
- `src/ai_karen_engine/core/memory/episodic/`
- `src/ai_karen_engine/core/memory/procedural/`
- `src/ai_karen_engine/core/memory/prospective/`
- `src/ai_karen_engine/core/memory/neuro/`
- `src/ai_karen_engine/core/memory/projection/`
- `src/ai_karen_engine/core/memory/lifecycle_service.py`
- `src/ai_karen_engine/core/memory/memory_runtime_manager.py`
- NeuroVault/governed persistence implementations
- ChatRuntime composition/integration

Tests/docs/config:

- all graph/memory tests;
- `.env*example` graph variables;
- `docs/development/MEMORY.md`;
- `PROJECT_DEV_MANIFEST.md`;
- recovery/deployment docs mentioning graph storage.

---

## 13. DRY / architecture constraints

- Do not create `AdvancedMemoryGraph`, `NeuroGraph`, `CognitiveGraphManager`, or another competing graph owner.
- Prefer evolving `core/memory/graph/`.
- One entity resolver.
- One temporal relationship contract.
- One graph repository abstraction.
- One relationship/ontology registry.
- One graph candidate contract consumed by NeuroRecall.
- One governed graph projection path from committed memory.
- One graph lifecycle/rebuild path.
- Reuse canonical `EvidenceType`, `GoalState`, confidence, temporal, tenant, audit, and telemetry contracts.
- No provider/model selection in graph code.
- No prompts scattered inside storage adapters.
- LLM-assisted extraction/entity linking, if used, must go through canonical runtime/capability contracts and be optional/local-first/config-driven.

---

## 14. Security / RBAC

Mandatory:

- tenant scope on every graph operation;
- user/project scope where applicable;
- no cross-tenant alias resolution;
- no cross-tenant traversal;
- deletion/privacy lifecycle respected before candidate return;
- no secret/token memory projection;
- audit entity merges/splits, fact invalidation, destructive lifecycle changes, rebuilds, backend migration;
- plugin/tool data cannot enter durable graph outside governed memory candidate policy;
- backend credentials are config/secrets, never graph metadata/logs.

Critical tests:

- malicious entity ID collision across tenants;
- alias collision across tenants;
- traversal path attempting to cross tenant boundary;
- deleted source memory still referenced by graph;
- quarantined memory excluded from recall.

---

## 15. Observability

Emit structured events:

```text
memory_graph_projection_started
memory_graph_projection_completed
memory_graph_projection_failed
memory_graph_entity_resolution_started
memory_graph_entity_resolution_completed
memory_graph_entity_resolution_ambiguous
memory_graph_entity_merged
memory_graph_entity_split
memory_graph_fact_superseded
memory_graph_fact_contradicted
memory_graph_recall_started
memory_graph_recall_completed
memory_graph_recall_abstained
memory_graph_rebuild_started
memory_graph_rebuild_completed
memory_graph_rebuild_failed
memory_graph_backend_degraded
```

Fields where applicable:

```text
correlation_id
request_id
tenant_id
user_id
conversation_id
source_memory_id
source_event_id
backend
operation
node_count
edge_count
candidate_count
visited_node_count
visited_edge_count
max_depth
actual_depth
temporal_filter
as_of
latency_ms
status
error_type
error_code
```

Never log source content that may contain secrets merely to debug graph extraction.

---

## 16. Proof matrix

| Capability | Required proof |
|---|---|
| Durable graph | write -> restart -> read |
| Rebuildable graph | wipe -> rebuild -> equivalent graph |
| Tenant safety | cross-tenant traversal impossible |
| True traversal | depth 1/2/3 fixtures |
| Temporal truth | current + as-of queries |
| Supersession | old validity closed, history retained |
| Provenance | every derived fact traces to source |
| Entity resolution | alias merge + ambiguous abstention |
| Contradiction | conflicting evidence preserved |
| Associative recall | indirect cue beats vector-only fixture |
| Pattern separation | similar episodes remain distinct |
| Pattern completion | partial cue retrieves with uncertainty |
| NeuroRecall authority | graph returns candidates, not final recall |
| Forgetting | deleted/expired source cannot reappear via graph |
| Experience transfer | prior outcome changes future task plan |
| Recovery | backup or deterministic rebuild proven |
| Observability | structured lifecycle events emitted |

---

## 17. Commands

Run at minimum:

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q
```

Focused graph/memory proof should include targeted test modules for:

```bash
pytest tests/ -q -k "memory and graph"
pytest tests/ -q -k "tenant and memory"
pytest tests/ -q -k "recall"
pytest tests/ -q -k "temporal"
pytest tests/ -q -k "consolidation or lifecycle"
```

Also run reference audits before deleting/renaming adapters:

```bash
git grep -n "KuzuGraphAdapter"
git grep -n "LeanGraphService"
git grep -n "get_leangraph_service"
git grep -n "KARI_GRAPH_"
git grep -n "RELATED_TO"
git grep -n "SUPERSEDES"
```

When backend/config changes touch deployment:

```bash
docker compose config
```

---

## 18. Exit criteria

MEMORY-GRAPH-2 is complete only when all are true:

- [ ] graph backend truthfully reports durable vs ephemeral state;
- [ ] selected production backend is actively maintained or explicitly pinned by ADR with accepted risk;
- [ ] no silent durable-to-in-memory fallback;
- [ ] graph survives restart or can deterministically rebuild;
- [ ] `max_depth` is real;
- [ ] typed relationship ontology exists;
- [ ] temporal validity/observation semantics exist;
- [ ] stale facts are invalidated rather than destructively erased;
- [ ] point-in-time retrieval works;
- [ ] entity aliases/ambiguity are handled safely;
- [ ] fact/belief/observation/experience classes are distinct;
- [ ] associative retrieval is bounded and explainable;
- [ ] graph candidates integrate through NeuroRecall;
- [ ] NeuroRecall remains final recall-policy owner;
- [ ] graph remains subordinate to governed memory/NeuroVault persistence;
- [ ] procedural/experience relationships are supported;
- [ ] deletion/forgetting propagates to graph projections;
- [ ] tenant isolation tests pass;
- [ ] graph observability is structured and complete;
- [ ] memory-to-behavior transfer benchmark shows measurable benefit;
- [ ] no duplicate graph/memory authority introduced.

---

## 19. Architecture decision

The target is **not** "build a giant knowledge graph."

The target is a bounded cognitive substrate where KAREN can answer four different questions correctly:

1. **What is true now?**
2. **What was true then?**
3. **How is this memory connected to that one?**
4. **What did I learn from what happened before, and should that change what I do now?**

If the graph cannot improve those four abilities with provenance, security, and measurable transfer utility, additional graph complexity is rejected.
