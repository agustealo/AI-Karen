# Memory Architecture

## 1. Core rule

**Memory is the domain. NeuroRecall is how KAREN finds memory. NeuroVault is how KAREN governs durable memory. The Memory Graph is KAREN's relational, temporal, associative projection of governed memory, not a competing memory store or recall authority.**

Do not split these concepts into competing stores, graph facades, or alternate retrieval runtimes.

The graph exists to make relationships, time, causality, contradiction, provenance, and experience structure explicit. It must never become the sole durable source of user memory or bypass the canonical memory persistence path.

## 2. Layers

### STM

Short-term memory holds bounded recent/session context needed for the current conversation/runtime window.

Typical backing: process-bounded state and/or Redis when configured.

Properties:

- bounded;
- session/conversation scoped;
- disposable/rebuildable where possible;
- never the sole source of durable user facts.

### Episodic memory

Meaningful interactions, decisions, outcomes, commitments, and notable events.

Properties:

- durable;
- timestamped/provenanced;
- tenant/user scoped;
- recallable by semantic/contextual strategy;
- governed by deletion/privacy policy;
- eligible for projection into temporal/associative graph structures.

### Semantic / durable LTM

Durable facts, preferences, stable knowledge, user/project information, and generalized knowledge that remains useful beyond a single session.

Properties:

- durable source of truth through canonical memory persistence;
- explicit scope and provenance;
- deduplication/update semantics;
- confidence/verification when appropriate;
- temporal validity where truth can change;
- deletion/export support.

### Procedural memory

Reusable skills, workflows, successful strategies, failure lessons, and learned execution patterns.

Properties:

- outcome-linked where possible;
- versioned when procedures evolve;
- distinct from declarative facts;
- recallable when a current task resembles a prior successful or failed execution pattern.

### Prospective memory

Future-oriented intentions, commitments, deadlines, conditions, and deferred actions.

Properties:

- explicit trigger/condition/time semantics;
- lifecycle state;
- tenant/user scope;
- traceable to the event or decision that created the intention.

## 3. Current data architecture

Canonical durable memory uses PostgreSQL/Supabase-backed storage through KAREN's data adapters where configured. Redis may support ephemeral/session/cache functions.

**Milvus and Elasticsearch are retired from the current memory architecture.** Do not add them to deployment files, docs, recovery plans, or runtime code unless a future ADR explicitly reintroduces them with a proven requirement.

Vector/semantic retrieval should use the canonical storage capabilities selected by the current data layer rather than automatically adding a new database.

### 3.1 Graph storage rule

The Memory Graph is a projection/index over governed memory and experience, not a second independent source of truth.

A graph backend may be embedded or service-based, but the cognitive contracts must remain backend-neutral. Backend choice belongs behind the canonical graph repository/adapter boundary.

The current `KuzuGraphAdapter` name must not be interpreted as proof of durable Kuzu persistence. Until restart-durability tests prove otherwise, graph persistence is considered **unproven**.

Kuzu is not a strategic default merely because legacy configuration names it. Any production graph backend must be selected by an ADR covering:

- maintenance status;
- local-first deployment;
- restart durability;
- multi-process/concurrency requirements;
- typed property-graph support;
- temporal query support;
- traversal performance;
- backup/recovery;
- tenant isolation strategy;
- operational cost.

Do not couple memory cognition to one database product.

## 4. Memory Graph authority

The canonical Memory Graph lives under `core/memory/graph/` and is subordinate to the memory domain.

It owns:

- typed nodes/edges representing memory relationships;
- temporal validity and observation time;
- provenance links back to canonical memory/event records;
- entity resolution/linking contracts;
- contradiction, reinforcement, supersession, support, and derivation links;
- episode/entity/assertion/procedure/goal relationship projection;
- graph traversal primitives;
- graph candidate generation for NeuroRecall;
- associative activation state that is explicitly derived and bounded.

It does not own:

- the canonical durable memory write decision;
- final recall ranking/disposition;
- prompt assembly;
- provider/model execution;
- global reasoning policy;
- user-intent interpretation;
- plugin/tool execution;
- cross-tenant discovery;
- silent memory mutation without provenance/version history.

### 4.1 Required temporal model

Every mutable fact/assertion/relationship that can change in the world must support a bi-temporal or equivalent explicit time model:

- `valid_from`: when the fact became true in the represented world;
- `valid_to`: when it stopped being true, if known;
- `observed_at`: when KAREN observed/learned it;
- `recorded_at`: when KAREN persisted/projected it;
- provenance/source reference;
- lifecycle state.

Superseding a fact must close or invalidate the prior validity interval rather than deleting history.

Point-in-time recall must be possible without mixing stale and current truth.

### 4.2 Required graph vocabulary

The graph schema must evolve beyond generic `RELATED_TO` relationships. Canonical relationship families should include typed semantics for at least:

- identity / alias / same-as;
- mention / participation;
- temporal ordering / follows / precedes;
- belongs-to / part-of;
- support / evidence-for / derived-from;
- contradiction / supersession / correction;
- causality / contributed-to / resulted-in;
- preference / belief / opinion with confidence and ownership;
- task / goal / decision / outcome;
- procedure / strategy / failure-mode;
- project / artifact / component relationships.

Relationship types must be registered and schema-validated. Free-form edge labels are not a substitute for a domain vocabulary.

### 4.3 Fact vs belief vs observation

KAREN must not flatten all remembered statements into the same epistemic class.

At minimum, memory graph projections must distinguish:

- **world facts**: externally grounded statements;
- **observations**: what KAREN/user/system observed at a time;
- **user beliefs/preferences**: subjective user-owned state;
- **KAREN hypotheses/opinions**: model-derived state with confidence and evidence;
- **experiences/outcomes**: records of what happened after an action;
- **procedures/lessons**: generalized strategy learned from experiences.

A belief changing is not the same as a world fact changing.

### 4.4 Graph evolution

Graph writes are not append-only decoration. New evidence may:

- reinforce an assertion;
- lower confidence;
- contradict it;
- supersede it;
- split one entity into two;
- merge aliases into one canonical entity;
- create a generalized observation from repeated episodes;
- link a task outcome to a reusable procedural lesson.

All evolution must preserve provenance and history.

## 5. NeuroRecall

NeuroRecall owns retrieval strategy, not persistence authority.

It may own:

- query formulation;
- scope selection;
- candidate retrieval coordination;
- semantic, lexical, temporal, graph, episodic, procedural, and case-based candidate fusion;
- ranking/scoring;
- recency/relevance tradeoffs;
- recall budgets;
- deduplication/selection;
- contradiction-aware candidate handling;
- evidence diversity;
- recall reason metadata;
- recall abstention;
- transfer/outcome utility feedback.

It must not:

- create a duplicate durable memory schema;
- bypass tenant/user scope;
- own message persistence;
- become a second vector database abstraction when canonical data adapters already exist;
- own graph persistence;
- mutate graph truth as a side effect of retrieval.

### 5.1 Graph-assisted recall

The graph is one candidate source among several. NeuroRecall decides when graph retrieval is useful and how much weight it receives.

Target retrieval flow:

```text
RecallRequest
   -> query/entity/temporal planning
   -> parallel candidate sources
      -> semantic/vector
      -> lexical
      -> episodic
      -> temporal
      -> graph traversal
      -> procedural/experience
   -> source-local scores
   -> graph/associative expansion where useful
   -> contradiction/current-validity filtering
   -> evidence fusion + diversity
   -> transfer-utility ranking
   -> budget-aware packing or abstention
```

Graph distance alone is never a final relevance score.

## 6. Associative memory and spreading activation

Associative activation is a retrieval mechanism, not durable truth.

A production spreading-activation implementation should account for:

- typed edge weights;
- temporal validity;
- recency/decay;
- confidence;
- salience;
- source reliability;
- traversal depth penalty;
- cycle/loop suppression;
- tenant/user scope;
- activation budget;
- diversity and redundancy;
- negative/inhibitory evidence where appropriate.

Activation must be bounded and explainable through reason metadata such as path, edge types, depth, and source memory IDs.

Pattern completion is allowed only with explicit uncertainty. Partial cues may retrieve likely episodes/entities, but the system must not convert inferred completion into an asserted fact without evidence.

Pattern separation must protect similar but distinct episodes from being merged merely because their embeddings or entities are similar.

## 7. NeuroVault

NeuroVault is the governance layer around durable memory.

It may coordinate:

- persistence policy;
- archive/retention;
- backup/recovery semantics;
- deletion/forgetting workflows;
- data export/governance;
- integrity/recovery controls;
- graph projection rebuild triggers;
- lifecycle transitions such as active, stale, superseded, invalid, quarantined, archived, and expired.

It does not replace the canonical memory domain or invent another storage system.

Deleting governed memory must also remove or invalidate graph projections derived solely from that memory unless retention policy requires an auditable tombstone.

## 8. Consolidation, reconsolidation, and forgetting

Human-like memory behavior requires lifecycle dynamics, not only storage and retrieval.

### Consolidation

Repeated or related episodic experiences may produce generalized semantic/procedural memories when evidence is sufficient.

```text
repeated episodes
   -> cluster / compare
   -> identify stable pattern
   -> create generalized memory candidate
   -> provenance links to supporting episodes
   -> governed persistence
   -> graph projection
```

### Reconsolidation

Recalling a memory does not authorize silent overwrite. New evidence may generate a revised memory version while preserving historical state and source provenance.

### Forgetting

Forgetting is a governed lifecycle operation. Low-value, redundant, stale, invalid, or expired memories may be pruned/archived according to policy.

Do not use raw recency alone. Retention policy may consider:

- user significance;
- recurrence;
- successful transfer to future tasks;
- confidence;
- causal importance;
- uniqueness/redundancy;
- age/staleness;
- policy/legal retention;
- explicit user pinning/deletion.

## 9. Experience memory

KAREN must remember not only conversation facts but **what actions were tried, what happened, and what should change next time**.

Experience records should be able to connect:

```text
goal
 -> plan/strategy
 -> actions/tools/models
 -> environment/context
 -> outcome
 -> failure/success signals
 -> lesson/procedure
 -> future transfer evidence
```

This supports real-world behavior where previous failures, UI/environment affordances, workflow gotchas, and learned strategies change later actions.

## 10. Runtime memory flow

```text
ChatRuntime
   -> CORTEX recall eligibility/scope signal
   -> NeuroRecall strategy
   -> canonical memory repositories/adapters
   -> optional temporal/graph/associative candidate sources
   -> ranked memory evidence
   -> prompt/context assembly

response/action lifecycle
   -> outcome/evidence collection
   -> memory-candidate evaluation
   -> NeuroVault-governed persistence
   -> graph projection/evolution from committed memory
   -> consolidation/reconsolidation candidates
   -> audit/telemetry
```

The graph is updated from committed/governed memory events or explicitly governed projections. Routes, agents, ICE, and providers do not write graph state directly.

## 11. Scope and security

Every memory and graph access must explicitly preserve applicable:

- user ID;
- tenant ID;
- workspace/project scope;
- conversation/session scope;
- authorization context;
- deletion/privacy status;
- provenance visibility;
- memory namespace/class.

Never use `tenant_id="default"` as a production security fallback.

Cross-tenant recall or graph traversal is a critical defect.

Graph/entity identifiers must not enable cross-tenant collisions or inference leaks.

## 12. What gets remembered

Do not persist every token as LTM or every extracted noun as a graph entity.

Good durable candidates include:

- explicit preferences;
- stable personal/project facts useful later;
- decisions/commitments;
- durable configuration choices;
- important task outcomes;
- meaningful episodic events;
- recurring failure modes;
- procedures/lessons that improve later execution;
- relationships with temporal or causal value.

Poor candidates include:

- transient chit-chat;
- secrets/passwords/tokens;
- raw hidden reasoning;
- duplicate facts with no changed meaning;
- unverified guesses presented as facts;
- low-value entity mentions with no future retrieval utility.

## 13. Persistence truth

When persistence is enabled, save operations must be real. The UI must never show a fake "saved" state when the backend write failed.

A graph backend that only stores nodes/edges in process memory must not emit telemetry claiming durable graph persistence.

Persistence metadata should capture provider/model/runtime details where relevant for provenance and diagnostics.

## 14. Observability

Memory graph operations should emit structured events including applicable:

- `correlation_id`;
- `request_id`;
- `tenant_id`;
- `user_id`;
- `conversation_id`;
- source memory/event ID;
- graph operation;
- node/edge counts;
- traversal strategy/depth;
- candidate count;
- temporal filters;
- contradiction/supersession actions;
- backend;
- latency;
- degraded state;
- error type/code.

Required event families include:

- graph projection start/complete/fail;
- entity resolution start/complete/conflict;
- graph recall start/complete/abstain;
- graph evolution/supersession;
- graph rebuild/recovery;
- graph backend unavailable/degraded.

## 15. Recovery

PostgreSQL/Supabase backup covers the durable relational store only. Redis, object storage, graph stores, model artifacts, and external services are separate recovery domains unless explicitly included.

Graph recovery must support one of two proven modes:

1. backup/restore of the selected durable graph backend; or
2. deterministic rebuild from canonical governed memory/event records.

Prefer rebuildable projections where practical so the graph does not become an irreplaceable second source of truth.

## 16. Tests

Memory work should prove:

- tenant isolation;
- write/read persistence;
- restart durability;
- graph backend actually persists when configured as durable;
- multi-hop traversal respects depth and scope;
- temporal point-in-time retrieval;
- stale fact invalidation/supersession;
- contradiction preservation;
- provenance back to canonical memory/event IDs;
- entity alias resolution and collision safety;
- pattern separation for similar episodes;
- bounded associative activation;
- graph candidate contribution to NeuroRecall;
- final recall remains NeuroRecall-owned;
- experience memory changes later task behavior where expected;
- deletion/forget propagation into graph projections;
- graph rebuild from canonical memory;
- no legacy Milvus/Elasticsearch authority;
- no duplicate memory facade/store;
- runtime recall integration;
- failure reporting rather than fake save success.

Recommended benchmark coverage includes conversational recall, temporal reasoning, multi-hop association, experience reuse, environment/workflow memory, and multi-session action tasks. LoCoMo-style recall alone is insufficient proof of human-like memory behavior.
