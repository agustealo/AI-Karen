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
- **CORTEX decides; Runtime executes.**
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
| Chat execution | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive decisions | `core/cortex/` and canonical cognitive contracts | providers, plugins, route handlers |
| Provider/model runtime | `core/model_runtime/` + canonical provider registry/routing | UI, API routes, Medusa |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents |
| Reasoning contracts/execution | canonical reasoning layer under `core/` | ad-hoc provider prompts |
| Graph workflows | `core/langgraph_orchestrator/` only when graph semantics are required | simple chat, generic orchestration |
| Multi-agent orchestration | `agent_medusa/` | provider routing, prompt authority, RBAC policy |
| Memory domain | `core/memory/` + canonical data adapters | NeuroRecall, agents, routes |
| Recall strategy | NeuroRecall/canonical recall components | duplicate storage |
| Persistence governance | NeuroVault/governed persistence components | duplicate memory database |
| Extensions/plugins | `extensions/` + governed action execution path | route-level execution, raw imports |
| Configuration | `src/ai_karen_engine/config/` + env | React fallbacks, launch scripts |
| Security | canonical auth/security + policy/RBAC enforcement | UI-only checks |
| Observability | `platform/observability/` | subsystem-specific shadow telemetry |
| Numeric metrics | canonical `MetricsCollector` and adapters | second Prometheus registries |
| Operator CLI | `ai_karen_engine.cli` | runtime/provider/prompt policy |

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
   |
   +--> context + memory recall coordination
   +--> CORTEX / RuntimePolicy decision signals
   +--> prompt assembly
   +--> execution topology
          |
          +--> direct model execution
          +--> reasoning
          +--> LangGraph workflow
          +--> AgentMedusa
          +--> governed tool/extension action
   |
   +--> provider/model runtime
   +--> streaming/response assembly
   +--> persistence
   +--> audit + telemetry
   v
Backend truth -> UI
```

The route does not choose providers, build prompts, recall memory, execute plugins, or create fallback model text.

---

## 4. CORTEX Contract

CORTEX is the **decision layer**, not an executor.

CORTEX may decide or signal:

- intent;
- capability requirements;
- reasoning depth/mode;
- verification requirements;
- memory routing;
- tool/extension eligibility;
- agent delegation/topology;
- policy/RBAC eligibility;
- confidence and reasoning hints.

CORTEX must not:

- call providers directly;
- construct final prompts;
- execute tools/plugins;
- write memory as an alternate store;
- run AgentMedusa work itself;
- become a second ChatRuntime.

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

Do not scatter prompt construction through route files, providers, agents, or plugins.

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
- UI model fallbacks;
- provider-specific prompt builders outside canonical prompt/runtime contracts;
- canned text represented as a model answer;
- scattered provider aliases or fallback orders.

A vLLM deployment is treated as an **OpenAI-compatible provider endpoint**, not a special built-in runtime authority.

---

## 7. Memory Model

Memory is the domain. Recall and governance are supporting responsibilities.

```text
STM       -> recent/session context
Episodic  -> meaningful interactions and decisions
LTM       -> durable facts/preferences/knowledge

NeuroRecall -> retrieval strategy, ranking, scoring, recall policy
NeuroVault  -> governed persistence, archive, backup/restore, deletion
```

Canonical durable data is PostgreSQL/Supabase-backed where configured. Redis may support bounded/ephemeral state.

**Milvus and Elasticsearch are not part of the current KAREN memory architecture and must not be reintroduced through stale documentation or implicit dependencies.**

Every memory operation must preserve tenant/user/session scope, deletion semantics, provenance where relevant, and auditability.

See `docs/development/MEMORY.md`.

---

## 8. Reasoning, LangGraph, and AgentMedusa

These are different tools with different authority.

### Reasoning

Use the canonical reasoning contracts for decomposition, evidence, verification, confidence, goals, constraints, and cognitive state. Reasoning augments execution; it does not become a provider router or memory store.

### LangGraph

Use LangGraph only for true graph semantics:

- branching workflows;
- checkpoint/resume;
- graph state;
- multi-step tool chains;
- human approval nodes;
- explicit long-running workflow topology.

Do not use LangGraph for ordinary chat or as a second general orchestrator.

### AgentMedusa

AgentMedusa is KAREN's multi-agent execution topology.

It owns planning, specialist coordination, dependency execution, arbitration, execution budgets, lifecycle, and trajectory assembly.

It does **not** own provider/model routing, prompt authority, RBAC/global policy, credentials, or memory storage.

See `docs/development/REASONING_LANGGRAPH_MEDUSA.md`.

---

## 9. Extensions, Plugins, Tools, and Actions

Canonical flow:

```text
manifest
 -> schema/manifest validation
 -> registry
 -> capability/permission resolution
 -> RuntimePolicy / RBAC eligibility
 -> ActionExecutionGate
 -> execution
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
- introduce policy-bypassing fallback paths.

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
plugin_id
agent_id
latency_ms
status
error_type
error_code
```

Emit structured lifecycle events for request, cognition/policy, recall, prompt, provider selection/execution, fallback/degradation, tools/extensions, persistence, and completion.

Use bounded metric labels. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

Canonical numeric metrics live under `platform/observability/`. Prometheus exposition is an adapter, not a second metrics authority.

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
- LangChain components only where they satisfy a specific adapter/workflow need and do not become architecture authority;
- AgentMedusa for governed multi-agent execution.

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

Never keep dead code "just in case".

See `docs/development/REPOSITORY_ENGINEERING.md`.

---

## 15. Coding Standards

- Prefer clear modules/classes/typed contracts over giant procedural files.
- Extend existing canonical modules before adding new folders/services.
- Keep functions focused and side effects explicit.
- Avoid globals for request/user/tenant state.
- Use dependency injection or explicit context for runtime dependencies.
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
8. What executable proof demonstrates the behavior and the architecture boundary?

If those answers are unclear, the design is not finished.
