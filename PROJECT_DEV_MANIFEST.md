# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract and live architecture truth map
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, installation/bootstrap, infrastructure, tests, and documentation
> **Live audit baseline:** `main` at `f71dd27bc881598d728af2c75fbafc491f20c369` on 2026-08-28
> **Active first-run hardening slice:** `feature/first-class-first-run-20260828`
> **Rule:** Live code is implementation truth. This manifest separates implemented behavior from target architecture. Historical sprint sheets, compatibility layers, framework conventions, and research systems never override it.

AI KAREN is a **local-first, prompt-first, modular AI runtime** evolving toward human-like cognitive continuity with durable governed memory, evidence-backed self/user/relationship models, provider/model orchestration, governed reasoning, RBAC, audit, extensibility, first-class installation/bootstrap, and observable system behavior.

KAREN is not framework-first. Libraries, research systems, model runtimes, agent harnesses, workflow engines, setup wizards, and infrastructure helpers are subordinate capabilities behind KAREN-owned contracts.

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
- **Runtime-authoritative:** routes, UI, providers, agents, plugins, and workflow engines never become alternate chat runtimes.
- **CORTEX is KAREN's central cognitive authority. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **Evidence access is authorization-sensitive.** CORTEX may request evidence, but RuntimePolicy must authorize governed access before Runtime resolves it.
- **DRY by authority:** one responsibility -> one owner -> one execution path.
- **Typed and async-safe:** public cognitive/runtime boundaries are typed; budgets, cancellation, concurrency, and distributed ownership are explicit.
- **Config-driven:** providers, models, endpoints, fallbacks, feature flags, environment, budgets, security modes, and installation settings belong behind canonical validated configuration.
- **Migration-owned schema:** production runtime verifies required schema but does not silently create missing migration-owned tables.
- **Honest degradation:** unavailable capabilities produce explicit degraded/unavailable results, never fabricated model output.
- **Evidence-preserving cognition:** retrieval evidence must not be flattened into untyped text before reasoning, prompting, or model revision.
- **Learning is outcome-aware:** durable formation is evaluated after execution from the actual interaction/outcome, not only predicted before generation.
- **First run is lifecycle, not UI:** a fresh installation must prove durable identity, tenant scope, one-time bootstrap, restart survival, and fail-closed setup behavior.
- **Test-proven architecture:** architecture rules are executable where practical.

### 1.1 Cognitive north star

The target is cognitive continuity, not merely long-term memory:

```text
experience
 -> interpret
 -> identify evidence needs
 -> authorize evidence access
 -> retrieve/resolve evidence
 -> revise current cognition
 -> decide
 -> authorize execution
 -> act
 -> observe outcome
 -> evaluate learning/formation
 -> consolidate
 -> revise beliefs/models
 -> update future cognition
```

Memory, evidence, claims, beliefs, knowledge, identity, user understanding, relationship continuity, temporal reasoning, goals, commitments, metacognition, retention/forgetting, and outcome learning remain distinct concerns with explicit contracts.

---

## 2. Canonical Authority Map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP ingress | `api_routes/` + app composition | provider choice, prompts, recall, orchestration, durable bootstrap writes |
| Request lifecycle | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive decisions | `core/cortex/` | authorization, provider execution, persistence |
| Signal extraction / ML inference | `core/intelligence/` | final cognitive authority, execution, authorization |
| Cognitive state vocabulary | `core/cognitive/` | orchestration, provider execution, persistence |
| Context vocabulary/resolution primitives | `core/context/` | independent cognitive authority |
| Runtime authorization | `core/runtime/policy/` | cognitive classification, provider execution |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents, memory retrieval |
| Reasoning execution | `core/reasoning/` | provider routing, durable writes, global orchestration |
| Soft Reasoning | `core/reasoning/soft_reasoning/` | memory authority, provider routing |
| Memory recall strategy | NeuroRecall under `core/memory/` | durable storage, provider/tool execution |
| Memory formation / durable mutation | MemoryFormation + NeuroVault | CORTEX, reasoning, recall |
| Self/User/Relationship models | `core/personalization/` contracts/services | global execution, policy authorization |
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX, first-run auth |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, global routing |
| Multi-agent execution | AgentMedusa | provider routing, global policy |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Authentication/session/RBAC identity | canonical auth services + backend policy | UI, client storage, setup wizard |
| Production schema bootstrap | migrations / deployment tooling | runtime routes, AuthService table creation |
| First-run durable owner/tenant bootstrap | canonical `AuthService` | UI, routes, provider runtime, ad-hoc scripts |
| First-run HTTP transport | `api_routes/auth/auth.py` | durable tenant/user creation logic |
| First-run production proof | `scripts/ci/production-first-boot-smoke.sh` + CI workflow | documentation-only/manual claims |
| Observability | `platform/observability/` | subsystem shadow telemetry |
| Configuration | `src/ai_karen_engine/config/` + validated adapters | React fallbacks, scattered direct environment reads |

**CORTEX is the central cognitive authority, not the supreme system authority.** Security/policy, execution, persistence, provider routing, authentication, installation bootstrap, schema migration, prompt assembly, observability, and configuration remain independent authorities in their own domains.

---

## 3. Live Implementation Truth: 2026-08-28

### 3.1 Actual canonical chat path

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
      |      +--> capabilities
      |      +--> reasoning modes
      |      +--> side-effect constraints
      |
      v
ExecutionDecision
      |
      v
ChatRuntime builds AuthorizedExecutionPlan
      |
      +--> memory recall when requested/authorized
      +--> DIRECT -> PromptRuntime -> ExpressionGateway -> model runtime
      +--> REASONING -> RuntimeReasoningBridge -> ReasoningExecutor
      +--> WORKFLOW / MULTI-AGENT -> WorkflowRuntime
      +--> persistence / trajectory / outcome / telemetry
```

Routes remain ingress. CORTEX remains decision-only. Runtime executes. Provider/model truth remains backend-owned.

### 3.2 CORTEX and Intelligence reality

`CortexExecutionDecider` is active as the cognitive decision head and consumes subordinate `IntelligenceRuntime` signals. The classifier hardening merged on 2026-08-28 preserves explicit unknown/weak-signal rejection and keeps Intelligence signal-producing rather than execution-authoritative.

Current cognitive limitations remain:

- the ordinary CORTEX path is still substantially single-pass before resolved evidence;
- compatibility heuristics still exist in decision/routing surfaces and require convergence;
- richer typed CognitiveContext is not yet the universal ordinary-chat envelope;
- direct/hardcoded cognitive/runtime config debt still exists and must migrate behind validated config;
- two-stage evidence authorization/decision remains target work, not current truth.

### 3.3 RuntimePolicy reality

RuntimePolicy remains separate from CORTEX. It is the authorization authority for execution eligibility and must also become the authorization authority for governed evidence access in the target two-stage cognitive loop.

No new policy engine should be introduced for evidence access.

### 3.4 Memory and formation reality

KAREN has substantial STM/episodic/LTM, NeuroRecall, formation, and NeuroVault foundations. Tenant-aware recall/persistence paths exist, but evidence-preservation and post-execution formation convergence remain active work.

Rules remain:

- recall does not persist;
- reasoning does not persist;
- CORTEX does not persist;
- Runtime coordinates authorized formation;
- MemoryFormation + NeuroVault govern durable mutation;
- recall/read and write/formation decisions must be independent;
- formation should evaluate the actual completed interaction/outcome.

### 3.5 Provider/model runtime reality

Provider/model availability, health, selection, execution, and fallback are backend runtime responsibilities. UI must display backend truth only.

Local-first capability may include OpenAI-compatible local endpoints, Transformers, Ollama, and other registered runtimes according to current validated configuration. Legacy `builtin_vllm` must not be resurrected as a duplicate provider authority.

### 3.6 Distributed Medusa reality

Medusa execution control now uses distributed ownership/fencing semantics so only the worker owning the concrete task can cancel it, while remote workers coordinate cancellation through durable distributed state. Medusa remains an execution topology, not a second runtime, CORTEX, or provider router.

### 3.7 First-run / installation bootstrap reality

KAREN now has a canonical first-run contract centered on durable backend truth.

Active implementation:

```text
Deployment/migrations
  -> apply migration-owned auth schema

AuthService.initialize()
  -> validate auth configuration
  -> verify required migration-owned tables exist

GET /api/auth/first-run
  -> AuthService.is_first_run()
  -> true only when durable AuthUser count is zero

POST /api/auth/first-run/setup
  -> AuthService.create_first_admin()
  -> PostgreSQL transaction advisory lock
  -> re-check durable user count under lock
  -> resolve/create installation tenant
  -> create verified first owner
  -> roles: admin + user
  -> enforce durable tenant assignment
  -> emit auth.first_admin.created audit event
  -> authenticate through normal auth/session path
```

**Implemented first-run invariants:**

- production auth initialization validates configuration;
- required auth tables are migration-owned and preflight-verified;
- runtime does not create missing production auth schema;
- first-admin bootstrap is serialized across workers with a transaction-scoped PostgreSQL advisory lock;
- durable user count is rechecked after lock acquisition;
- first owner receives durable tenant scope;
- first owner receives backend `admin` and `user` roles;
- completed bootstrap rejects later setup attempts;
- setup emits an auth audit event;
- token/session issuance uses the normal auth authority;
- browser session uses the canonical HTTP-only session cookie path.

**Executable production burn:** `scripts/ci/production-first-boot-smoke.sh` now proves against a fresh isolated stack:

1. PostgreSQL/pgvector readiness;
2. password-protected Redis readiness;
3. canonical migrations on an empty database;
4. real production API image liveness;
5. auth readiness;
6. `first_run_required=true` before setup;
7. first owner creation and authentication;
8. durable `tenant_id`, username, `admin`, and `user` roles;
9. second setup attempt is denied with HTTP 400;
10. database contains exactly one bootstrap user;
11. an active durable tenant exists;
12. authenticated `/api/auth/me` works;
13. exact production image restarts;
14. first-run remains completed after restart;
15. owner can log in and resolve identity after restart.

Architecture guard: `tests/architecture/test_first_run_system_contract.py` proves the route remains thin, AuthService owns one-time durable bootstrap, schema remains migration-owned, and the production smoke retains its critical invariants.

Canonical documentation: `docs/architecture/FIRST_RUN_SYSTEM.md`.

### 3.8 First-run maturity boundary

**First-class today:** durable auth/bootstrap ownership and production fresh-install proof.

**Not yet a single first-class installation-readiness surface:** provider/model readiness, memory readiness, extension readiness, observability readiness, UI wizard orchestration, and first-real-chat proof are still separate subsystem truths.

That separation is intentional. The next layer should aggregate existing subsystem health/contracts rather than move provider, model, memory, extension, or observability authority into AuthService or a setup route.

Target post-login readiness flow:

```text
auth bootstrap complete
 -> aggregate canonical subsystem health/readiness
 -> provider/model ready or explicitly unavailable
 -> required memory services ready/degraded
 -> governed extensions ready/disabled
 -> observability requirements ready
 -> first real chat through canonical runtime
 -> display actual provider/model/degradation truth
```

### 3.9 First-run configuration debt

`AuthService.create_first_admin()` still directly interprets `KARI_FIRST_RUN_TENANT_SLUG` and `KARI_FIRST_RUN_TENANT_NAME` from the environment.

This violates the configuration rule even though the values are used only inside the canonical bootstrap owner. The fix must move interpretation behind canonical validated configuration without creating a second bootstrap-config service or leaving duplicate environment readers.

This debt is **explicitly open**. Do not describe it as completed until service wiring, tests, docs, and reference audit prove the migration.

### 3.10 Compatibility and tenant debt

Compatibility accessors and default tenant fallbacks must continue to be removed only after caller/reference audits. No new production path may invent tenant scope.

### 3.11 Live maturity classification

| Capability | Live status | Assessment |
|---|---|---|
| Runtime lifecycle authority | ACTIVE | strong |
| CORTEX cognitive decision head | ACTIVE | strong but still converging toward evidence-informed two-stage cognition |
| RuntimePolicy separation | ACTIVE | strong execution-policy authority; evidence-access gate remains target |
| Intelligence signal layer | ACTIVE | hardened, explicit unknown/weak-signal rejection |
| PromptRuntime authority | ACTIVE | final assembly canonical; richer resolved context still evolving |
| Governed memory recall | ACTIVE/PARTIAL | substantial, evidence preservation still converging |
| Governed formation/persistence | ACTIVE/PARTIAL | outcome-aware convergence remains |
| Provider/model authority | ACTIVE | backend-owned, local-first/config-driven direction |
| Distributed Medusa execution control | ACTIVE | fenced ownership/cancellation path landed |
| First-run auth/bootstrap | ACTIVE | canonical, durable, one-time, tenant-scoped |
| First-run production burn | ACTIVE | fresh DB/Redis/migrations/image/restart proof |
| First-run architecture guard | ACTIVE | ownership/invariant test added |
| Unified installation-readiness aggregator | NOT YET | next layer; must consume subsystem truth |
| First-run UI end-to-end burn | NOT YET | next layer |
| First-real-chat fresh-install proof | NOT YET | next layer |
| First-run tenant config purity | PARTIAL | direct env reads remain explicit debt |
| Human-like cognitive continuity | PARTIAL | strong subsystems, incomplete nervous system |

---

## 4. First-Run System Contract

First run is a privileged installation lifecycle. It is not equivalent to “the web server answered” and it is not owned by the UI.

### 4.1 State machine

```text
UNREADY
  config/schema/dependency preflight fails
  -> explicit unavailable/error

BOOTSTRAP_REQUIRED
  auth schema ready + zero durable users
  -> GET /api/auth/first-run = required

BOOTSTRAPPING
  POST /api/auth/first-run/setup
  -> advisory transaction lock
  -> durable re-check
  -> tenant + first owner transaction
  -> audit
  -> normal authentication/session issuance

CONFIGURED
  one or more durable users exist
  -> first-run=false
  -> repeat setup denied
  -> normal login/session flow
```

### 4.2 Security rules

First-run code must preserve:

- fail-closed production/staging config validation;
- migration-owned schema;
- durable tenant assignment;
- backend RBAC role authority;
- race-safe one-time bootstrap;
- auditability;
- canonical password policy;
- canonical token/session issuance;
- no development auth bypass in production proof;
- no client-local fake admin or fake setup completion;
- no secret leakage in readiness diagnostics.

### 4.3 UI rules

The active UI may implement a polished first-run wizard, but it may only render/submit backend truth.

It may:

- request `/api/auth/first-run`;
- collect first-owner identity/password;
- submit `/api/auth/first-run/setup`;
- display backend errors;
- guide authenticated owners through provider/model and deployment readiness.

It must not:

- invent first-run state;
- assign roles client-side;
- create synthetic tenant IDs;
- persist a fake owner locally;
- mark setup complete after persistence failure;
- silently fall back to demo/development credentials;
- own provider/model selection or health truth.

### 4.4 Next first-run tasks

**FIRST-RUN-2: Typed installation readiness**

Objective: add one backend-facing readiness view that aggregates existing subsystem truth without taking ownership from those subsystems.

Do:

- define a typed readiness envelope with component name, required/optional status, ready/degraded/unavailable, reason code, remediation hint, and provenance/source;
- consume canonical provider/model health/inventory;
- consume required memory dependency health;
- consume governed extension readiness;
- consume observability requirements appropriate to environment;
- expose overall `ready_for_chat` separately from `auth_bootstrap_complete`;
- preserve honest degraded/unavailable states;
- emit structured readiness telemetry.

Avoid:

- provider selection in auth/setup code;
- new memory/extension health implementations;
- frontend-only readiness logic;
- fake defaults that mark a component healthy;
- making optional components block minimal local chat unless policy/config says required.

**FIRST-RUN-3: UI wizard**

Objective: active frontend automatically routes fresh installations based on backend status and guides setup without owning truth.

Proof:

- fresh install routes to setup;
- completed install cannot re-enter setup as bootstrap authority;
- backend failure is displayed honestly;
- no local fake save;
- provider/model options come from backend;
- browser refresh/restart preserves backend-completed state.

**FIRST-RUN-4: First real chat burn**

Objective: after bootstrap, prove one real/local enabled provider can answer through canonical `/api/chat` and response metadata identifies actual provider/model/runtime/degradation source.

This proof belongs in an environment where a real model runtime is part of the release contract. Do not replace it with canned text.

---

## 5. Target Cognitive Continuity Model

The target remains a two-stage CORTEX with two RuntimePolicy evaluations owned by the same policy authority:

```text
NEW REQUEST
    |
BootstrapContext
    |
CORTEX Stage 1: what evidence is needed?
    |
ContextRequirements
    |
RuntimePolicy Gate A: what evidence may be accessed?
    |
Runtime EvidenceResolver
    |
CognitiveContext
    |
CORTEX Stage 2: what should happen now?
    |
CognitiveDecision
    |
RuntimePolicy Gate B: what work is allowed?
    |
AuthorizedExecutionPlan
    |
Runtime execution
    |
Outcome
    |
Post-execution formation / consolidation / belief revision
```

CORTEX does not execute. RuntimePolicy does not become cognition. EvidenceResolver cannot expand its own scope. Runtime remains lifecycle owner.

---

## 6. Cognitive and Memory Semantics

Canonical semantic layers:

```text
Observation  = observed event/input
Evidence     = typed, scoped, provenance-bearing support or contradiction
Memory       = stored representation of experience/observation/derived artifact
Claim        = proposition attributed to a source
Belief       = current evidence-weighted proposition held by KAREN
Knowledge    = sufficiently supported belief within explicit confidence/validity bounds
Decision     = cognitive recommendation selected by CORTEX
Action       = authorized execution performed by Runtime
Outcome      = observed result of an action
```

Historical evidence is immutable except for governed retention/deletion. Belief/model state may be revised. Model revision never silently rewrites historical evidence.

Memory layers remain:

```text
STM       recent/session state
Episodic  meaningful interactions, decisions, outcomes, reusable experience
LTM       durable facts, preferences, knowledge
```

NeuroRecall owns retrieval strategy/ranking. MemoryFormation + NeuroVault own durable mutation/lifecycle.

---

## 7. Prompt, Reasoning, Provider, Workflow Boundaries

PromptRuntime owns final prompt assembly. Runtime owns the authorized resolved context supplied to it. CORTEX does not build final prompts.

Reasoning modes are typed execution protocols, not capability strings. Reasoning does not choose providers or persist memory.

Provider/model availability, health, selection, execution, and fallback remain centralized in the canonical model runtime/provider registry.

LangGraph is only for true graph semantics. AgentMedusa is only for authorized multi-agent topology. Neither becomes KAREN's cognitive head or global runtime.

---

## 8. Security and Governance

Preserve authentication/session validation, RBAC, tenant isolation, least privilege, credential redaction, extension/tool permission checks, audit logs, safe exception translation, request/correlation IDs, deletion/retention policy, and fail-closed production behavior.

Never let:

- CORTEX authorize itself;
- evidence retrieval bypass policy where governed;
- EvidenceResolver expand its own scope;
- memory bypass deletion/retention policy;
- raw model output become authoritative belief without provenance;
- UI checks substitute for backend authorization;
- fallback paths bypass policy;
- first-run UI create durable identity outside AuthService;
- first-run bootstrap create production schema at runtime;
- a second bootstrap request create a second “first” owner;
- a user/session proceed without durable tenant scope.

---

## 9. Configuration Authority

Canonical configuration belongs under `src/ai_karen_engine/config/` and validated subsystem adapters.

Remove/migrate scattered direct reads and hardcodes, including:

- direct CORTEX environment feature flags;
- hardcoded runtime/policy environment values;
- hardcoded reasoning/model-call floors that should be configurable;
- duplicated provider/model/fallback settings;
- direct first-run tenant slug/name environment interpretation in AuthService.

Every configuration option needs an owner, default where safe, environment override where appropriate, validation, documentation, telemetry exposure when relevant, and safe failure behavior.

Do not “fix” config debt by creating another config service.

---

## 10. Observability

Trace, when applicable:

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

For installation/bootstrap also distinguish:

```text
first_run_required
auth_schema_ready
bootstrap_attempt
bootstrap_result
bootstrap_reason_code
tenant_created_or_resolved
first_admin_created
reentry_denied
ready_for_chat
readiness_component
readiness_status
```

Do not log passwords, raw tokens, or secrets. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

---

## 11. Composition and No-Hidden-Construction Rule

Stateful canonical services must not silently instantiate alternate provider registries, memory managers, NeuroRecall instances, reasoning engines, prompt runtimes, policy engines, workflow orchestrators, CORTEX instances, auth authorities, or installation orchestrators.

Compatibility shims may remain only when they resolve to canonical composed instances and have explicit migration/removal conditions.

A future installation-readiness aggregator is a view/composition layer. It does not become the owner of the health or configuration it aggregates.

---

## 12. Priority Migration

### COGNITIVE-CONTINUITY-1

1. **CORTEX-CONTEXT-1:** typed ContextRequirements/CognitiveContext and two-stage CORTEX without duplicate orchestration.
2. **EVIDENCE-AUTH-1:** RuntimePolicy Gate A before governed evidence resolution.
3. **EVIDENCE-1:** preserve evidence provenance/confidence/temporal/contradiction/scope semantics end-to-end.
4. **FORMATION-1:** decouple formation from recall and make it post-execution/outcome-aware.
5. **PROMPT-CONTEXT-1:** route resolved CognitiveContext through existing PromptRuntime normalization.
6. **CONFIG-COGNITIVE-1:** migrate direct environment reads and hardcoded cognitive/runtime defaults.
7. **SELF-1 / USER-REL-1:** operationalize evidence-backed self/user/relationship continuity.
8. **BELIEF-1 / METACOGNITION-1 / CONSOLIDATION-1:** complete revision/calibration/consolidation loops.
9. **COGNITIVE-EVAL-1:** benchmark continuity, conflict, temporal updates, abstention, forgetting, and calibration.
10. **COMPAT-CORTEX-1:** remove misleading compatibility accessors after caller migration.

### FIRST-RUN

1. **FIRST-RUN-1:** durable auth/bootstrap authority + production fresh-install burn. **ACTIVE in this hardening slice.**
2. **FIRST-RUN-CONFIG-1:** move tenant slug/name interpretation behind canonical validated config. **OPEN.**
3. **FIRST-RUN-2:** typed post-login installation-readiness aggregator over canonical subsystem truth. **OPEN.**
4. **FIRST-RUN-3:** active frontend first-run wizard/router consuming backend truth. **OPEN.**
5. **FIRST-RUN-4:** fresh-install first-real-chat burn with actual provider/model provenance. **OPEN.**

Do not add a new global orchestrator, setup framework, persona framework, memory framework, policy engine, or agent harness before checking whether existing canonical contracts can be extended.

---

## 13. Repository and Cleanup Rules

Before changing or deleting a service/path:

1. identify the current owner;
2. search imports/references;
3. find stronger existing implementations;
4. classify touched code as active, misplaced, useful-incomplete, compatibility, experimental, dead, or dangerous;
5. merge into the canonical owner;
6. migrate consumers;
7. delete dead authority after reference audit;
8. add architecture tests preventing resurrection.

Broad namespaces are not authorities by name. Ownership is defined by contract and runtime path.

Never keep dead code “just in case.”

---

## 14. Required Proof

Relevant backend changes run the applicable subset:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Frontend:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Infrastructure:

```bash
docker compose config
```

First-run architecture proof:

```bash
pytest tests/architecture/test_first_run_system_contract.py -q
bash -n scripts/ci/production-first-boot-smoke.sh
```

Real production first-run burn:

```bash
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:beta .
KAREN_SMOKE_API_IMAGE=ai-karen-api:beta bash scripts/ci/production-first-boot-smoke.sh
```

First-run merge checklist:

```text
[ ] route delegates durable bootstrap to AuthService
[ ] route does not create Tenant/AuthUser rows directly
[ ] required auth schema is migration-owned
[ ] AuthService initialization fails when required schema is absent
[ ] first-run state comes from durable user count
[ ] bootstrap is serialized across workers
[ ] durable user count is rechecked after lock acquisition
[ ] first owner has durable tenant scope
[ ] first owner has backend admin + user roles
[ ] setup emits audit event
[ ] duplicate/re-entry setup is denied
[ ] production smoke proves exactly one bootstrap user
[ ] completed state survives exact-image restart
[ ] owner can authenticate after restart
[ ] UI does not invent setup state or roles
[ ] provider/model/memory/extension readiness remains owned by canonical subsystems
[ ] direct first-run tenant config environment reads are tracked until migrated
```

Never report CI/tests green unless actually observed on the exact head.

---

## 15. Research-Guided Development Rules

Research informs implementation; it does not gain architecture authority.

Favor mechanisms that fit KAREN-owned contracts: consolidation, interference/retention policy, reconsolidation, temporal knowledge updates, associative/entity links, multi-cue retrieval, evidence-aware memory evolution, metacognitive calibration, and explicit abstention.

Every research-derived capability documents source paper/repository, implemented mechanism, deviations, compute/resource assumptions, benchmark protocol, production activation policy, and fallback/abstention behavior.

---

## 16. Documentation Authority

Read in this order:

1. `PROJECT_DEV_MANIFEST.md`
2. live code and architecture tests
3. `docs/architecture/FIRST_RUN_SYSTEM.md` for first-run/bootstrap work
4. `docs/development/ARCHITECTURE_AUTHORITY.md`
5. accepted ADR/current dev sheet
6. subsystem documentation
7. historical sprint sheets as history only

If documentation disagrees with tested live behavior, classify it explicitly as documentation drift or implementation debt.

---

## 17. Final Architecture Test

Before merging, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Is this signal production, cognitive decision, evidence authorization, evidence resolution, execution authorization, execution, formation, persistence, installation bootstrap, or presentation?
5. Does the change preserve local-first and prompt-first behavior?
6. Does it preserve RBAC, tenant isolation, audit, credentials, retention/deletion, and telemetry?
7. Does CORTEX remain cognitive authority without becoming an executor?
8. Does RuntimePolicy remain authorization-only?
9. Does Runtime remain the sole chat lifecycle/execution authority?
10. Does first-run bootstrap remain inside canonical AuthService + migration/deployment boundaries?
11. Does any subsystem silently construct or mutate an alternate authority?
12. Does evidence retain provenance/confidence/temporal/contradiction/scope semantics across boundaries?
13. Is learning based on actual completed interaction/outcome?
14. Are environment, budgets, flags, providers, fallbacks, and bootstrap settings sourced from canonical config or explicitly tracked as debt?
15. What executable proof demonstrates the boundary?

If those answers are unclear, the design is not finished.

---

## 18. Canonical Mental Model

```text
CORTEX Stage 1    = What evidence does KAREN need?
RuntimePolicy A   = What evidence may KAREN access now?
EvidenceResolver  = Resolve only authorized evidence/context.
CORTEX Stage 2    = Given the evidence, what should KAREN do?
RuntimePolicy B   = What final work is KAREN allowed to perform?
Runtime           = Execute authorized chat work and own request lifecycle.
Intelligence      = Produce typed signals/features/predictions for cognition.
CognitiveState    = Typed cognitive snapshot vocabulary, not an orchestrator.
NeuroRecall       = Which authorized past information is useful now?
MemoryFormation   = Which completed experiences/outcomes are eligible for memory?
NeuroVault        = Govern durable memory mutation and lifecycle.
Reasoning         = Execute typed, authorized reasoning strategies.
LangGraph         = Execute explicit graph semantics only.
AgentMedusa       = Execute governed specialist-agent topology only.
PromptRuntime     = Serialize authorized resolved context into prompt contracts.
ModelRuntime      = Resolve and execute an eligible healthy provider/model.
AuthService       = Own durable users/sessions and one-time first-owner bootstrap.
Migrations        = Own production schema creation/evolution.
First-run API     = Thin transport over AuthService bootstrap truth.
First-run UI      = Render backend setup/readiness truth only.
Observability     = Record what actually happened.
Configuration     = Supply validated environment, flags, budgets, endpoints, and defaults.
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
