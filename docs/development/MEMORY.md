# Memory Architecture

## 1. Core rule

**Memory is the domain. NeuroRecall is how KAREN finds memory. NeuroVault is how KAREN governs durable memory. Redis is the bounded STM/runtime-memory substrate. Supabase-hosted PostgreSQL is the durable episodic/LTM/graph source of truth. The Memory Graph is a relational, temporal, associative projection over governed durable memory, not a competing store or recall authority.**

Do not split these responsibilities into competing stores, graph facades, alternate recall runtimes, or direct provider/plugin persistence paths.

The graph exists to make relationships, time, causality, contradiction, provenance, and experience structure explicit. It must never become the sole durable source of user memory or bypass the canonical memory persistence path.

---

## 2. Actual deployed memory stack

KAREN's current memory architecture is intentionally hybrid:

```text
                     CORTEX
              recall eligibility/scope
                        |
                        v
                     Runtime
                        |
                        v
                   NeuroRecall
          +-------------+-------------+
          |                           |
          v                           v
   Redis STM/runtime           Durable memory
   session continuity          Supabase/PostgreSQL
   bounded hot context         via canonical PostgresEngine
          |                           |
          |                    +------+------+
          |                    |             |
          |                    v             v
          |               assertions      episodes/LTM
          |                    |             |
          |                    +------+------+
          |                           |
          |                           v
          |                 temporal/graph projection
          |                           |
          +-------------+-------------+
                        |
                        v
                 NeuroRecall fusion
```

### 2.1 Redis ownership

Redis is **active**, not retired.

Canonical implementation lives under:

`src/ai_karen_engine/platform/memory/redis/`

The legacy import path under `core/memory/redis_connection_manager.py` is only a compatibility shim and must be removed at its documented sunset. Removing the shim does **not** mean removing Redis.

Redis owns only bounded/ephemeral state such as:

- session continuity;
- recent-turn summaries;
- short-term/working memory;
- hot recall/cache data;
- short-lived runtime coordination state where explicitly approved.

Redis must not become the sole durable owner of user facts, episodic history, procedures, beliefs, or long-term graph truth.

Redis degradation may fall back to bounded process memory where the existing platform adapter explicitly supports it, but degraded cache state must never be presented as durable persistence.

### 2.2 Supabase/PostgreSQL ownership

Supabase-hosted PostgreSQL is the durable memory authority.

KAREN does **not** create a second direct Supabase SDK memory runtime. Durable memory accesses reuse the existing canonical database path:

```text
memory service
  -> platform memory Postgres adapter
  -> database.client compatibility facade
  -> canonical persistence.postgres.PostgresEngine
  -> Supabase-hosted PostgreSQL
```

SQLAlchemy async sessions and migrations are part of this existing data path. Schema changes are migration-owned. Runtime table creation is forbidden in production.

Supabase/PostgreSQL owns durable:

- memory assertions/facts;
- episodic events;
- semantic/LTM records;
- preferences/beliefs where governed;
- procedures/lessons;
- prospective-memory records where durable;
- provenance/source references;
- graph relationships and temporal state;
- vector representations where pgvector is enabled.

### 2.3 Native PostgreSQL/Supabase capabilities

Prefer native capabilities before introducing another service:

- pgvector for semantic retrieval;
- PostgreSQL full-text search;
- pg_trgm where approved for alias/fuzzy entity matching;
- recursive CTEs for bounded multi-hop graph traversal;
- relational indexes for graph edges and temporal validity;
- RLS and explicit tenant/user predicates for isolation;
- pgTAP where useful for DB invariants;
- pg_cron only when a real scheduled memory-maintenance workload has been proven.

Do not introduce a second graph/vector database until benchmarks prove the native stack insufficient.

Milvus and Elasticsearch remain retired from the current memory architecture.

---

## 3. Memory layers

### STM / working memory

Backing: **Redis** through the canonical platform adapter, with explicitly bounded degraded in-process fallback.

Properties:

- bounded;
- session/conversation scoped;
- TTL/eviction aware;
- disposable/rebuildable where possible;
- optimized for hot/recent context;
- never the sole source of durable user facts.

### Episodic memory

Backing: **Supabase/PostgreSQL**.

Meaningful interactions, decisions, actions, outcomes, commitments, and notable events.

Properties:

- durable;
- timestamped/provenanced;
- tenant/user scoped;
- reconstructable from source references;
- recallable by semantic/contextual/temporal/graph strategy;
- governed by deletion/privacy policy;
- eligible for graph projection and consolidation.

### Semantic / durable LTM

Backing: **Supabase/PostgreSQL**.

Durable facts, preferences, stable knowledge, project information, and generalized knowledge.

Properties:

- canonical durable source of truth;
- explicit scope and provenance;
- deduplication/update semantics;
- confidence/verification when appropriate;
- temporal validity when truth can change;
- deletion/export support.

### Procedural memory

Backing: **Supabase/PostgreSQL** once promoted from evidence-backed episodes/outcomes.

Reusable workflows, successful strategies, failure lessons, and learned execution patterns.

### Prospective memory

Durable prospective items belong in **Supabase/PostgreSQL**. Short-lived session reminders/state may be mirrored in Redis when useful, but Redis is not the authoritative record for durable commitments.

---

## 4. Memory formation before graph formation

Raw messages are not automatically episodes, and entity extraction is not memory understanding.

Target formation flow:

```text
interaction / observation / action
        -> event boundary detection
        -> contextual goal/state cues
        -> epistemic classification
        -> temporal normalization
        -> provenance binding
        -> StructuredMemoryEvent / Episode
        -> governed durable commit to Supabase/Postgres
        -> graph projection
        -> consolidation/revision candidates
```

Redis participates before durable formation as the hot context source. Formation may use the current bounded session window from Redis to decide whether a new observation continues an episode or starts a new one.

Redis must not independently create durable semantic truth.

---

## 5. Memory Graph authority

The canonical Memory Graph lives under `core/memory/graph/` and is subordinate to the memory domain.

### 5.1 Physical implementation target

For the current architecture, the default target is **PostgreSQL-native graph relationships**, not a second graph database.

Use canonical durable records plus graph relation tables such as:

```text
memory_edges
entity_aliases
source/provenance references
```

Do not duplicate complete memory text into a second `memory_nodes` authority when the canonical memory row already exists. Graph records should reference canonical IDs wherever possible.

The existing Kuzu-facing implementation is legacy/experimental and must not be treated as the production target. Any in-memory graph adapter is test/dev-only unless explicitly configured as ephemeral.

### 5.2 Graph owns

- typed relationship contracts;
- graph edge persistence/projection;
- temporal validity of relationships;
- provenance links back to canonical durable memory/event records;
- entity linking/alias contracts;
- contradiction, reinforcement, supersession, support, and derivation links;
- bounded traversal primitives;
- graph candidate generation for NeuroRecall;
- derived associative activation inputs.

### 5.3 Graph does not own

- canonical durable memory write decisions;
- final recall ranking/disposition;
- prompt assembly;
- provider/model execution;
- global reasoning policy;
- durable STM/session state;
- user-intent interpretation;
- plugin/tool execution;
- cross-tenant discovery;
- silent truth mutation.

### 5.4 Temporal model

Mutable facts/assertions/relationships must support explicit world time and observation time:

- `valid_from`;
- `valid_to`;
- `observed_at`;
- `recorded_at`;
- provenance/source reference;
- lifecycle state.

Superseding a fact closes or invalidates the previous validity interval rather than deleting history.

### 5.5 Required relationship semantics

Canonical families should include typed semantics for:

- identity / alias / same-as;
- mention / participation;
- temporal ordering;
- belongs-to / part-of;
- support / evidence / derivation;
- contradiction / supersession / correction;
- causality / contribution / result;
- task / goal / decision / outcome;
- preference / belief / opinion ownership;
- procedure / strategy / failure mode;
- project / artifact / component relationships.

---

## 6. Epistemic separation

KAREN must not flatten all remembered statements into the same class.

At minimum distinguish:

- **world facts**;
- **observations**;
- **user beliefs/preferences**;
- **KAREN hypotheses/opinions**;
- **experiences/outcomes**;
- **procedures/lessons**.

A belief changing is not the same thing as a world fact changing.

---

## 7. NeuroRecall

NeuroRecall remains the single recall-policy authority.

Candidate sources may include:

- Redis STM/hot context;
- durable PostgreSQL lexical/relational recall;
- pgvector semantic recall;
- episodic retrieval;
- temporal retrieval;
- graph traversal;
- procedural/experience retrieval.

Target flow:

```text
RecallRequest
   -> authorized scope + current runtime/CORTEX cues
   -> parallel candidate sources
      -> Redis STM
      -> Postgres lexical/semantic
      -> episodic
      -> temporal
      -> graph
      -> procedural/experience
   -> source-local scores
   -> associative expansion where useful
   -> temporal/contradiction filtering
   -> provenance reconstruction
   -> NeuroRecall fusion/ranking
   -> budget-aware packing or abstention
```

Redis or Postgres adapters do not independently decide final recall disposition.

---

## 8. Associative memory

Reuse and harden KAREN's existing spreading-activation capability before adding NetworkX or another graph-compute library.

Production associative activation must eventually account for:

- typed edge weights;
- temporal validity;
- recency/decay;
- confidence;
- salience;
- source reliability;
- traversal depth penalty;
- cycle suppression;
- tenant/user scope;
- activation budget;
- diversity/redundancy;
- negative/inhibitory evidence where appropriate.

Activation score is not truth confidence.

Pattern completion must remain explicitly uncertain. Pattern separation must protect similar but distinct episodes from accidental merge.

---

## 9. NeuroVault and persistence governance

NeuroVault governs durable memory operations against the canonical Postgres data layer.

It may coordinate:

- persistence policy;
- archive/retention;
- backup/recovery;
- deletion/forgetting;
- export/governance;
- integrity/recovery controls;
- graph projection rebuild triggers;
- lifecycle transitions.

Redis writes are not NeuroVault durable writes unless they mirror or cache a durable object that has separately passed the canonical persistence path.

Deleting durable memory must invalidate/remove derived graph projections according to governance policy.

---

## 10. Consolidation, reconsolidation, and forgetting

Repeated episodic evidence may produce generalized semantic/procedural memory:

```text
Redis/session context
   -> formed episodes
   -> Supabase/Postgres durable evidence
   -> cluster/compare
   -> generalized candidate
   -> provenance links
   -> NeuroVault-governed commit
   -> graph update
```

Reconsolidation produces versioned revision rather than silent overwrite.

Forgetting is governed. Consider usefulness, recurrence, transfer success, confidence, causal importance, redundancy, age/staleness, policy retention, and explicit user deletion/pinning.

Redis TTL eviction is **cache/STM expiry**, not durable forgetting.

---

## 11. Experience memory

KAREN must remember not only facts but what actions were tried, what happened, and what should change next time.

Durable experience records should connect:

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

Redis may hold the live action sequence while an episode is still unfolding. Once the episode is closed/eligible, the durable representation belongs in Supabase/PostgreSQL.

---

## 12. Runtime memory flow

```text
ChatRuntime
   -> CORTEX recall eligibility/scope
   -> NeuroRecall
       -> Redis STM candidate source
       -> Supabase/Postgres durable candidate source
       -> temporal/graph/procedural candidate sources
   -> ranked evidence
   -> prompt/context assembly

response/action lifecycle
   -> Redis receives bounded current-session state
   -> MemoryFormation evaluates event/episode boundaries
   -> memory candidates
   -> NeuroVault-governed durable commit to Supabase/Postgres
   -> graph projection/evolution
   -> consolidation/revision candidates
   -> audit/telemetry
```

Routes, agents, ICE, providers, and plugins do not write durable memory or graph truth directly.

---

## 13. Scope and security

Every Redis and Postgres memory access must preserve applicable:

- tenant ID;
- user ID;
- workspace/project scope;
- conversation/session scope;
- authorization context;
- deletion/privacy state;
- provenance visibility;
- memory namespace/class.

Never use `tenant_id="default"` as a production security fallback.

Redis key construction must remain tenant/user scoped. PostgreSQL queries and recursive graph expansion must enforce the same scope at every traversal step. RLS may add defense in depth but does not replace application/runtime scope contracts.

Cross-tenant recall or graph traversal is a critical defect.

---

## 14. Persistence truth and observability

The UI must never report durable save success because a Redis cache write succeeded.

Observability should distinguish at least:

- `memory_source=redis_stm`;
- `memory_source=postgres_durable`;
- `memory_source=graph_projection`;
- `degraded_mode`;
- `degradation_reason`;
- candidate counts by source;
- correlation/request/tenant/user/session/conversation IDs;
- graph traversal depth/path;
- persistence status;
- latency.

When Redis is unavailable, emit explicit STM degradation. Durable Postgres memory remains independently authoritative.

When Postgres/Supabase is unavailable, Redis may maintain bounded continuity, but the system must not claim durable persistence.

---

## 15. Recovery

Supabase/PostgreSQL backup/recovery covers durable memory and PostgreSQL-native graph relations when included in the database schema.

Redis is a separate recovery domain and should be treated as reconstructable/ephemeral unless a deployment explicitly configures Redis persistence for operational continuity. Redis persistence does not promote it to durable memory authority.

Prefer PostgreSQL-native/rebuildable graph projections so graph recovery follows the same durable backup domain.

---

## 16. Current live debt

The current repository still has several alignment issues to close before adding new memory technology:

1. `HybridRetrievalRouter` imports Redis through the deprecated core shim instead of the canonical `platform/memory/redis/` path.
2. Redis itself is active, but some dependency/documentation comments incorrectly describe Redis as retired.
3. `PostgresRecallRetriever` already uses SQLAlchemy against the canonical database session path; dependency manifests must match this live import truth.
4. Graph retrieval remains shallow and Kuzu-named storage is not durable graph truth.
5. Existing spreading activation maintains an independent in-memory association graph and is not yet driven from canonical PostgreSQL graph neighborhoods.
6. Lexical/profile/procedural branches in hybrid retrieval are incomplete/stubbed.

These are wiring/ownership problems, not reasons to add another database.

---

## 17. Required execution order

```text
MEMORY-WIRING-TRUTH
  -> affirm Redis as canonical STM platform adapter
  -> remove deprecated core Redis imports/shims at sunset
  -> prove Redis tenant/session/TTL/degradation behavior
  -> affirm Supabase/Postgres as durable authority
  -> align dependency manifests with live SQLAlchemy/Redis imports
  -> close PostgreSQL durable recall path
  -> build MEMORY-FORMATION-1 on Redis context + Postgres durability
  -> establish PostgreSQL-native temporal graph persistence/traversal
  -> connect existing spreading activation to canonical graph neighborhoods
  -> prove provenance/tenant/degradation contracts
  -> MEMORY-GRAPH-2 associative/experience phases
```

Do **not** add NetworkX, pgmq, Kuzu, Neo4j, Memgraph, FalkorDB, Graphiti, Mem0, Apache AGE clients, Elasticsearch, Milvus, or another graph/vector database during this closure work.

Any external graph-compute or storage dependency requires a benchmark-backed ADR after the Redis + Supabase/PostgreSQL architecture has been proven under real KAREN workloads.

---

## 18. Proof

Memory work must prove:

- Redis session/STM read/write/TTL behavior;
- Redis unavailable -> explicit bounded degradation;
- Redis cache success != durable save success;
- Supabase/Postgres durable write/read persistence;
- process restart durability for durable memory;
- tenant isolation across Redis and Postgres;
- canonical async Postgres session path only;
- migrations own schema changes;
- pgvector/lexical recall integration where enabled;
- temporal current-vs-historical retrieval;
- true bounded multi-hop graph traversal;
- graph provenance to canonical durable IDs;
- contradiction/supersession behavior;
- associative activation consumes canonical graph neighborhoods;
- experience memory changes later behavior;
- deletion/forgetting propagates correctly;
- no duplicate durable memory authority;
- failure reporting rather than fake save success.

Recommended baseline commands:

```text
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Plus targeted Redis, Postgres/Supabase, memory contract, tenant isolation, recall, and graph tests.