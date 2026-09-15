# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract, live technology inventory, and architecture truth map
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, installation/bootstrap, infrastructure, tests, and documentation
> **Live audit baseline:** `main` at `d80d79af63b017162713334dd53fdc3956a9bbc4` audited 2026-09-14
> **Architecture direction:** KARI OS, a domain-neutral local-first cognitive operating substrate
> **Rule:** Live code, migrations, dependency manifests, deployment composition, and executable tests are implementation truth. Historical sprint sheets, compatibility layers, old diagrams, framework conventions, and research systems never override them.

AI KAREN is a **local-first, prompt-first, modular cognitive AI operating substrate** evolving toward human-like continuity with governed memory, evidence-backed self/person/relationship/world models, provider/model orchestration, governed reasoning, durable agency, RBAC, audit, extensibility, installation/bootstrap, and observable system behavior.

KAREN is not framework-first and is not an enterprise-only vertical. Enterprise, Personal, Family, Creative, Research and other domains must specialize universal KARI primitives through governed packs/extensions rather than fork the cognitive core.

**Canonical KARI OS law:** Core stores universal cognitive primitives. Domain Packs provide semantics. Skill Packs provide reusable practice. Connectors provide external capabilities. Runtime retains authority.

---

## 0. Live Technology Stack Truth

This section is the first place developers check before proposing a datastore, graph engine, vector database, model runtime, workflow framework, cache, or infrastructure service. A technology mentioned in old documentation is not active merely because it was once planned.

### 0.1 Canonical durable data spine

**ACTIVE / AUTHORITATIVE: PostgreSQL 15 through the repository's Supabase-local deployment/migration baseline.**

Production migrations under `supabase/migrations/` own schema evolution. SQLAlchemy is the canonical Python ORM/session/engine abstraction, with `asyncpg` for canonical async PostgreSQL URLs and psycopg/psycopg2 available for configured sync paths.

PostgreSQL currently carries more than relational rows. KARI deliberately converged durable memory capabilities onto this data spine:

- relational durable state;
- JSONB metadata/evidence payloads;
- pgvector embeddings;
- HNSW vector indexing;
- PostgreSQL full-text search / GIN;
- temporal/entity/relation memory projections;
- recursive SQL/CTE graph traversal where applicable;
- tenant isolation/RLS in migration-owned schemas;
- transactional/advisory-lock semantics for critical lifecycle operations.

**Do not add another authoritative durable memory database because a feature can be described as graph, vector, document, or semantic storage.** Benchmark the existing PostgreSQL capabilities first.

### 0.2 Vector and semantic retrieval

**ACTIVE: pgvector inside canonical PostgreSQL/Supabase.**

The required production extension migration creates `vector`. Memory migrations define `embedding_vector` and an HNSW cosine index. PostgreSQL FTS is also indexed for lexical retrieval.

**RETIRED for canonical memory: Milvus and Elasticsearch projections.** The production memory migration explicitly records that memory persistence converged to PostgreSQL with pgvector + FTS and retired Milvus/Elasticsearch projections for `memory_items`.

Do not describe Milvus or Elasticsearch as current KARI memory authorities unless live code, migrations and deployment are deliberately changed through an approved ADR.

### 0.3 Graph / relationship storage

**NEO4J IS RETIRED. It is not part of the current KARI production stack.**

The runtime dependency policy explicitly classifies `neo4j` as retired and prohibits adding Neo4j, Memgraph, FalkorDB, Graphiti, Apache AGE clients or another graph/vector database without a benchmark-backed ADR.

Current graph direction is:

```text
canonical governed memory in PostgreSQL
        |
        +--> memory_entity
        +--> memory_relation
        +--> temporal validity / confidence / salience
        +--> tenant RLS
        +--> recursive traversal / spreading activation
        |
        `--> rebuildable graph projections/accelerators when justified
```

The migration `20260827090000_09_memory_temporal_graph.sql` explicitly states PostgreSQL/Supabase remains durable authority and graph rows are rebuildable projections.

A future graph accelerator is permitted only as derived/rebuildable compute. It must never become an independent durable memory authority without an architecture migration and benchmark evidence.

### 0.4 Short-term / distributed state

**ACTIVE: Redis 7.**

Redis is canonical bounded STM/session/hot-context infrastructure and is also reused for distributed coordination where appropriate, including Medusa ownership/cancellation coordination and rate limiting. Do not create a second Redis connection authority; use the canonical platform Redis manager/adapters.

### 0.5 Analytics

**DuckDB is RETIRED as a canonical backend dependency.** `requirements.txt` classifies DuckDB with retired backends. A stale `KARI_ENABLE_DUCKDB` environment line remains in `docker-compose.yml`; treat that as configuration/documentation debt, not evidence that DuckDB is an active canonical datastore. Remove/audit stale wiring rather than resurrecting the dependency.

### 0.6 Backend / API runtime

**ACTIVE:**

- Python
- FastAPI
- Uvicorn
- uvloop / httptools
- Pydantic / pydantic-settings
- SQLAlchemy
- Alembic / Supabase migrations
- asyncpg / psycopg
- Redis client
- HTTPX / aiohttp where owned integrations require them

API routes remain thin ingress. Framework availability never grants architectural authority.

### 0.7 Model / inference stack

The canonical model runtime/provider registry owns availability, health, model selection, execution and fallback. Current packaged dependencies/deployment support include:

- Transformers / Hugging Face model assets;
- sentence-transformers for embedding/NLP capabilities where active;
- Ollama as an optional local inference service;
- vLLM as an optional OpenAI-compatible local inference service, GPU and CPU profiles in Docker composition;
- local GGUF server as an optional profile;
- OpenAI-compatible provider clients;
- OpenAI SDK;
- Google Generative AI integration where configured;
- other providers only when registered through canonical provider/model authority.

`docker-compose.yml` containing a service does not make that service the default authority. Provider health/config/registry truth decides runtime eligibility.

Local-first fallback remains config/policy driven. No route, UI, CORTEX component, agent, pack or connector chooses providers independently.

### 0.8 Workflow and multi-agent execution

**ACTIVE specialist frameworks/subsystems:**

- LangGraph 1.1.x for true graph semantics only;
- Agent Medusa for governed multi-agent/distributed execution topology.

Neither is KARI's global runtime. CORTEX decides, RuntimePolicy authorizes, Runtime/WorkflowRuntime executes, and specialist engines operate below those authorities.

### 0.9 Observability

**ACTIVE / supported:**

- structured Python logging / python-json-logger;
- Prometheus client and optional Prometheus service profile;
- Grafana optional observability profile;
- OpenTelemetry API/SDK;
- KARI structured lifecycle/audit telemetry.

High-cardinality request/user/tenant IDs belong in structured events/traces, not Prometheus labels.

### 0.10 Security / identity

KARI owns application authentication and authorization. The local Supabase configuration has Supabase Auth disabled; Supabase/PostgreSQL is being used as the data spine, not as a replacement identity authority.

Active security building blocks include canonical AuthService/session flows, backend RBAC, tenant scope, audit, bcrypt/argon2/passlib support, JWT/session handling, rate limiting, cryptography, TOTP capability, PostgreSQL RLS and secret-safe configuration.

### 0.11 Extension/integration substrate

KARI supports governed extensions/actions and MCP-related dependencies. External integrations remain Connectors. Domain semantics remain Domain Packs. Reusable expert behavior remains Skill Packs. None of these may become alternate runtime, identity, memory, provider or policy authorities.

### 0.12 Retired / prohibited-by-default technology inventory

Unless a new benchmark-backed ADR explicitly changes the architecture, developers must treat these as retired from canonical memory/data authority:

- Neo4j
- Milvus
- Elasticsearch memory projections
- Kuzu
- DuckDB
- hnswlib

Also do not introduce Memgraph, FalkorDB, Graphiti, Mem0, Apache AGE, NetworkX-as-authority, or a second vector/graph database merely to implement WorldModel or associative recall.

The WorldModel is a KARI contract/ontology. It is **not synonymous with a graph database**.

### 0.13 Stack verification rule

Before writing any tech name into a sprint as ACTIVE, verify at least two relevant implementation signals where practical:

1. live import/dependency;
2. live runtime composition/config;
3. migration/schema ownership;
4. deployment service;
5. executable test/CI proof.

Classify technologies as `ACTIVE`, `OPTIONAL`, `DERIVED/PROJECTION`, `COMPATIBILITY`, `EXPERIMENTAL`, `RETIRED`, or `TARGET`. Never collapse those states into a generic "we use X" statement.

---

## 1. Engineering Mission

Every major responsibility must have:

1. one owner;
2. one canonical contract;
3. one runtime path;
4. one registry/config source where applicable;
5. explicit tenant/security boundaries;
6. observable lifecycle events;
7. executable proof.

Core rules:

- **Local-first:** prefer healthy local capabilities when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable contracts.
- **Runtime-authoritative:** routes, UI, providers, agents, plugins, connectors and workflow engines never become alternate runtimes.
- **CORTEX is KAREN's central cognitive authority. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **Evidence access is authorization-sensitive.** CORTEX may request evidence, but RuntimePolicy must authorize governed access before Runtime resolves it.
- **DRY by authority:** one responsibility -> one owner -> one execution path.
- **Typed and async-safe:** public cognitive/runtime boundaries are typed; budgets, cancellation, concurrency, and distributed ownership are explicit.
- **Config-driven:** providers, models, endpoints, fallbacks, feature flags, environment, budgets, security modes, and installation settings belong behind canonical validated configuration.
- **Migration-owned schema:** production runtime verifies required schema but does not silently create missing migration-owned tables/extensions.
- **Honest degradation:** unavailable capabilities produce explicit degraded/unavailable results, never fabricated model output.
- **Evidence-preserving cognition:** retrieval evidence must not be flattened into untyped text before reasoning, prompting, or model revision.
- **Learning is outcome-aware:** durable formation is evaluated after execution from the actual interaction/outcome, not only predicted before generation.
- **Human-like continuity is domain-neutral:** enterprise concepts never become universal core primitives merely because Enterprise is a valuable KARI deployment.
- **First run is lifecycle, not UI:** a fresh installation must prove durable identity, tenant scope, one-time bootstrap, restart survival, and fail-closed setup behavior.
- **Test-proven architecture:** architecture rules are executable where practical.

### 1.1 Cognitive north star

The target is cognitive continuity, not merely long-term memory:

```text
experience/event
 -> interpret
 -> identify evidence needs
 -> authorize evidence access
 -> retrieve/resolve evidence
 -> revise current cognition
 -> decide
 -> authorize execution
 -> act/respond/workflow
 -> observe outcome
 -> evaluate learning/formation
 -> consolidate
 -> revise beliefs/models/relationships/practice
 -> update goals/commitments/future cognition
```

Memory, evidence, claims, beliefs, knowledge, identity, person understanding, relationship continuity, temporal reasoning, goals, commitments, metacognition, retention/forgetting, craft/practice and outcome learning remain distinct concerns with explicit contracts.

---

## 2. Canonical Authority Map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP/event ingress | `api_routes/` + app composition / governed connector ingress | provider choice, prompts, recall, orchestration, identity invention |
| Request/event lifecycle | `core/runtime/` | routes, UI, CORTEX, agents, connectors |
| Cognitive decisions | `core/cortex/` | authorization, provider execution, persistence |
| Signal extraction / ML inference | `core/intelligence/` | final cognitive authority, execution, authorization |
| Cognitive state vocabulary | `core/cognitive/` | orchestration, provider execution, persistence |
| Context vocabulary/resolution primitives | `core/context/` | independent cognitive authority |
| Runtime authorization | `core/runtime/policy/` | cognitive classification, provider execution |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents, memory retrieval |
| Reasoning execution | `core/reasoning/` | provider routing, durable writes, global orchestration |
| Memory recall strategy | NeuroRecall under `core/memory/` | durable storage, provider/tool execution |
| Memory formation / durable mutation | MemoryFormation + NeuroVault | CORTEX, reasoning, recall |
| Self/Person/Relationship models | current `core/personalization/` contracts/services | global execution, policy authorization |
| Universal WorldModel | target KARI core contracts, reusing existing memory/cognitive primitives | Enterprise/Family/CRM-specific ontology |
| Goals/commitments/automation semantics | `core/automation/` target authority | duplicate scheduler/proactive runtimes |
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX, packs, first-run auth |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, global routing |
| Multi-agent execution | AgentMedusa | provider routing, cognitive intent, global policy |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Domain semantics | governed Domain Packs | universal cognitive core unless primitive proven universal |
| Reusable expert practice | governed Skill Packs + core Craft/Practice contracts | provider/policy/runtime authority |
| External system capability | governed Connectors | auth/tenant/provider/memory/policy authority |
| Authentication/session/RBAC identity | canonical auth services + backend policy | UI, client storage, setup wizard, connectors |
| Production schema bootstrap | migrations / deployment tooling | runtime routes, AuthService table/extension creation |
| First-run durable owner/tenant bootstrap | canonical `AuthService` | UI, routes, provider runtime, ad-hoc scripts |
| Observability | `platform/observability/` | subsystem shadow telemetry |
| Configuration | `src/ai_karen_engine/config/` + validated adapters | React fallbacks, scattered direct environment reads |

**CORTEX is the central cognitive authority, not the supreme system authority.** Security/policy, execution, persistence, provider routing, authentication, installation bootstrap, schema migration, prompt assembly, observability, and configuration remain independent authorities in their own domains.

---

## 3. Live Implementation Truth: 2026-09-14

### 3.1 Actual canonical interaction path

```text
Transport / API
      |
      v
ChatRuntime.execute / execute_stream
      |
      +--> control-plane gate
      |
      v
RuntimeDecisionPipeline.decide
      |
      +--> CortexExecutionDecider.decide
      |      +--> IntelligenceRuntime signals
      |      +--> requested intent/topology/reasoning/recall/tools/budgets
      |
      +--> RuntimePolicyEnforcer.evaluate
      |
      v
AuthorizedExecutionPlan
      |
      +--> governed memory recall
      +--> DIRECT -> PromptRuntime -> ExpressionGateway -> ModelRuntime
      +--> REASONING -> RuntimeReasoningBridge -> ReasoningExecutor
      +--> WORKFLOW / MULTI-AGENT -> WorkflowRuntime -> LangGraph/Medusa as eligible
      +--> persistence / trajectory / outcome / telemetry
```

Chat is currently the mature interaction path. KARI OS target architecture generalizes events without creating a competing EventRuntime. User messages, schedules, connectors, agent completions and commitment wakeups must converge through canonical Runtime authority.

### 3.2 Memory/data reality

Current durable memory authority is PostgreSQL/Supabase, not the historical multi-database plan.

```text
Redis
  -> bounded STM / hot context / coordination

PostgreSQL 15 / Supabase data spine
  -> memory event ledger
  -> assertions / episodes / profile facts
  -> governed durable state
  -> pgvector embeddings + HNSW
  -> PostgreSQL FTS
  -> memory entities / temporal relations
  -> RLS / tenant boundaries
  -> rebuildable graph projections

NeuroRecall
  -> retrieval strategy/scoring

MemoryFormation + NeuroVault
  -> governed durable mutation/lifecycle
```

**Historical architecture references to Milvus + Elasticsearch + Neo4j + DuckDB as active memory authorities are obsolete.** Do not use them to design new code.

### 3.3 CORTEX / policy reality

CORTEX remains decision-only. RuntimePolicy remains authorization authority. The open LangGraph convergence work demonstrates that direct workflow/agent entry points still require continued hardening so server-derived auth/tenant context always reaches graph execution through canonical Runtime/WorkflowRuntime authority.

### 3.4 Automation reality

`core/automation/contracts.py` currently provides generic `FlowType`, `FlowInput`, `FlowOutput` and decide-action contracts. It is correctly placed but behaviorally shallow relative to the KARI OS agency target.

Durable commitments, trigger persistence, wakeups, recurrence, approvals, context refresh, outcome evaluation and restart-safe follow-up remain target work. Extend this canonical domain instead of introducing a second scheduler/proactive-agent authority.

### 3.5 Provider/model reality

Provider/model availability, health, selection, execution and fallback are backend runtime responsibilities. Optional deployment paths include vLLM, Ollama and local GGUF; Transformers/OpenAI-compatible integrations are present in the dependency/runtime estate. Runtime registry/config truth, not Docker comments or UI state, determines actual eligibility.

### 3.6 Distributed Medusa reality

Medusa execution control uses distributed ownership/fencing semantics and remains an execution subsystem. It does not decide cognitive intent, authorize itself, choose providers, or own memory.

### 3.7 First-run reality

KARI has canonical durable first-owner/tenant bootstrap and production first-boot proof. The data spine is PostgreSQL/pgvector plus Redis. Supabase Auth is disabled in local Supabase config; application AuthService remains identity authority.

Unified installation readiness and fresh-install first-real-chat proof remain separate work until exact-head CI proves them.

### 3.8 Live maturity classification

| Capability | Live status | Assessment |
|---|---|---|
| PostgreSQL/Supabase durable data spine | ACTIVE | canonical durable authority |
| pgvector + HNSW semantic memory | ACTIVE | canonical vector retrieval substrate |
| PostgreSQL FTS | ACTIVE | canonical lexical retrieval substrate |
| PostgreSQL temporal/entity/relation graph projection | ACTIVE | graph representation/projection; Postgres remains authority |
| Neo4j | RETIRED | not current stack |
| Milvus | RETIRED | memory projections replaced by pgvector/Postgres |
| Elasticsearch memory projection | RETIRED | replaced by PostgreSQL FTS/data spine for canonical memory |
| DuckDB | RETIRED / STALE CONFIG | dependency retired; stale compose flag requires cleanup |
| Redis 7 | ACTIVE | STM/hot state/distributed coordination |
| Runtime lifecycle authority | ACTIVE | strong |
| CORTEX cognitive decision head | ACTIVE | strong, evidence loop still evolving |
| RuntimePolicy separation | ACTIVE | authorization authority |
| PromptRuntime authority | ACTIVE | canonical final assembly |
| NeuroRecall | ACTIVE/PARTIAL | governed retrieval, longitudinal proof still evolving |
| MemoryFormation/NeuroVault | ACTIVE/PARTIAL | canonical mutation/lifecycle direction |
| LangGraph | ACTIVE SPECIALIST | true graph workflows only |
| Agent Medusa | ACTIVE SPECIALIST | governed distributed multi-agent execution |
| Durable proactive commitments | NOT YET | major KARI OS agency gap |
| Universal WorldModel | TARGET | generic contracts required; do not buy a graph DB to fake it |
| Craft & Practice cognition | TARGET | generic core model; Brand becomes specialization |
| Connector/Domain/Skill taxonomy | TARGET/PARTIAL | extension governance must be formalized |
| Human-like cognitive continuity | PARTIAL | strong substrate, incomplete longitudinal nervous system |
| Exact-head beta release proof | NOT ASSUMED | must be observed on immutable SHA |

---

## 4. KARI OS Extension Boundary

### 4.1 Universal core primitives

Core may own domain-neutral concepts such as Entity, Person, Group, Role, Relationship, Artifact, Process, Resource, Rule, Goal, Commitment, Event, Context, Dependency and Outcome.

Before adding a vertical noun such as Employee, Department, CRM Opportunity, Family Rule, Patient, Campaign, Jira Issue or Salesforce Lead to core, prove why universal primitives plus a pack cannot represent it.

### 4.2 Connector

External capability/event bridge. Supplies typed capabilities and events. Does not own cognition, authorization, identity, provider routing or durable memory authority.

### 4.3 Domain Pack

Specialized ontology, schemas, prompts, policies, reasoning hints, evaluations and workflows using universal primitives. Examples: Enterprise, Personal, Family, Creative, Research.

### 4.4 Skill Pack

Reusable expert practice across domains. Examples: design, coding, writing, research, project management.

### 4.5 Autonomy

Autonomy is policy, not tool availability. Semantic levels are A0 Observe, A1 Recommend, A2 Prepare, A3 Approve then execute, A4 Delegated execution, A5 Managed execution. Packs may request behavior; RuntimePolicy/deployment governance grants or denies authority.

---

## 5. Memory and WorldModel Rules

- PostgreSQL/Supabase remains canonical durable memory authority.
- Redis remains bounded/hot/distributed state, not LTM authority.
- pgvector is the canonical vector substrate.
- PostgreSQL FTS is the canonical lexical substrate for current memory convergence.
- graph relations/projections are currently PostgreSQL-backed and rebuildable.
- Neo4j is retired.
- NeuroRecall retrieves; it does not persist.
- MemoryFormation + NeuroVault govern durable mutation.
- WorldModel is an ontology/contract and cognitive projection, not a database product.
- a graph accelerator requires benchmark evidence and remains derived unless an explicit architecture migration changes authority.
- no cross-tenant recall or projection.
- evidence/provenance/confidence/temporal semantics survive retrieval and reasoning boundaries.

---

## 6. Prompt-First Rules

Prompts are explicit, versioned, testable execution contracts. Prompt assembly respects system policy, persona/profile, tenant, authorized memory/evidence, intent, tools/extensions, provider capability, token budget, safety and output format.

Domain Packs and Skill Packs may contribute declared prompt contracts. They may not concatenate hidden prompt fragments through arbitrary runtime code or bypass PromptRuntime.

---

## 7. Security Rules

Enforce RBAC, tenant isolation, session validation, audit, extension permissions, manifest validation, secret redaction, safe errors, correlation IDs and policy-dominant autonomy.

Never accept user/tenant/role authority from client-controlled graph/agent/connector payloads. Direct execution surfaces must receive server-derived identity context and delegate through canonical Runtime/WorkflowRuntime.

---

## 8. Configuration Authority

Canonical configuration belongs under `src/ai_karen_engine/config/` and validated subsystem adapters.

Remove/migrate scattered direct reads and stale configuration. In particular, audit the stale `KARI_ENABLE_DUCKDB` compose setting because DuckDB is retired by the current dependency policy.

Every configuration option needs an owner, default where safe, environment override where appropriate, validation, documentation, telemetry exposure when relevant, and safe failure behavior.

Do not fix config debt by creating another config service.

---

## 9. Observability

Trace when applicable: correlation_id, request_id, user_id, tenant_id, session_id, conversation_id, event_type, intent, topology, provider, model, runtime_engine, fallback_level, degraded_mode, degradation_reason, response_source, memory_recall_count, connector/plugin/agent identity, autonomy level, commitment/trigger IDs, latency, status and safe error code.

Do not log passwords, raw tokens or secrets. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

---

## 10. Composition / No Hidden Construction

Stateful canonical services must not silently instantiate alternate provider registries, memory managers, NeuroRecall instances, reasoning engines, prompt runtimes, policy engines, workflow orchestrators, CORTEX instances, auth authorities, schedulers, graph stores or installation orchestrators.

Compatibility shims may remain only when they resolve to canonical composed instances and have explicit migration/removal conditions.

---

## 11. Current Sprint Program

### KARI-OS-0: architecture freeze

- codify domain-neutral cognitive substrate;
- classify Connector / Domain Pack / Skill Pack;
- freeze Runtime authority;
- freeze live stack truth and retired technology list.

### KARI-OS-1: authority convergence

Finish CORTEX -> RuntimePolicy -> Runtime -> WorkflowRuntime -> LangGraph identity/execution convergence. Direct agent/graph API paths may normalize and delegate but may not establish identity or alternate execution authority.

### KARI-OS-2: executable architecture immunity

Add CI tests rejecting:

- Neo4j/Milvus/Elasticsearch/DuckDB resurrection as canonical memory dependencies without ADR;
- domain-specific core leakage;
- connector/plugin execution bypassing RuntimePolicy;
- client-controlled tenant/auth context;
- direct memory writes outside formation/NeuroVault;
- duplicate provider/runtime/scheduler/graph authorities.

### KARI-OS-3: Universal WorldModel

Define minimal typed Entity/Relationship/Role/Group/Artifact/Process/Resource/Rule/Goal/Commitment/Event/Context/Outcome contracts. Reuse existing cognitive, temporal, evidence and memory contracts. Store canonical durable projections on the existing PostgreSQL spine first.

### KARI-OS-4: Durable Commitment Runtime

Expand `core/automation` with durable commitments, triggers, wakeups, recurrence, approvals, cancellation/expiry, context refresh, RuntimePolicy reauthorization, Medusa/WorkflowRuntime execution, outcomes, retry/follow-up and telemetry.

### KARI-OS-5: Craft & Practice

Add generic artifact/exemplar/technique/critique/constraint/rationale/accepted-rejected outcome/exception/evolution contracts. Institutional Brand Craft becomes a Domain/Skill specialization.

### KARI-OS-6: governed extension taxonomy

Manifest-level Connector/Domain Pack/Skill Pack type, permissions, capabilities, prompt contracts, schemas, data ownership, policy requirements, versioning and tests.

### KARI-OS-7: generality benchmark

Prove KARI Personal, KARI Family and KARI Enterprise run on the same cognitive core. A domain requiring a core fork fails the architecture benchmark.

### KARI-OS-8: longitudinal cognition benchmark

Prove restart-safe commitments, belief revision, contradiction, forgetting/retention, relationship continuity, preference drift, practice learning, provenance and multi-tenant isolation.

### TECH-DEBT-STACK-1

Audit/remove stale stack claims and configuration, starting with `KARI_ENABLE_DUCKDB`. Search docs, compose, scripts, tests and code for retired Neo4j/Milvus/Elasticsearch/DuckDB assumptions and either delete dead wiring or label historical documentation clearly.

---

## 12. Repository / Cleanup Rules

Before changing or deleting a service/path:

1. identify current owner;
2. search imports/references;
3. find stronger existing implementation;
4. classify active/misplaced/useful-incomplete/compatibility/experimental/dead/dangerous;
5. merge into canonical owner;
6. migrate consumers;
7. delete dead authority after reference audit;
8. add architecture tests preventing resurrection.

Never keep dead technology or code "just in case."

---

## 13. Required Proof

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

Architecture-affecting changes also require the applicable canonical GitHub gates. Never report CI/tests green unless actually observed on the exact head SHA.

---

## 14. Research-Guided Development

Research informs implementation; it does not gain architecture authority. New graph/vector/cognitive technologies require a benchmark against KARI's current PostgreSQL/pgvector/FTS/temporal-relation substrate and must document source, mechanism, deviation, compute assumptions, benchmark protocol, activation policy, migration cost and fallback behavior.

A paper using a graph database is not an ADR for KARI to adopt that database.

---

## 15. Documentation Authority

Read in this order:

1. `PROJECT_DEV_MANIFEST.md`
2. live code, migrations, dependency manifests, deployment composition and architecture tests
3. `docs/architecture/KARI_OS_MANIFEST.md`
4. `docs/architecture/KARI_OS_ADVERSARIAL_BURN.md`
5. current accepted ADR/dev sprint
6. subsystem documentation
7. historical sprint sheets as history only

If documentation disagrees with tested live behavior, classify it as documentation drift or implementation debt. Do not silently average conflicting documents into a fictional architecture.

---

## 16. Final Architecture Test

Before merging, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Is the proposed technology actually ACTIVE, or only historical/optional/target?
5. Can PostgreSQL/pgvector/FTS/current graph projection satisfy the requirement before adding a datastore?
6. Does the change preserve local-first and prompt-first behavior?
7. Does it preserve RBAC, tenant isolation, audit, credentials, retention/deletion and telemetry?
8. Does CORTEX remain cognitive decision authority without becoming executor?
9. Does RuntimePolicy remain authorization authority?
10. Does Runtime remain execution/lifecycle authority?
11. Does LangGraph remain graph-workflow-only?
12. Does Medusa remain specialist distributed execution rather than cognition/policy?
13. Does any subsystem silently construct an alternate authority?
14. Does evidence retain provenance/confidence/temporal/contradiction/scope semantics?
15. Is learning based on actual completed interaction/outcome?
16. Did a domain-specific noun leak into universal core?
17. Did an extension gain authority it should only consume?
18. What executable proof demonstrates the boundary?

If those answers are unclear, the design is not finished.

---

## 17. Canonical Mental Model

```text
KARI OS            = Domain-neutral cognitive operating substrate.
CORTEX Stage 1     = What evidence/context does KARI need?
RuntimePolicy A    = What evidence may KARI access now?
EvidenceResolver   = Resolve only authorized evidence/context.
CORTEX Stage 2     = Given evidence/context, what should KARI do?
RuntimePolicy B    = What final work is KARI allowed to perform?
Runtime            = Execute authorized work and own lifecycle.
Intelligence       = Produce typed signals/features/predictions.
CognitiveState     = Typed cognitive snapshot vocabulary.
NeuroRecall        = Retrieve useful authorized past information.
MemoryFormation    = Evaluate completed experiences/outcomes for formation.
NeuroVault         = Govern durable memory mutation/lifecycle.
PostgreSQL         = Canonical durable data/memory authority.
pgvector           = Canonical vector retrieval substrate.
PostgreSQL FTS     = Canonical lexical retrieval substrate.
Memory relations   = PostgreSQL-backed rebuildable graph projection.
Redis              = Bounded STM/hot state/distributed coordination.
Neo4j              = RETIRED, not current KARI stack.
Milvus             = RETIRED for canonical memory.
Elasticsearch      = RETIRED for canonical memory projection.
DuckDB             = RETIRED; stale config must not imply active use.
Reasoning          = Execute typed authorized reasoning strategies.
LangGraph          = Execute explicit graph workflow semantics only.
AgentMedusa        = Execute governed specialist-agent topology.
PromptRuntime      = Serialize authorized resolved context into prompt contracts.
ModelRuntime       = Resolve and execute eligible healthy provider/model.
Connector          = External capability/event bridge, never authority.
Domain Pack        = Specialized ontology/policy/workflow semantics.
Skill Pack         = Reusable expert practice.
WorldModel         = Universal ontology/contracts, not a database product.
Craft & Practice   = Generic learned ways-of-doing, not Brand-only cognition.
Observability      = Record what actually happened.
Configuration      = Supply validated environment, flags, budgets, endpoints and defaults.
```

### Architecture conservation law

```text
ONE RESPONSIBILITY
       ↓
ONE CANONICAL OWNER
       ↓
ONE CONTRACT
       ↓
ONE REGISTRY / CONFIG SOURCE where applicable
       ↓
ONE EXECUTION PATH
       ↓
EXECUTABLE BOUNDARY PROOF
```
