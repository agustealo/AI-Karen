# MEMORY-FORMATION-1 Developer Sheet

> **Status:** READY FOR EXECUTION
> **Priority:** P0 memory architecture closure before additional graph technology
> **Scope:** memory formation, episodic segmentation, state transitions, contextual intent, provenance reconstruction, temporal consolidation, belief revision, recall evidence packing, behavioral proof
> **Authority:** `docs/development/MEMORY.md`, `docs/development/MEMORY_GRAPH_DEV_SHEET.md`, `PROJECT_DEV_MANIFEST.md`
> **Core rule:** The graph is not the memory formation engine. Raw interaction streams are first converted into governed events/state transitions; the graph is a relational projection of those canonical memories. NeuroRecall remains recall-policy authority and NeuroVault remains durable-persistence governance.

---

## 1. Why this sprint exists

The live repository already contains memory types, NeuroRecall, graph projection, associative spreading activation, consolidation rules, and PostgreSQL recall. The missing production bridge is the protocol that turns ongoing interaction into coherent, evolving experience.

Current graph work is insufficient if it performs:

```text
raw message -> entities/assertion -> graph edges
```

Target memory formation is:

```text
interaction / observation / action
        -> event boundary detection
        -> state + contextual intent
        -> structured episodic event
        -> canonical memory write
        -> temporal/epistemic updates
        -> graph projection
        -> consolidation / abstraction
        -> NeuroRecall evidence reconstruction
        -> future behavior
```

This sprint must be completed before adding NetworkX, a dedicated graph database, Mem0, Graphiti, Hindsight runtime, or another memory framework.

---

## 2. Research-backed design inputs

### 2.1 CompassMem / Event Graphs (ACL 2026)

Adopt the principle that experience should be incrementally segmented into events and linked through explicit logical relations. Retrieval should navigate the resulting event graph as a logic map rather than rely only on shallow semantic similarity.

KAREN adaptation:

- event segmentation belongs to canonical memory formation;
- event graph projection belongs to `core/memory/graph`;
- goal-directed graph navigation produces candidates for NeuroRecall;
- graph traversal never becomes final recall authority.

### 2.2 SEEM / Structured Episodic Event Memory (ACL 2026)

Adopt:

- structured episodic event frames;
- precise provenance pointers;
- hierarchical relation between episodic narrative and graph facts;
- reverse provenance expansion to reconstruct coherent context from fragmented evidence.

KAREN adaptation:

A graph hit should normally return source IDs/path evidence, not synthetic pseudo-memory text. NeuroRecall may expand selected source memories/episode frames through provenance before prompt packing.

### 2.3 STITCH / Contextual Intent (ACL 2026)

Adopt compact intent/state indexing to reduce interference between semantically similar experiences.

Each memory event should be able to carry:

- goal/intent segment;
- action type;
- salient entity types/IDs;
- task/project/workspace context;
- relevant constraints;
- state fingerprint/features.

These are retrieval cues, not a second global intent authority. CORTEX remains executive authority.

### 2.4 Hindsight (ACL 2026)

Adopt the separation of epistemic classes and explicit memory operations.

KAREN mapping:

```text
world       -> semantic facts / assertions
experience  -> episodic + action/outcome memory
observation -> observations/evidence
opinion     -> beliefs/preferences/hypotheses with confidence
```

Use the conceptual operations:

```text
RETAIN  -> governed memory formation/write
RECALL  -> NeuroRecall
REFLECT -> consolidation/revision/lesson formation through canonical runtime
```

Do not introduce Hindsight as a parallel runtime.

### 2.5 Temporal Semantic Memory (ACL 2026)

Adopt semantic/world time instead of only conversation timestamp. Support durative memories formed by consolidating temporally continuous, semantically compatible states.

Examples:

- `user lived in Detroit from X to Y` is a duration, not thousands of repeated point memories;
- `project used provider X during release cycle Y` can become a durative state;
- state changes close prior validity intervals rather than erase history.

### 2.6 EVU / Belief intervention (ACL 2026)

Adopt an Estimate/Verify/Update pattern for beliefs and learned expectations:

```text
prior belief / expectation
      -> predicted outcome
      -> observed outcome
      -> verification evidence
      -> strengthen | weaken | revise | supersede
```

Never allow old learned beliefs to persist merely because they were recalled frequently.

### 2.7 MCMA / Meta-cognitive memory abstraction (ACL 2026)

Adopt abstraction levels, but do not add a learned memory copilot yet.

KAREN target levels:

```text
L0 raw source/reference
L1 observation/action
L2 event/episode
L3 fact/state/preference
L4 procedure/lesson
L5 generalized strategy/pattern
```

Promotion must be evidence-backed and reversible to provenance. Learned abstraction policy is a later benchmark-gated capability.

### 2.8 MemoryArena + LongMemEval-V2

Evaluation must prove that memory changes future behavior, including:

- dynamic state tracking;
- workflow knowledge;
- recurring gotchas;
- premise awareness;
- multi-session interdependence;
- preference/constraint retention;
- use of prior action feedback in later action selection.

---

## 3. Live repo findings addressed by this sprint

### MF-F01 — episodic domain is effectively empty

The live `core/memory/episodic/` directory currently exposes only `__init__.py`. There is no active first-class event/episode builder in that domain.

**Consequence:** the graph currently has no canonical episodic segmentation authority feeding it.

**Priority:** CRITICAL.

### MF-F02 — consolidation is a shallow promotion ruleset

Current consolidation primarily checks reuse count, explicit save, repeated tool success, correction, and low confidence.

Useful as policy gates, but insufficient for:

- event grouping;
- durative state formation;
- contradiction resolution;
- temporal interval closure;
- abstraction/generalization;
- belief revision;
- provenance-preserving semanticization.

**Priority:** HIGH.

### MF-F03 — graph recall loses narrative evidence

Current graph retrieval can produce graph result dictionaries which are wrapped into new `MemoryEntry` objects. This weakens provenance and can turn relationships into pseudo-memory content.

Target behavior: graph retrieval returns canonical source IDs + paths; selected sources are expanded from canonical memory and packed with explicit evidence provenance.

**Priority:** CRITICAL.

### MF-F04 — contextual intent/state is not first-class on memory events

Current memory retrieval is mainly query/text scoped. Similar entities across different tasks/projects/goals can interfere.

**Priority:** HIGH.

---

## 4. Canonical Memory Formation Pipeline

```text
Runtime observation
(messages, user changes, tool results, actions, environment state)
        |
        v
MemoryFormationService
        |
        +--> EventSegmenter
        |       determines boundary / continuation
        |
        +--> ContextualStateEncoder
        |       goal, action type, project, entities, constraints, state cues
        |
        +--> EpistemicClassifier
        |       fact | observation | belief | preference | experience
        |
        +--> TemporalNormalizer
        |       event time, valid interval, observed/recorded time
        |
        +--> ProvenanceBinder
        |       exact source messages/actions/tool outputs
        |
        v
StructuredMemoryEvent / EpisodeFrame
        |
        v
Runtime memory policy
        |
        v
NeuroVault
        |
        v
Canonical PostgreSQL/Supabase memory
        |
        +--> pgvector representation
        +--> graph projection
        +--> lifecycle/consolidation candidates
```

`MemoryFormationService` owns formation mechanics only. It must not become CORTEX, NeuroRecall, or NeuroVault.

---

## 5. Structured Episodic Event Contract

Create one canonical typed event/episode contract, reusing existing memory/cognitive/time/confidence authorities.

Required concept set:

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

goal_id / contextual_intent
action_type
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
temporal_neighbor_ids
confidence
importance/salience
lifecycle_state
schema_version
```

Do not duplicate full raw message/tool payloads inside the event when a canonical source reference exists.

---

## 6. Event Segmentation

Implement bounded deterministic-first segmentation.

Boundary signals may include:

- explicit topic/task change;
- goal change;
- project/workspace change;
- meaningful time gap;
- tool/action sequence completion;
- success/failure outcome;
- user correction;
- commitment/decision;
- environment state transition;
- conversation/session boundary.

Start with rules + canonical intent/state signals. Do not add an LLM call for every message by default.

Optional model-assisted segmentation is permitted only behind a prompt contract and budget/config gate.

Proof:

- same task over multiple turns becomes one coherent episode;
- task switch creates new event/episode;
- correction can attach to prior event without merging unrelated context;
- identical entity mention under another goal does not force episode merge.

---

## 7. State-aware / intent-aware indexing

Store compact retrieval cues, not hidden reasoning.

Suggested typed cues:

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

NeuroRecall may use compatibility between current authorized CORTEX/runtime context and stored cues as one ranking/filtering signal.

Intent compatibility score is separate from semantic similarity and truth confidence.

---

## 8. Temporal state and durative memory

Support point events and intervals.

Formation flow:

```text
new observation
 -> find compatible active state
 -> same state? extend/reinforce interval
 -> changed state? close old interval + create new state
 -> uncertain? retain separate observation without forced transition
```

No destructive rewrite of historical state.

Examples to test:

- preference changed and later reverted;
- project provider changed twice;
- user location changed;
- recurring workflow remained stable for months;
- uncertain state update remained unconfirmed.

---

## 9. Provenance-first retrieval and reconstruction

Introduce source-preserving graph candidate retrieval.

Graph candidate result must contain at minimum:

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

It must not invent a new UUID-backed pseudo memory to stand in for canonical source content.

### Reverse provenance expansion

After NeuroRecall selects graph/event candidates:

```text
candidate/path
 -> canonical source IDs
 -> source memory/episode fetch
 -> bounded neighboring episode expansion when needed
 -> dedupe
 -> temporal ordering
 -> evidence packing
```

This reconstructs coherent episodes without stuffing entire history into context.

---

## 10. Belief revision / reconsolidation

Create a typed revision decision:

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

- prior assertion/belief;
- new observation/evidence;
- provenance strength;
- contradiction/support relation;
- temporal compatibility;
- user confirmation/correction;
- outcome verification.

Durable revisions pass through runtime policy + NeuroVault.

Never overwrite history without preserving supersession/provenance.

---

## 11. Hierarchical consolidation

Target transformations:

```text
raw references
 -> observations/actions
 -> episode
 -> semantic fact/state
 -> procedure/lesson
 -> generalized strategy
```

Promotion criteria should combine evidence such as:

- repetition across independent episodes;
- confirmed successful outcomes;
- user confirmation;
- correction history;
- temporal stability;
- cross-context transfer success;
- source confidence;
- contradiction count.

Do not promote merely because a memory was recalled frequently.

---

## 12. Lean Supabase/Postgres implementation

Do not introduce a second database for MEMORY-FORMATION-1.

Use existing PostgreSQL/Supabase authority plus available native capabilities:

- canonical relational memory tables;
- pgvector for semantic candidates;
- PostgreSQL FTS/`pg_trgm` where approved for lexical/entity candidates;
- canonical edge relation tables for graph projection;
- recursive CTEs for bounded graph traversal;
- RLS/tenant predicates for isolation.

Graph projection should reference canonical memory/event IDs rather than duplicate source memory text.

External graph compute remains benchmark-gated.

---

## 13. Implementation tasks

### Task 1 — Episodic authority

Do:

- establish `core/memory/episodic` as the owner of event/episode contracts + segmentation;
- implement canonical event frame types;
- implement deterministic-first event segmentation;
- bind exact provenance/source references.

Avoid:

- new memory manager/orchestrator;
- graph-specific episode builder;
- provider-specific event extraction.

### Task 2 — Formation service

Do:

- implement one `MemoryFormationService` or equivalently named subordinate service under `core/memory`;
- accept runtime observations and return typed candidates/events;
- integrate contextual state, epistemic classification, temporal normalization and provenance.

Authority:

- Runtime invokes it;
- CORTEX may supply intent/goal signals but does not perform writes;
- NeuroVault governs durable commits.

### Task 3 — Postgres event persistence

Do:

- persist event/episode structures in the canonical data layer;
- preserve tenant/user scope;
- add relevant temporal, provenance and cue indexes;
- use migrations, not runtime schema creation.

### Task 4 — Graph projection rewrite

Do:

- project canonical event/fact/entity references;
- eliminate pseudo-durable Kuzu behavior;
- make graph projection rebuildable from canonical Postgres memory;
- graph hits return source refs/path evidence.

### Task 5 — NeuroRecall reconstruction

Do:

- add event/graph candidate source(s) through existing NeuroRecall retriever contracts;
- implement provenance expansion;
- add contextual-intent/state compatibility as bounded ranking signals;
- preserve temporal ordering and source evidence.

### Task 6 — Temporal/durative consolidation

Do:

- close/extend state intervals;
- build durative memories from repeated continuous evidence;
- preserve point observations behind consolidated state;
- add contradiction/supersession handling.

### Task 7 — belief revision

Do:

- implement evidence-backed reconsolidation decisions;
- distinguish belief/preferences from world facts;
- feed user corrections and observed outcomes into revision;
- prevent frequency-only belief reinforcement.

### Task 8 — behavioral benchmark

Build KAREN-specific longitudinal fixtures in addition to external benchmark adapters.

Minimum scenarios:

1. preference change over time;
2. repeated entity under different goals/projects;
3. tool failure learned and avoided later;
4. successful procedure reused later;
5. incorrect prior belief corrected by evidence;
6. multi-turn episode reconstructed from fragmentary query;
7. tenant isolation during multi-hop expansion;
8. stale state excluded from current answer but available historically;
9. current action changes because of prior outcome;
10. irrelevant semantically similar memory suppressed by contextual intent.

---

## 14. Required telemetry

Structured events should include applicable:

```text
memory.formation.started/completed
memory.event.boundary_detected
memory.episode.created/extended
memory.state.transitioned
memory.provenance.bound
memory.graph.projected
memory.recall.provenance_expanded
memory.consolidation.decided
memory.revision.decided
memory.behavior_transfer.recorded
```

Carry correlation/request/user/tenant/session/conversation IDs according to canonical observability contracts. Do not log secrets or raw sensitive content unnecessarily.

---

## 15. Security / RBAC proof

Prove:

- every source reference remains tenant scoped;
- recursive graph/provenance expansion cannot cross tenant boundaries;
- deletion propagates to projections and derived memories according to governance policy;
- quarantined/invalid source evidence cannot silently re-enter through graph paths;
- user corrections are provenance-preserving and auditable;
- no hidden chain-of-thought is persisted as memory.

---

## 16. Exit criteria

MEMORY-FORMATION-1 is complete only when:

- raw interaction streams form coherent typed episodes;
- event segmentation is test-proven;
- contextual intent/state is available as a retrieval cue;
- graph projection is sourced from canonical memories/events;
- graph hits expand back to canonical evidence;
- current vs historical state is distinguishable;
- beliefs can strengthen/weaken/revise/supersede from evidence;
- consolidation produces provenance-backed higher abstractions;
- a prior successful/failed experience measurably changes a later action/plan;
- all graph/provenance traversal is tenant-safe;
- no new graph database or external memory framework is required to pass the baseline.

---

## 17. Proof commands

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Add focused suites for:

```text
tests/memory/test_event_segmentation.py
tests/memory/test_episode_formation.py
tests/memory/test_contextual_intent_recall.py
tests/memory/test_temporal_state_transition.py
tests/memory/test_provenance_expansion.py
tests/memory/test_belief_revision.py
tests/memory/test_memory_behavior_transfer.py
tests/memory/test_memory_graph_tenant_isolation.py
```

Use existing test organization if equivalent files already exist; do not create duplicates solely to match these suggested names.

---

## 18. Architectural north star

```text
Experience is not a message.
Memory is not an embedding.
The graph is not the source of truth.
Similarity is not relevance.
Activation is not confidence.
Recall is not learning.
Frequency is not truth.

KAREN memory becomes human-like when it can:
segment experience,
place it in context,
preserve where it came from,
track what changed,
connect cause to outcome,
revise beliefs,
abstract lessons,
and use those lessons differently the next time.
```
