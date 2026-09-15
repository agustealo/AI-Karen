# KARI OS Developer Sheet

> **Status:** Canonical implementation sprint and developer execution contract  
> **Repository baseline:** `agustealo/AI-Karen@d80d79af63b017162713334dd53fdc3956a9bbc4`  
> **Audit date:** 2026-09-14  
> **Branch carrying this refresh:** `audit/kari-os-methodology-burn`  
> **Current architecture PRs:** #57 LangGraph authority convergence, #58 KARI OS architecture/methodology/stack refresh  
> **Rule:** This sheet is the current execution program. Historical sprint sheets do not override it.

# 0. Mission

Build KARI as a **local-first, prompt-first, domain-neutral cognitive operating substrate** with durable governed memory, provider/model orchestration, cognitive continuity, policy-governed action, modular extensions, strong tenant/RBAC boundaries, observability and executable proof.

The project law is:

> **Core stores universal cognitive primitives. Domain Packs provide semantics. Skill Packs provide reusable practice. Connectors provide external capabilities. Runtime retains authority.**

The engineering law is:

> **One responsibility -> one owner -> one contract -> one registry/config source where applicable -> one runtime path -> executable proof.**

No sprint may introduce a second authority simply because an existing subsystem is incomplete.

---

# 1. Live stack truth

## Canonical durable data

**ACTIVE / AUTHORITATIVE**

- PostgreSQL 15
- Supabase-local deployment/migration baseline
- SQLAlchemy
- asyncpg
- psycopg / psycopg2 where configured
- pgvector
- HNSW vector index
- PostgreSQL FTS / GIN
- JSONB
- temporal entity/relation projections
- RLS / tenant isolation
- advisory locks / transaction semantics

## Hot/distributed state

**ACTIVE**

- Redis 7
- bounded STM/hot context
- rate limiting where configured
- distributed coordination
- Medusa execution ownership/cancellation coordination

## Backend

**ACTIVE**

- Python
- FastAPI
- Uvicorn
- uvloop
- httptools
- Pydantic / pydantic-settings
- Alembic / Supabase migrations
- HTTPX / aiohttp where owned integrations need them

## Model/inference estate

**ACTIVE/OPTIONAL BY CONFIG**

- Transformers
- sentence-transformers
- Hugging Face assets
- Ollama
- vLLM GPU profile
- vLLM CPU profile
- local GGUF server
- OpenAI-compatible provider interfaces
- OpenAI SDK
- Google Generative AI integration where configured

Provider existence is not provider authority. Runtime registry/config/health decides eligibility.

## Workflow / agents

**ACTIVE SPECIALISTS**

- LangGraph: true graph workflow semantics only
- Agent Medusa: governed distributed multi-agent execution

Neither owns global runtime, identity, policy or provider selection.

## Observability

**ACTIVE/SUPPORTED**

- structured logging
- python-json-logger
- Prometheus client
- optional Prometheus service
- optional Grafana service
- OpenTelemetry API/SDK
- audit/lifecycle events
- request/correlation IDs

## Retired from canonical memory/data authority

- Neo4j
- Milvus
- Elasticsearch memory projections
- Kuzu
- DuckDB
- hnswlib

Do not reintroduce any of these as an authority without a benchmark-backed ADR.

---

# 2. Current authority map

| Responsibility | Canonical owner | Forbidden duplicate |
|---|---|---|
| HTTP/event ingress | API routes / governed connector ingress | orchestration, provider choice, memory mutation |
| Cognitive decisions | `core/cortex` | provider/tool execution, persistence |
| Runtime authorization | `core/runtime/policy` | self-authorization by CORTEX/agent/plugin |
| Request/event lifecycle | `core/runtime` | route/UI/agent-owned runtime |
| Complex authorized workflows | `WorkflowRuntime` | direct graph authority |
| Graph workflows | LangGraph under Runtime/WorkflowRuntime | ordinary chat/global routing |
| Multi-agent execution | Agent Medusa | cognitive intent/policy/provider authority |
| Signal extraction | `core/intelligence` | final cognitive authority |
| Cognitive contracts/state | `core/cognitive` | orchestration |
| Context primitives | `core/context` | independent runtime |
| Prompt assembly | PromptRuntime | scattered concatenation |
| Memory recall | NeuroRecall | persistence |
| Memory formation | MemoryFormation | recall/CORTEX/reasoning |
| Durable memory mutation | NeuroVault / canonical Postgres repositories | side-door writes |
| Person/self/relationship foundation | `core/personalization` | global runtime/policy |
| Automation semantics | `core/automation` | new scheduler/proactive runtime |
| Provider/model selection | canonical model runtime/provider registry | UI/routes/CORTEX/packs |
| Authentication/session/RBAC | AuthService/backend policy | UI/client/connectors |
| Durable schema | migrations | runtime table creation |
| Configuration | `src/ai_karen_engine/config` | scattered env readers |
| Observability | canonical platform observability | shadow telemetry |
| Domain semantics | Domain Packs | universal core leakage |
| Reusable expert practice | Skill Packs + core practice contracts | runtime/policy authority |
| External systems | Connectors | identity/policy/memory authority |

---

# 3. Current live interaction path

```text
Transport / API
      |
      v
ChatRuntime.execute / execute_stream
      |
      v
RuntimeDecisionPipeline
      |
      +--> CortexExecutionDecider
      |
      +--> RuntimePolicyEnforcer
      |
      v
AuthorizedExecutionPlan
      |
      +--> governed memory recall
      +--> DIRECT -> PromptRuntime -> ModelRuntime
      +--> REASONING -> ReasoningExecutor
      +--> WORKFLOW -> WorkflowRuntime
      |                 +--> LangGraph when real graph semantics apply
      |                 +--> Medusa when multi-agent topology applies
      |
      +--> persistence / outcome / telemetry
```

Chat is the mature path today.

Target evolution is **event-capable Runtime**, not a second EventRuntime.

---

# 4. Current memory/data path

```text
Redis
  +--> STM / hot context / coordination

PostgreSQL/Supabase
  +--> memory_event
  +--> memory_assertion
  +--> memory_episode
  +--> profile_fact
  +--> memory_items
  +--> memory_entity
  +--> memory_relation
  +--> contradiction / reinforcement records
  +--> consent / retention state
  +--> pgvector
  +--> HNSW
  +--> FTS / GIN
  +--> RLS

NeuroRecall
  +--> retrieval strategy/scoring

MemoryFormation
  +--> post-outcome formation decision

NeuroVault
  +--> governed durable mutation/lifecycle
```

## Hard rules

- Neo4j is retired.
- Milvus is retired from canonical memory.
- Elasticsearch memory projections are retired.
- DuckDB is retired despite stale compose configuration.
- WorldModel is not a database product.
- Redis is not durable LTM.
- Graph projections are rebuildable unless a deliberate ADR changes authority.
- No memory write bypasses canonical formation/persistence.
- No cross-tenant recall.

---

# 5. Architecture maturity

## Strong / active

- PostgreSQL/Supabase durable spine
- pgvector/HNSW semantic retrieval
- PostgreSQL FTS
- temporal relation projections
- Redis distributed/hot state
- CORTEX decision authority
- RuntimePolicy separation
- Runtime-owned chat lifecycle
- provider/model backend authority
- Agent Medusa distributed ownership/fencing
- tenant/RBAC/audit foundations
- first-run durable bootstrap
- architecture/release CI estate

## Partial

- two-stage evidence-aware cognition
- person/self/relationship continuity
- post-outcome memory formation convergence
- graph/workflow authority convergence
- extension taxonomy
- generalized event intake
- installation readiness aggregation
- first-real-chat fresh-install proof

## Underbuilt / target

- durable commitment engine
- wakeups/triggers/recurrence/approval lifecycle
- universal WorldModel contracts
- Craft & Practice cognition
- RuntimeGovernanceProfile
- autonomy-level contract
- Personal/Family/Enterprise generality benchmark
- longitudinal cognition benchmark

---

# 6. Current blocking work

## BLOCKER A: PR #57 authority convergence

### Objective

Close the remaining LangGraph identity/runtime authority split.

### Required end state

```text
API / Event ingress
      |
      v
Runtime derives trusted identity/tenant context
      |
      v
CORTEX decides
      |
      v
RuntimePolicy authorizes
      |
      v
WorkflowRuntime adapts
      |
      v
LangGraph consumes trusted context
```

### Do

- preserve AuthGate as validation-only;
- ensure direct agent/workflow entry points cannot invoke graph execution with empty trusted context;
- derive identity server-side;
- pass tenant/user scope from canonical runtime;
- ensure streaming and non-streaming paths match;
- preserve RuntimePolicy dominance;
- prevent anonymous/default-tenant synthesis.

### Avoid

- client-supplied `auth_context`;
- graph-level user lookup;
- graph-level tenant invention;
- graph-specific provider selection;
- graph-specific memory authority.

### Proof

- architecture contract for runtime-owned identity;
- direct `/api/agents/execute` path test;
- streaming path test;
- tenant mismatch fail-closed test;
- existing workflow/LangGraph tests;
- exact-head CI.

---

# 7. KARI-OS-0: architecture + stack freeze

## Objective

Make the developer contract impossible to misread.

## Status

PR #58 active.

## Do

- maintain `PROJECT_DEV_MANIFEST.md`;
- maintain `docs/architecture/KARI_OS_MANIFEST.md`;
- maintain `docs/architecture/KARI_OS_ADVERSARIAL_BURN.md`;
- maintain `docs/architecture/KARI_OS_CURRENT_BLUEPRINT.md`;
- maintain this developer sheet;
- retire contradictory current-state claims;
- label historical documents explicitly;
- keep live stack classifications current.

## Proof

- docs agree with live code/migrations/dependencies;
- no current doc claims Neo4j/Milvus/Elasticsearch/DuckDB as canonical memory;
- no current doc claims target behavior is implemented.

---

# 8. KARI-OS-1: runtime authority convergence

## Objective

Finish one execution authority chain.

## Do

- complete PR #57;
- audit all direct LangGraph entry points;
- audit all direct Medusa entry points;
- audit direct provider calls from routes/services;
- audit direct memory writes from routes/services/agents;
- migrate legitimate callers to Runtime/WorkflowRuntime;
- remove dead alternate paths after reference audit.

## Reuse

- CORTEX
- RuntimePolicy
- ChatRuntime
- WorkflowRuntime
- canonical AuthService
- Agent Medusa execution controls
- current LangGraph orchestrator

## Avoid

- new orchestrator;
- graph runtime v2;
- agent runtime v2;
- route-level fallback logic.

## Proof

```bash
python -m compileall src
pytest tests/architecture -q
pytest tests/ -q
ruff check --select E9,F63,F7 src tests
mypy --follow-imports=skip --ignore-missing-imports src/ai_karen_engine/core/runtime/contracts.py src/ai_karen_engine/core/runtime/chat_runtime_contract.py src/ai_karen_engine/core/runtime/execution_decision.py src/ai_karen_engine/core/runtime/decision_pipeline.py src/ai_karen_engine/core/cortex/contracts.py src/ai_karen_engine/core/model_runtime/provider_contracts.py src/ai_karen_engine/core/model_runtime/inference_target.py src/ai_karen_engine/core/model_runtime/runtime_contracts.py src/ai_karen_engine/core/memory/contracts.py
```

---

# 9. KARI-OS-2: architecture immune system

## Objective

Turn architecture law into failing tests.

## Add contract tests for

- no new Neo4j/Milvus/Elasticsearch/DuckDB canonical-memory dependencies without ADR;
- no client-controlled tenant/user/role authority;
- no direct plugin/connector action bypassing RuntimePolicy;
- no side-door memory mutation;
- no duplicate provider registry;
- no duplicate global runtime;
- no duplicate scheduler/proactive engine;
- no vertical-domain type leakage into universal core without explicit allowlist/ADR;
- no LangGraph ordinary-chat ownership;
- no Medusa cognitive-intent ownership;
- no UI provider/persistence truth invention.

## Proof

- architecture tests hard-fail;
- CI workflow includes them;
- negative fixtures prove the tests actually catch violations.

---

# 10. KARI-OS-3: Universal WorldModel

## Objective

Introduce domain-neutral world contracts without a new datastore.

## Minimum contracts

```text
Entity
Person
Group
Role
RoleAssignment
Relationship
Artifact
Process
Resource
Rule
Goal
Commitment
Event
Context
Dependency
Outcome
```

## Requirements

- typed;
- tenant-scoped;
- evidence/provenance-aware;
- temporal;
- confidence-aware where appropriate;
- compatible with existing memory relation/entity projections;
- serializable;
- no enterprise-only nouns;
- no persistence side effects inside contracts.

## Storage direction

Use current PostgreSQL entity/relation/temporal substrate first.

## Explicit non-goal

Installing Neo4j is not part of WorldModel implementation.

## Proof

- unit tests for contracts;
- serialization tests;
- temporal/evidence tests;
- Personal/Family/Enterprise fixture mappings using the same primitives;
- no new external graph DB dependency.

---

# 11. KARI-OS-4: Durable Commitment Runtime

## Objective

Turn `core/automation` from contracts into durable agency.

## Canonical lifecycle

```text
Observation
 -> Interpretation
 -> Goal/Commitment candidate
 -> Persistence decision
 -> Trigger registration
 -> Wake event
 -> Context refresh
 -> CORTEX
 -> RuntimePolicy
 -> ExecutionPlan
 -> Approval if required
 -> Runtime execution
 -> Outcome evaluation
 -> Memory formation
 -> Commitment update
```

## Required capabilities

- durable commitment record;
- trigger persistence;
- time/event triggers;
- deduplication;
- recurrence;
- approval state;
- cancellation;
- expiry;
- restart survival;
- distributed ownership where required;
- context refresh before action;
- RuntimePolicy reauthorization;
- retry/follow-up;
- outcome capture;
- telemetry.

## Reuse

- current `core/automation`;
- PostgreSQL;
- Redis coordination;
- Runtime/WorkflowRuntime;
- RuntimePolicy;
- Medusa if distributed execution is genuinely needed;
- existing temporal/prospective memory concepts.

## Avoid

- scheduler_service_v2;
- background_agent;
- proactive_ai;
- automation_runtime_new.

## Proof

- restart test;
- duplicate-trigger test;
- expired approval test;
- tenant isolation test;
- stale-context prevention test;
- A3 approval test;
- A4 delegated-scope test;
- outcome/formation test.

---

# 12. KARI-OS-5: Craft & Practice cognition

## Objective

Model learned ways of doing things, not just facts.

## Core contracts

```text
Practice
Artifact
Exemplar
Technique
Critique
Constraint
DecisionRationale
AcceptedOutcome
RejectedOutcome
Exception
Evolution
```

## Requirements

- evidence/provenance;
- temporal evolution;
- accepted vs rejected outcomes;
- explainable rationale;
- domain-neutral vocabulary;
- memory integration through canonical formation;
- retrieval through NeuroRecall.

## Proof domains

At least three unrelated domains:

- software architecture;
- creative/design;
- personal/family practice.

If one domain requires a new vertical core type, review the abstraction.

---

# 13. KARI-OS-6: extension taxonomy

## Objective

Formalize Connector, Domain Pack and Skill Pack as different governed extension classes.

## Connector manifest must declare

- external system;
- capabilities;
- events;
- input/output schemas;
- permissions;
- secrets;
- rate/resource limits;
- tenant scope;
- audit requirements.

## Domain Pack manifest must declare

- ontology additions;
- schemas;
- policy contributions;
- prompt contracts;
- reasoning hints;
- workflows;
- evaluation rules;
- compatibility/version.

## Skill Pack manifest must declare

- skill identity;
- applicable artifact/practice types;
- prompt contracts;
- tools required;
- evaluation criteria;
- permissions;
- version.

## Hard rule

No extension class may own:

- auth;
- tenant identity;
- RuntimePolicy;
- provider routing;
- canonical memory persistence;
- global runtime.

---

# 14. KARI-OS-7: generality benchmark

## Objective

Prove the abstraction is actually domain-neutral.

## Reference deployments

### KARI Personal

- Personal Domain Pack
- Calendar Connector
- Email Connector
- personal finance or planning skill

### KARI Family

- Family Domain Pack
- household roles/relationships
- routine/commitment examples
- calendar/home connector examples

### KARI Enterprise

- Enterprise Domain Pack
- role/approval examples
- GitHub/Slack/Jira-style connector examples
- software/operations skill examples

## Pass condition

All three use the same:

- Runtime;
- RuntimePolicy;
- CORTEX;
- memory authority;
- WorldModel primitives;
- commitment engine;
- extension interfaces.

A core fork fails the benchmark.

---

# 15. KARI-OS-8: longitudinal cognition benchmark

## Objective

Prove human-like continuity behavior over time.

## Required scenarios

- revise belief when stronger evidence arrives;
- preserve contradiction history;
- survive restart with unresolved commitment;
- expire/forget under retention policy;
- prevent cross-tenant recall;
- distinguish observation vs inference;
- preserve provenance;
- detect preference drift without flattening history;
- retain relationship context;
- retain learned practice and rationale;
- wake from commitment and refresh context before action.

## Proof

- deterministic fixtures where possible;
- explicit time controls;
- restart boundaries;
- tenant matrix;
- evidence lineage assertions;
- no model-only subjective pass criteria.

---

# 16. TECH-DEBT-STACK-1: retired stack cleanup

## Objective

Remove stale wiring and documentation that falsely imply retired technologies remain active.

## Audit targets

```text
neo4j
milvus
elasticsearch
duckdb
kuzu
hnswlib
memgraph
falkordb
graphiti
mem0
apache age
```

## Known current debt

`docker-compose.yml` still contains:

```text
KARI_ENABLE_DUCKDB=true
```

while DuckDB is retired by current dependency policy.

## Do

- search code;
- search config;
- search scripts;
- search tests;
- search docs;
- classify each match;
- preserve historical provenance only when clearly labeled;
- delete dead runtime/config wiring;
- update architecture tests to prevent resurrection.

## Before deleting

For every active-looking path:

1. identify purpose;
2. search imports/references;
3. inspect tests;
4. inspect config/docs;
5. confirm replacement;
6. preserve security/telemetry behavior;
7. delete only after proof.

---

# 17. FIRST-RUN / installation work

## Current strong area

- durable first-owner bootstrap;
- tenant assignment;
- one-time semantics;
- normal authentication/session path;
- production first-boot smoke;
- migration-owned schema.

## Remaining work

### FIRST-RUN-CONFIG-1

Move direct first-run tenant env interpretation behind canonical validated config.

### FIRST-RUN-2

Typed installation-readiness aggregation over existing subsystem truths.

Must aggregate, not take ownership of:

- provider/model readiness;
- memory readiness;
- extension readiness;
- observability readiness.

### FIRST-RUN-3

Frontend wizard/router rendering backend truth only.

### FIRST-RUN-4

Fresh-install first-real-chat proof with actual provider/model/degradation provenance.

---

# 18. Provider/runtime rules

Canonical fallback remains config-driven.

Conceptual priority:

```text
Requested eligible provider/model
 -> local primary
 -> vLLM
 -> Transformers
 -> Ollama when healthy
 -> external when enabled
 -> honest unavailable
```

Actual order must come from current canonical config, not hardcoded sprint prose.

Required degraded metadata:

```text
degraded_mode
degradation_reason
requested_provider
requested_model
actual_provider
actual_model
runtime_engine
fallback_level
response_source
latency_ms
correlation_id
```

No canned model output.

---

# 19. Security / governance checklist

Every architecture-affecting change must preserve:

- server-derived identity;
- explicit tenant scope;
- RBAC;
- RuntimePolicy dominance;
- audit;
- extension permissions;
- secret redaction;
- safe errors;
- correlation IDs;
- retention/deletion semantics;
- approval state;
- no policy-bypassing fallback;
- no cross-tenant memory;
- no client-supplied authority.

---

# 20. Observability checklist

Trace when applicable:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
event_type
intent
topology
provider
model
runtime_engine
fallback_level
degraded_mode
degradation_reason
response_source
memory_recall_count
plugin_id
connector_id
domain_pack
skill_pack
agent_id
autonomy_level
commitment_id
trigger_id
approval_id
latency_ms
status
error_type
error_code
```

Do not put high-cardinality IDs into Prometheus labels.

---

# 21. Prompt-first checklist

Any new reasoning behavior must answer:

- where is the prompt contract?
- version?
- schema?
- input ownership?
- output ownership?
- token budget?
- provider capability assumptions?
- tests?
- security/policy constraints?
- extension contribution mechanism?

No hidden prompt concatenation in routes, providers, agents or connectors.

---

# 22. Deletion discipline

Before deleting any file/service:

```text
[ ] identify purpose
[ ] search imports
[ ] search dynamic references
[ ] search tests
[ ] search docs
[ ] search config
[ ] search UI
[ ] search workflows
[ ] identify replacement
[ ] preserve RBAC/security/audit
[ ] preserve telemetry
[ ] classify risk
[ ] run proof
[ ] delete
[ ] re-run reference audit
```

Never keep dead authority "just in case."

---

# 23. Development stop conditions

Stop and perform an architecture review before merging if a change:

- adds another global runtime;
- adds another provider registry;
- adds another memory writer;
- adds another scheduler/proactive runtime;
- lets LangGraph authenticate/authorize independently;
- lets Medusa decide cognitive intent;
- lets UI invent backend truth;
- lets a Connector persist memory directly;
- lets a Domain Pack own runtime/policy;
- lets a Skill Pack choose providers;
- accepts client-controlled tenant/user/role authority;
- introduces a retired datastore as canonical memory;
- puts enterprise/family/tool-specific nouns into universal core;
- introduces prompts without contracts/tests;
- claims release readiness without exact-head proof.

---

# 24. Canonical proof commands

Backend:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Frontend where applicable:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Infrastructure/data:

```bash
docker compose config
supabase db reset
```

Narrow tests are appropriate during development.

Current Main Quality uses staged Ruff and Mypy correctness baselines while historical formatting/style and typing debt is retired in contained slices. Do not represent those baselines as full-repository lint/type cleanliness. Full Ruff and full-tree Mypy convergence remain technical debt.

Architecture-affecting merges require the applicable canonical GitHub gates.

Never call a SHA green unless the checks actually ran against that SHA.

---

# 25. GitHub gate map

Current repository workflows include dedicated proof for:

- main quality;
- beta release;
- chat-system burn;
- classifier burn;
- cognitive proof;
- context authority;
- agent-system burn;
- Medusa core;
- Medusa durable runs;
- memory consumer contracts;
- plugins;
- production auth/security;
- production data recovery;
- production database baseline;
- production deployment;
- production first boot;
- reasoning smoke;
- live/real model proof.

A workflow file existing is not evidence that the current head passed.

---

# 26. Developer handoff format

For implementation handoffs, use:

```text
Task #
Title
Objective
Current owner
Do
Reuse
Avoid
Files
Security/RBAC
Observability
Proof
Risks
```

Do not send vague "improve X" work into the repo.

Every task must identify the authority being modified and how the result is proven.

---

# 27. Current priority order

```text
P0  PR #57 authority convergence
P0  PR #58 architecture/methodology/stack freeze

P1  KARI-OS-2 architecture immune system
P1  TECH-DEBT-STACK-1 retired-stack cleanup
P1  exact-head beta proof restoration

P2  KARI-OS-3 Universal WorldModel contracts
P2  KARI-OS-4 Durable Commitment Runtime

P3  KARI-OS-5 Craft & Practice
P3  KARI-OS-6 extension taxonomy

P4  KARI-OS-7 generality benchmark
P4  KARI-OS-8 longitudinal cognition benchmark
```

Do not jump to KARI-OS-5/6/7 while runtime authority is still split.

---

# 28. Final developer mental model

```text
KARI OS          = domain-neutral cognitive substrate
CORTEX           = cognitive decision authority
RuntimePolicy    = authorization authority
Runtime          = lifecycle/execution authority
WorkflowRuntime  = authorized complex-work adapter
LangGraph        = true graph-workflow executor
Agent Medusa     = governed distributed multi-agent executor
Intelligence     = signal/perception layer
Context          = typed context primitives
NeuroRecall      = retrieval strategy
MemoryFormation  = formation eligibility
NeuroVault       = governed durable memory mutation
PostgreSQL       = canonical durable data/memory authority
pgvector         = canonical vector retrieval substrate
PostgreSQL FTS   = canonical lexical retrieval substrate
Redis            = bounded hot/distributed state
WorldModel       = universal ontology/contracts, not a DB product
Craft & Practice = learned ways of doing things
Connector        = external capability/event bridge
Domain Pack      = specialized semantics
Skill Pack       = reusable expert practice
Observability    = actual execution truth
Config           = validated runtime/deployment truth
```

# Final rule

Protect architecture before adding capability.

Use the existing source of truth.

Collapse duplicates.

Delete dead authority.

Keep routes thin.

Keep Runtime authoritative.

Keep CORTEX cognitive.

Keep RuntimePolicy dominant.

Keep PostgreSQL/Supabase the durable spine unless benchmarks prove otherwise.

Keep packs semantic.

Keep connectors capable but subordinate.

Keep telemetry complete.

Prove every claim.
