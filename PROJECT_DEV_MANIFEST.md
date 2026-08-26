# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract
> **Applies to:** backend, runtime, AI/ML, agents, extensions, APIs, UI integration, infrastructure, tests, and documentation
> **Rule:** When this manifest conflicts with an older implementation note, sprint sheet, or legacy README, verify live code and prefer the current canonical owner documented here.

AI KAREN is a **local-first, prompt-first, modular AI runtime** with governed execution, durable memory, provider/model orchestration, cognitive decisioning, multi-agent execution, extensibility, RBAC, audit, and first-class observability.

The project is not framework-first. Libraries are implementation tools. **KAREN's own contracts and authority boundaries remain primary.**

---

## 1. Engineering Mission

Build one coherent runtime in which every major responsibility has:

1. one owner;
2. one canonical interface/contract;
3. one runtime path;
4. one registry/config source where applicable;
5. explicit security and tenant boundaries;
6. observable lifecycle events;
7. tests proving the boundary.

### Core principles

- **Local-first**: local models and infrastructure are preferred when suitable and healthy.
- **Prompt-first**: prompts are explicit, versioned, testable execution contracts.
- **Runtime-authoritative**: routes, UI, agents, providers, and plugins do not become alternate orchestration runtimes.
- **CORTEX is KAREN's cognitive head. CORTEX decides; Runtime executes.**
- **DRY by authority**: one responsibility -> one owner -> one registry/config -> one execution path.
- **Secure by enforcement**: RBAC, tenancy, credentials, permissions, and audit are backend/runtime responsibilities.
- **Observable by default**: important decisions and execution stages emit structured events and bounded metrics.
- **Typed and async-safe**: public cognitive/runtime boundaries are typed; concurrency and cancellation are explicit.
- **Config-driven**: provider availability, defaults, feature flags, URLs, ports, model choices, and fallbacks are configuration, not scattered constants.
- **Honest degradation**: never fabricate a model response to hide an unavailable capability.
- **Test-proven architecture**: architecture rules must be executable as tests where practical.

---

## 2. Canonical Authority Map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP ingress | `api_routes/` + canonical app composition | providers, prompts, memory recall, orchestration |
| App entrypoint | `ai_karen_engine.app:create_app` | Docker scripts, legacy root server runners |
| Chat/request execution lifecycle | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive executive decisions | `core/cortex/` and canonical cognitive contracts | providers, persistence, direct tool execution |
| Memory-access strategy and learned recall policy | NeuroRecall/canonical recall components | storage, provider execution, prompt synthesis |
| Semantic retrieval and novelty primitives | canonical Soft Reasoning / retrieval components | cognitive executive policy, persistence, workflow execution |
| Reasoning/synthesis execution | ICE/canonical reasoning layer under `core/` | provider routing, durable memory writes, route orchestration |
| Provider/model runtime | `core/model_runtime/` + canonical provider registry/routing | UI, API routes, CORTEX |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents, NeuroRecall |
| Graph workflows | `core/langgraph_orchestrator/` only when graph semantics are required | simple chat, generic orchestration, cognitive authority |
| Multi-agent orchestration | `agent_medusa/` | provider routing, prompt authority, RBAC policy |
| Memory domain | `core/memory/` + canonical data adapters | NeuroRecall, ICE, agents, routes |
| Persistence governance | NeuroVault/governed persistence components | reasoning engines, recall engines, duplicate memory databases |
| Extensions/plugins | `extensions/` + governed action execution path | route-level execution, raw imports |
| Configuration | `src/ai_karen_engine/config/` + env | React fallbacks, launch scripts |
| Security | canonical auth/security + policy/RBAC enforcement | UI-only checks |
| Observability | `platform/observability/` | subsystem-specific shadow telemetry |
| Numeric metrics | canonical `MetricsCollector` and adapters | second Prometheus registries |
| Operator CLI | `ai_karen_engine.cli` | runtime/provider/prompt policy |

### 2.1 Cognitive Authority Hierarchy

KAREN has one cognitive head: **CORTEX**. Runtime owns execution, but Runtime does not become a second cognitive decision-maker. ICE, NeuroRecall, Soft Reasoning, LangGraph, AgentMedusa, providers, tools, and memory systems are capabilities or execution mechanisms subordinate to the canonical CORTEX + Runtime contract.

```text
                              CORTEX
                     cognitive executive authority
                               |
          +--------------------+--------------------+
          |                    |                    |
          v                    v                    v
      NeuroRecall             ICE            workflow/topology
 memory-access policy   reasoning/synthesis   decision signals
          |                    |                    |
          v                    |                    v
   Soft Reasoning              |               LangGraph or
 retrieval primitives         |               AgentMedusa
          |                    |                    |
          +--------------------+--------------------+
                               |
                         CORTEX decision
                               |
                               v
                            Runtime
                       execution authority
                               |
       +-----------------------+------------------------+
       |                       |                        |
       v                       v                        v
 provider/model runtime   tools/extensions        memory services
                                                       |
                                                       v
                                                  NeuroVault
                                            governed persistence
```

This diagram is an authority map, not an implementation requirement that every request traverse every component.

### 2.2 Head vs. Body Rule

Use this mental model consistently:

- **CORTEX = executive function / cognitive head.** It decides what kind of cognition is needed and what is eligible.
- **Runtime = request lifecycle and execution authority.** It performs the approved work and coordinates side effects.
- **ICE = reasoning faculty.** It performs governed reasoning, synthesis, reflection, decomposition, or verification work requested through the runtime plan.
- **NeuroRecall = memory-access intelligence.** It selects recall strategy, ranks/fuses candidates, estimates transfer utility, and may learn which memories are useful to recall.
- **Soft Reasoning (SR) = retrieval machinery.** It owns semantic retrieval primitives, novelty/similarity heuristics, lightweight candidate generation, and retrieval-local scoring only.
- **LangGraph = graph workflow machinery.** It executes explicit graph workflows when CORTEX/Runtime select graph semantics.
- **AgentMedusa = multi-agent execution topology.** It executes governed specialist-agent plans when selected.
- **NeuroVault = persistence governance.** It controls durable memory writes, lifecycle, deletion, archive, and recovery.

### 2.3 Dependency Direction Rules

The following are architectural invariants:

```text
API/routes -> Runtime
Runtime -> CORTEX
Runtime -> execution capabilities selected by CORTEX
CORTEX -> decision contracts only
NeuroRecall -> SR/memory candidate sources
ICE -> reasoning inputs/contracts
Runtime -> provider/tool/workflow execution
Runtime -> memory candidate submission
NeuroVault -> durable persistence adapters
```

Forbidden reverse authority:

- SR must not call or direct CORTEX.
- NeuroRecall must not execute providers, tools, plugins, or workflows.
- ICE must not choose providers or persist durable memory directly.
- LangGraph must not become the global router or cognitive head.
- AgentMedusa must not become the global router or cognitive head.
- providers must not assemble canonical prompts or choose memory policy.
- memory stores must not decide recall strategy.
- NeuroVault must not decide reasoning strategy.

### 2.4 No Hidden Construction Rule

Canonical cognitive/runtime dependencies must be composed explicitly at the runtime/application composition boundary. Subsystems must not silently instantiate alternate canonical engines when a dependency is omitted.

Forbidden production pattern:

```python
self.recall_engine = recall_engine or SoftReasoningEngine()
```

when `SoftReasoningEngine` is the canonical shared retrieval dependency. The same rule applies to provider registries, memory services, ICE, NeuroRecall, and workflow orchestrators.

Why: implicit construction can create split-brain runtime state in which two apparently integrated components recall from, write to, or observe different service instances.

Tests must prove canonical dependency identity where shared state or authority is required.

---

## 3. Primary Runtime Flow

```text
Client / UI
   |
   v
Thin API route
   |  validate request, auth/session/tenant context, request/correlation IDs
   v
ChatRuntime
   |  normalize request + assemble safe execution context
   v
CORTEX
   |  intent, policy, capability, recall, reasoning, verification,
   |  tool/agent/workflow eligibility and topology signals
   v
ChatRuntime
   |
   +--> NeuroRecall when memory access is authorized/needed
   |       +--> Soft Reasoning / canonical memory candidate sources
   |       +--> ranked/fused/abstaining recall result
   |
   +--> canonical prompt assembly
   |
   +--> selected execution topology
   |       +--> direct model execution
   |       +--> ICE reasoning/synthesis
   |       +--> LangGraph workflow
   |       +--> AgentMedusa
   |       +--> governed tool/extension action
   |
   +--> provider/model runtime
   +--> streaming/response assembly
   +--> learning/memory candidates
   +--> NeuroVault-governed persistence
   +--> audit + telemetry
   v
Backend truth -> UI
```

Runtime legitimately appears both before and after CORTEX because Runtime owns the request lifecycle. It receives and normalizes the request, asks the cognitive head for decisions, then executes those decisions. This does not make Runtime a second cognitive head.

The route does not choose providers, build prompts, recall memory, execute plugins, or create fallback model text.

---

## 4. CORTEX Contract

CORTEX is KAREN's **cognitive executive authority**, not an executor and not merely a policy gate.

CORTEX may decide or signal:

- intent and domain interpretation;
- goal/state interpretation;
- capability requirements;
- reasoning depth/mode;
- verification requirements;
- whether recall is needed;
- recall class/scope/strategy hints to NeuroRecall;
- tool/extension eligibility;
- agent delegation/topology;
- whether graph workflow semantics are warranted;
- policy/RBAC action eligibility;
- confidence-domain and reasoning hints;
- abstention/escalation/clarification requirements;
- execution constraints and budgets.

CORTEX must not:

- call providers directly;
- construct final prompts;
- execute tools/plugins;
- persist or directly mutate memory;
- perform low-level vector retrieval itself;
- run ICE, LangGraph, or AgentMedusa work itself;
- own provider/model fallback execution;
- become a second ChatRuntime.

CORTEX returns typed decisions. Runtime executes them through canonical capabilities.

See `docs/development/CORTEX_RUNTIME.md`.

---

## 5. Prompt-First Rules

Prompts are versioned execution contracts.

Canonical prompt assembly must account for:

1. system policy;
2. task/output contract;
3. explicit turn override;
4. explicit user preference;
5. selected assistant-profile defaults;
6. global defaults;
7. tenant context;
8. memory context;
9. intent/reasoning requirements;
10. tools/extensions;
11. provider capabilities;
12. token budget;
13. safety/output schema.

Do not scatter prompt construction through route files, providers, agents, NeuroRecall, or plugins.

Do not request hidden chain-of-thought. Prefer explicit evidence, verification, confidence, constraints, and structured result contracts.

---

## 6. Provider and Model Runtime

Provider/model availability, selection, execution, and fallback are centralized.

Target fallback behavior is configuration-driven and local-first:

```text
requested provider/model
 -> local primary
 -> custom OpenAI-compatible local endpoint (including vLLM deployments)
 -> Transformers where enabled
 -> Ollama when enabled/healthy
 -> external provider when explicitly enabled
 -> honest unavailable/degraded result
```

### Forbidden

- `builtin_vllm` resurrection;
- route-level provider selection;
- CORTEX-level provider execution;
- UI model fallbacks;
- provider-specific prompt builders outside canonical prompt/runtime contracts;
- canned text represented as a model answer;
- scattered provider aliases or fallback orders.

A vLLM deployment is treated as an **OpenAI-compatible provider endpoint**, not a special built-in runtime authority.

---

## 7. Memory and Recall Model

Memory is the domain. Recall intelligence and persistence governance are supporting responsibilities with separate owners.

```text
STM       -> recent/session context
Episodic  -> meaningful interactions, decisions, outcomes, and reusable experiences
LTM       -> durable facts/preferences/knowledge

Soft Reasoning -> retrieval primitives, similarity/novelty, lightweight candidate generation
NeuroRecall    -> memory-access strategy, candidate fusion/ranking, recall policy, transfer utility
NeuroVault     -> governed persistence, lifecycle, archive, backup/restore, deletion
```

### 7.1 Recall authority

NeuroRecall is subordinate to CORTEX as a cognitive capability. It may decide **which authorized memories are useful to recall and how strongly they should influence context**, but it may not decide the overall user intent, execute tools, choose providers, synthesize the final answer, or own durable storage.

NeuroRecall may own:

- recall strategy selection within the scope authorized by CORTEX/Runtime;
- candidate-source coordination;
- semantic/temporal/case/graph candidate fusion;
- learned case-selection policy;
- outcome/transfer-utility scoring;
- contradiction/redundancy/diversity resolution;
- scope-aware ranking;
- budget-aware recall packing;
- recall abstention/disposition;
- recall confidence as a distinct confidence domain;
- feedback on whether recalled cases transferred positively or negatively.

NeuroRecall must not own:

- memory database/storage authority;
- provider/model execution;
- prompt assembly;
- final synthesis;
- tool/plugin execution;
- global RBAC policy;
- hidden parallel conversation state.

### 7.2 Soft Reasoning authority

Soft Reasoning is intentionally narrower than NeuroRecall. It is a retrieval primitive, not a second cognitive head.

It may own:

- embeddings through canonical ML capabilities;
- semantic similarity search;
- retrieval-local recency heuristics;
- novelty scoring;
- lightweight candidate generation;
- bounded local reranking tied to retrieval semantics.

It must not own:

- case utility/outcome policy;
- cross-source recall authority;
- final recall disposition;
- durable write policy;
- reasoning synthesis;
- provider/model routing;
- workflow execution.

Do not call `1 - top_similarity` "entropy". Canonical naming is `novelty_score`, `retrieval_gap`, or another explicitly defined retrieval-uncertainty term. Reserve entropy terminology for actual distribution/policy entropy.

### 7.3 Persistence authority

ICE, SR, NeuroRecall, CORTEX, agents, and routes do not persist durable memory directly. They may emit typed memory/learning candidates or observations. Runtime submits eligible candidates to governed memory policy and NeuroVault.

```text
reasoning / execution / recall outcome
        |
        v
MemoryCandidate / LearningObservation
        |
        v
Runtime + memory policy
        |
        v
NeuroVault
        |
        v
canonical durable memory adapters
```

### 7.4 Scope and provenance

Every production recall/persistence contract must carry explicit scope and provenance sufficient to enforce:

- tenant isolation;
- user/workspace/project scope where applicable;
- session/conversation scope where applicable;
- memory namespace/class;
- source/provenance;
- creation/update timestamps;
- policy/schema version;
- embedding/model provenance where vectorization is used;
- lifecycle state such as active, stale, superseded, invalid, quarantined, or expired.

No implicit production `tenant_id="default"` fallback is permitted.

### 7.5 Current storage architecture

Canonical durable data is PostgreSQL/Supabase-backed where configured. Redis may support bounded/ephemeral state.

**Milvus and Elasticsearch are not part of the current KAREN memory architecture and must not be reintroduced through stale documentation, copied examples, default constructors, or implicit dependencies.** Any future addition requires an explicit architecture decision and manifest update.

See `docs/development/MEMORY.md`.

---

## 8. Reasoning, ICE, LangGraph, and AgentMedusa

These are different capabilities with different authority.

### ICE / reasoning

ICE is a reasoning faculty under CORTEX-directed runtime execution. It may perform governed synthesis, decomposition, reflection, evidence integration, verification coordination, and other reasoning modes defined by canonical contracts.

ICE does not:

- choose the canonical provider/model routing path;
- become a memory store;
- directly persist durable memory;
- become the global cognitive router;
- silently construct an alternate SR/NeuroRecall instance;
- own route/application lifecycle.

Reasoning augments execution; it does not become a provider router or memory authority.

### LangGraph

Use LangGraph only for true graph semantics:

- branching workflows;
- checkpoint/resume;
- graph state;
- multi-step tool chains;
- human approval nodes;
- explicit long-running workflow topology.

CORTEX/Runtime decide when graph semantics are warranted. LangGraph executes the selected graph. Do not use LangGraph for ordinary chat or as a second general orchestrator/cognitive head.

### AgentMedusa

AgentMedusa is KAREN's multi-agent execution topology.

It owns planning/execution inside an authorized multi-agent topology, specialist coordination, dependency execution, arbitration, execution budgets, lifecycle, and trajectory assembly.

It does **not** own provider/model routing, canonical prompt authority, RBAC/global policy, credentials, memory storage, or CORTEX's executive decision authority.

See `docs/development/REASONING_LANGGRAPH_MEDUSA.md`.

---

## 9. Extensions, Plugins, Tools, and Actions

Canonical flow:

```text
manifest
 -> schema/manifest validation
 -> registry
 -> capability/permission resolution
 -> CORTEX / RuntimePolicy eligibility
 -> ActionExecutionGate
 -> Runtime execution
 -> output validation
 -> audit + telemetry
```

A manifest declares capability. It does not grant authorization.

Extensions must define, as applicable:

- stable ID/version;
- capabilities;
- permissions;
- input/output schemas;
- prompt contract references;
- credentials required;
- network/filesystem requirements;
- side-effect class/idempotency behavior;
- tenant/RBAC requirements;
- health/dependency requirements.

See `docs/development/EXTENSIONS_TOOLS.md`.

---

## 10. Security Rules

Must preserve:

- authentication/session validation;
- RBAC;
- tenant isolation;
- least privilege;
- credential/secret redaction;
- plugin/action permission checks;
- audit logs;
- safe exception translation;
- request/correlation IDs;
- production fail-closed behavior.

### Never

- rely on UI checks for authorization;
- use `tenant_id="default"` as a security fallback in production paths;
- execute plugins/actions without governed permission checks;
- log secrets/tokens;
- retain production dev bypasses;
- introduce policy-bypassing fallback paths;
- allow recalled or learned memory to bypass current security/policy checks;
- persist raw untrusted tool/model output as authoritative memory without validation/provenance.

See `docs/development/SECURITY_OBSERVABILITY.md`.

---

## 11. Observability Rules

Canonical structured runtime metadata includes, when applicable:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
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
recall_strategy
recall_disposition
reasoning_mode
plugin_id
agent_id
latency_ms
status
error_type
error_code
```

Emit structured lifecycle events for request, CORTEX decisions/policy, recall, prompt, provider selection/execution, reasoning, fallback/degradation, tools/extensions, persistence, and completion.

Use bounded metric labels. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

Canonical numeric metrics live under `platform/observability/`. Prometheus exposition is an adapter, not a second metrics authority.

Do not describe a retrieval/evidence graph as hidden "thought" or chain-of-thought. Observable graphs represent decision, evidence, recall, workflow, or influence relationships only.

---

## 12. Languages, Frameworks, and Infrastructure

### Backend

- **Python**: primary AI/runtime/backend language.
- **FastAPI / ASGI**: HTTP application/API layer.
- **Uvicorn**: ASGI process server.
- **Pydantic/typed contracts**: request/config/runtime validation where used.
- **asyncio**: asynchronous runtime and I/O coordination.

### AI / orchestration

- local and remote model providers behind KAREN provider contracts;
- OpenAI-compatible APIs for compatible endpoints including vLLM deployments;
- LangGraph only for graph workflows;
- LangChain/LlamaIndex/DSPy/Haystack components only where they satisfy a specific adapter, retrieval, evaluation, or workflow need and do not become architecture authority;
- AgentMedusa for governed multi-agent execution;
- imported research systems such as AgentFly/Memento are experimental/reference implementations until their useful capabilities are extracted behind KAREN contracts.

### Data

- **PostgreSQL / Supabase**: durable application/data platform where configured;
- **Redis**: bounded cache/session/ephemeral runtime use where configured;
- object storage where needed for artifacts/media;
- no Milvus/Elasticsearch memory dependency in the current architecture.

### Frontend

The UI displays backend truth. It must not invent provider/model availability, persistence success, routing, or degraded state.

### Infrastructure

- Docker/OCI images;
- Docker Compose as a deployment/development adapter, not architecture authority;
- GitHub Actions/CI for proof/build/deployment workflows;
- canonical app target: `ai_karen_engine.app:create_app`.

---

## 13. API Design Rules

API routes are thin ingress.

They may:

- parse/validate transport data;
- resolve authenticated user/session/tenant context;
- establish request/correlation IDs;
- call canonical runtime/application services;
- translate known domain/runtime exceptions to HTTP responses.

They may not:

- choose providers/models;
- build prompts;
- run memory recall;
- execute plugins/tools directly;
- implement fallback orchestration;
- return fake success/persistence states.

Admin APIs belong in the dedicated admin surface and preserve RBAC/audit.

---

## 14. Repository Rules

Canonical application code belongs under `src/ai_karen_engine/`.

Before creating a file/module/service:

1. search for an existing owner;
2. determine whether the new behavior extends that owner;
3. identify duplicate/legacy implementations;
4. centralize rather than fork authority;
5. add tests proving ownership.

### Legacy classification

Every suspicious implementation is one of:

- active/correct: keep;
- misplaced: move/merge;
- useful/incomplete: complete/extract;
- compatibility shim: centralize, document, give a removal condition;
- experimental: feature flag;
- replaced/dead: delete after reference audit;
- dangerous: disable/replace immediately while preserving required security behavior.

Imported research/demo harnesses that own their own providers, planners, tool execution, memory stores, or benchmark loops must remain outside canonical runtime authority until decomposed into KAREN-owned capabilities.

Never keep dead code "just in case".

See `docs/development/REPOSITORY_ENGINEERING.md`.

---

## 15. Coding Standards

- Prefer clear modules/classes/typed contracts over giant procedural files.
- Extend existing canonical modules before adding new folders/services.
- Keep functions focused and side effects explicit.
- Avoid globals for request/user/tenant state.
- Use dependency injection or explicit context for runtime dependencies.
- Canonical shared services must not be silently reconstructed inside subordinate components.
- Use structured logging; no `print()` in runtime paths.
- Do not catch broad exceptions merely to fabricate success.
- Async code must define ownership of tasks, cancellation, timeouts, and concurrency limits.
- Public contracts require types and stable semantics.
- Compatibility shims require an identified canonical replacement and deletion condition.
- Comments explain architectural intent or non-obvious constraints, not line-by-line narration.

---

## 16. Required Proof

Choose the relevant subset, but architecture changes need real proof.

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Frontend changes additionally use the repository's configured equivalents of:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Infrastructure changes:

```bash
docker compose config
```

Cognitive/memory authority changes must additionally prove, where applicable:

```text
[ ] CORTEX remains the sole cognitive executive authority
[ ] Runtime remains the sole request/execution authority
[ ] ICE has no direct durable-memory write path
[ ] NeuroRecall has no provider/tool/workflow execution path
[ ] SR has no learned case-policy or durable-persistence authority
[ ] shared canonical dependencies are explicitly injected
[ ] tenant/scope is explicit for production recall
[ ] recall confidence is not conflated with answer/evidence confidence
[ ] novelty_score is not mislabeled as entropy
[ ] current memory-storage architecture is respected
```

When deleting code, also prove no stale imports/references remain.

Never report CI/tests green unless actually observed.

---

## 17. Documentation Authority and Maintenance

Read in this order:

1. **`PROJECT_DEV_MANIFEST.md`**: project-wide contract and authority map.
2. **`docs/development/ARCHITECTURE_AUTHORITY.md`**: detailed boundaries and runtime topology.
3. Subsystem document matching the code being changed.
4. Current ADRs for accepted design decisions.
5. Live implementation and architecture tests.
6. Historical sprint sheets only as history, never as current authority without verification.

Documentation must distinguish:

- **Canonical**: current supported owner/path.
- **Transitional**: still live but scheduled for convergence/removal.
- **Historical**: describes a completed/retired phase.
- **Forbidden**: architecture that must not be reintroduced.

Any architecture-changing PR/commit should update this manifest or the relevant subsystem doc when it changes ownership, contracts, supported libraries, data stores, provider behavior, security behavior, or runtime topology.

---

## 18. Developer Documentation Map

- `docs/development/ARCHITECTURE_AUTHORITY.md`
- `docs/development/CORTEX_RUNTIME.md`
- `docs/development/MEMORY.md`
- `docs/development/REASONING_LANGGRAPH_MEDUSA.md`
- `docs/development/EXTENSIONS_TOOLS.md`
- `docs/development/SECURITY_OBSERVABILITY.md`
- `docs/development/REPOSITORY_ENGINEERING.md`
- `docs/development/TESTING_RELEASE.md`

---

## 19. Final Architecture Test

Before merging a change, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Is touched code active, misplaced, legacy, compatibility, experimental, dead, or dangerous?
5. Can central config/registry/contracts replace hardcoding?
6. Does the change preserve prompt-first and local-first behavior?
7. Does it preserve RBAC, audit, tenant isolation, credentials, and telemetry?
8. Does it preserve the CORTEX-head / Runtime-execution hierarchy?
9. Does any subordinate capability silently construct or mutate an alternate authority?
10. What executable proof demonstrates the behavior and the architecture boundary?

If those answers are unclear, the design is not finished.
