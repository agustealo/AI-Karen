# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, infrastructure, tests, and documentation
> **Rule:** Live code must converge toward this authority model. Historical sprint sheets and compatibility layers never override it.

AI KAREN is a **local-first, prompt-first, modular AI runtime** with durable memory, provider/model orchestration, governed reasoning, RBAC, audit, extensibility, and first-class observability.

KAREN is not framework-first. Libraries, research systems, and agent harnesses are implementation capabilities. **KAREN-owned contracts remain architectural authority.**

---

## 1. Engineering Mission

Every major responsibility must have:

1. one owner;
2. one canonical contract;
3. one runtime path;
4. one registry/config source where applicable;
5. explicit tenant/security boundaries;
6. observable lifecycle events;
7. tests proving the boundary.

Core rules:

- **Local-first**: prefer healthy local capabilities when suitable.
- **Prompt-first**: prompts are explicit, versioned, testable contracts.
- **Runtime-authoritative**: routes, UI, providers, agents, and plugins never become alternate runtimes.
- **CORTEX is KAREN's cognitive head. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **DRY by authority**: one responsibility -> one owner -> one execution path.
- **Typed and async-safe**: public cognitive/runtime boundaries are typed; budgets, cancellation, and concurrency are explicit.
- **Config-driven**: providers, models, endpoints, fallbacks, feature flags, and security modes are centralized.
- **Honest degradation**: unavailable capabilities produce explicit degraded/unavailable results, never fabricated model output.
- **Test-proven architecture**: architecture rules are executable where practical.

---

## 2. Canonical Authority Map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP ingress | `api_routes/` + app composition | provider choice, prompts, recall, orchestration |
| Request lifecycle | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive decisions | `core/cortex/` | authorization, provider execution, persistence |
| Runtime authorization | `core/runtime/policy/` | cognitive classification, provider execution |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents, memory retrieval |
| Reasoning execution | `core/reasoning/` | provider routing, durable writes, global orchestration |
| Soft Reasoning | `core/reasoning/soft_reasoning/` | memory retrieval authority, provider routing |
| Memory recall strategy | NeuroRecall under `core/memory/` | durable storage, provider/tool execution |
| Recall primitives | canonical memory retrievers/scorers | global cognitive policy, durable persistence |
| Persistence governance | NeuroVault / memory formation path | reasoning engines, recall engines |
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, global routing |
| Multi-agent execution | AgentMedusa | provider routing, global policy |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Observability | `platform/observability/` | subsystem shadow telemetry |
| Configuration | `src/ai_karen_engine/config/` + environment | React fallbacks, launch scripts |

---

## 3. Canonical Decision and Execution Chain

```text
Transport / API
      |
      v
ChatRuntime
request lifecycle owner
      |
      v
CORTEX
cognitive desirability only
      |
      v
Cortex Decision
requested topology / reasoning / recall / capabilities / budgets
      |
      v
RuntimePolicy
authorization authority
      |
      v
Authorized Execution Plan
      |
      v
ChatRuntime
      |
      +--> NeuroRecall
      +--> PromptRuntime
      +--> Reasoning
      +--> Direct model execution
      +--> LangGraph when graph semantics are required
      +--> AgentMedusa when multi-agent topology is authorized
      +--> governed tools/extensions
      +--> MemoryFormation / NeuroVault
      +--> audit / telemetry
```

Runtime legitimately appears before and after CORTEX because it owns the request lifecycle. CORTEX never executes the capabilities it selects.

### 3.1 CORTEX owns

- intent/domain interpretation;
- task/goal interpretation;
- cognitive risk signals;
- requested capabilities;
- reasoning depth and requested reasoning modes;
- recall need, class, scope, and budget hints;
- tool/agent/workflow desirability;
- topology recommendations;
- abstention, clarification, escalation, and verification hints;
- requested compute budgets.

CORTEX must not:

- instantiate or invoke `RuntimePolicyEnforcer`;
- call providers/models;
- construct final prompts;
- execute tools/plugins;
- persist memory;
- run LangGraph/AgentMedusa work;
- authorize its own requested capabilities or reasoning modes.

### 3.2 RuntimePolicy owns

- capability authorization;
- reasoning-mode authorization;
- side-effect authorization;
- risk/runtime-level restrictions;
- provider/resource constraints;
- human-gate requirements;
- allowed/denied reasoning modes with reason codes;
- conversion of policy truth into the authorization portion of `AuthorizedExecutionPlan`.

Policy may deny an expensive reasoning protocol without denying the entire request. Runtime must prefer an already-authorized cheaper path when one exists rather than inventing a reasoning mode.

### 3.3 Runtime owns

- request lifecycle;
- context assembly;
- calling CORTEX then RuntimePolicy as distinct stages;
- capability composition;
- prompt assembly coordination;
- execution selection;
- provider/model execution;
- streaming/fallback/degradation;
- persistence coordination;
- telemetry/audit;
- budget accounting.

---

## 4. Reasoning Architecture

Reasoning modes are typed execution protocols, not generic capability strings.

Canonical modes include:

```text
causal
counterfactual
evidence_synthesis
hypothesis_comparison
verification
refinement
soft_exploration
metacognition
```

Capabilities such as `memory.read`, `memory.write`, `web`, `code_execution`, or `filesystem_read` must never leak into the reasoning-mode field.

### 4.1 Soft Reasoning

**Soft Reasoning is reserved exclusively for the research-derived reasoning strategy**, not retrieval.

KAREN's strict Soft Reasoning profile implements a test-time inference protocol based on first-token embedding intervention, candidate exploration, verifier feedback, Gaussian-process Bayesian optimization, and explicit compute accounting.

Soft Reasoning:

- is a specialist reasoning strategy under Runtime-authorized execution;
- requires an already-selected compatible model runtime;
- does not choose providers;
- does not build canonical prompts itself;
- does not own memory retrieval;
- does not persist memory;
- must report generation/verifier/model-call cost separately;
- must fail closed when required embedding/log-probability capabilities are unavailable.

The research profile and KAREN production-tuned profile must remain distinguishable in telemetry and benchmarks.

### 4.2 Adaptive test-time compute

Do not treat all reasoning as one scalar "deep" budget.

KAREN should distinguish inference protocols and allocate compute based on expected value, task difficulty, uncertainty, verification value, risk, and available budget. `soft_exploration` is high-cost and must never become a default for all difficult prompts.

---

## 5. Memory Architecture

Memory follows a governed **write -> manage -> read** lifecycle.

```text
STM       recent/session state
Episodic  meaningful interactions, decisions, outcomes, reusable experience
LTM       durable facts, preferences, knowledge
```

### NeuroRecall

NeuroRecall owns memory-access strategy:

- candidate-source coordination;
- semantic/temporal/graph/case fusion;
- ranking/reranking;
- contradiction/redundancy/diversity handling;
- scope-aware selection;
- recall abstention;
- recall confidence;
- future learned case-selection policy behind explicit evaluation gates.

NeuroRecall must not own persistence, provider execution, prompt assembly, tools, or global policy.

### Recall primitives

Use the term **recall primitives** for embeddings, semantic similarity, retrieval-gap/novelty scoring, recency, local reranking, graph candidate generation, and source-specific retrieval.

Do not call `1 - top_similarity` entropy. Use `novelty_score`, `retrieval_gap`, or another explicitly defined term.

### NeuroVault / durable mutation

Durable memory mutation must flow through governed memory formation and NeuroVault-compatible persistence contracts.

```text
interaction / reasoning / outcome
        |
        v
MemoryCandidate / LearningObservation
        |
        v
MemoryFormation / policy
        |
        v
NeuroVault
        |
        v
canonical durable adapters
```

Every production memory contract must preserve tenant, user/workspace/project, session/conversation where applicable, namespace/class, provenance, lifecycle state, policy/schema version, and timestamps.

No implicit production `tenant_id="default"` fallback is permitted.

Current durable architecture is PostgreSQL/Supabase-backed where configured; Redis is bounded/ephemeral. Milvus and Elasticsearch are not current KAREN memory authorities.

---

## 6. Prompt-First Rules

Canonical prompt assembly accounts for:

1. system policy;
2. task/output contract;
3. explicit turn override;
4. user preference / assistant profile;
5. tenant context;
6. authorized memory context;
7. intent/reasoning requirements;
8. authorized tools/extensions;
9. provider capability;
10. token budget;
11. safety/output schema.

Do not scatter canonical prompt construction through routes, providers, agents, memory retrievers, or reasoning strategies.

---

## 7. Provider and Model Runtime

Provider/model availability, selection, execution, health, and fallback are centralized.

Target local-first order is config-driven:

```text
requested provider/model
 -> local primary
 -> OpenAI-compatible local endpoint, including vLLM deployments
 -> Transformers when enabled
 -> Ollama when enabled/healthy
 -> explicitly enabled external provider
 -> honest unavailable/degraded result
```

Forbidden:

- `builtin_vllm` resurrection;
- route-level provider selection;
- CORTEX provider execution;
- UI-maintained model truth;
- provider-specific prompt authority;
- canned text represented as model output;
- duplicated fallback orders.

---

## 8. Workflow and Multi-Agent Rules

Complexity does **not** imply workflow semantics.

LangGraph is used only for actual graph requirements such as:

- branching;
- checkpoint/resume;
- dependency chains;
- human approval nodes;
- explicit long-running stateful workflows.

A difficult conceptual question may need deep reasoning and still remain a non-graph execution.

AgentMedusa is used only for an authorized multi-agent topology requiring specialist coordination, dependencies, concurrency, or arbitration.

Neither LangGraph nor AgentMedusa may become KAREN's global router or cognitive head.

---

## 9. Security and Governance

Preserve:

- authentication/session validation;
- RBAC;
- tenant isolation;
- least privilege;
- credential redaction;
- extension/tool permission checks;
- audit logs;
- safe exception translation;
- request/correlation IDs;
- production fail-closed behavior.

Never:

- rely on UI checks for authorization;
- execute extensions/actions without governed permission checks;
- allow memory to bypass current policy;
- persist raw untrusted output as authoritative memory without provenance/validation;
- let CORTEX authorize its own requested action;
- introduce policy-bypassing fallback paths.

---

## 10. Observability

Canonical structured metadata includes, when applicable:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
intent
topology
requested_reasoning_modes
allowed_reasoning_modes
denied_reasoning_modes
reasoning_policy_reason
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
model_calls
reasoning_steps
latency_ms
status
error_type
error_code
```

Use one observability authority under `platform/observability/`. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

---

## 11. Composition and No-Hidden-Construction Rule

Stateful canonical services are composed at the application/runtime boundary.

The runtime composition must make the cognitive-policy sequence explicit:

```text
CortexExecutionDecider
       +
RuntimePolicyEnforcer
       |
       v
RuntimeDecisionPipeline
       |
       v
ChatRuntime
```

Subsystems must not silently instantiate alternate provider registries, memory managers, NeuroRecall instances, reasoning engines, prompt runtimes, policy engines, or workflow orchestrators.

Compatibility accessors may remain temporarily only when they resolve to the canonical composed instance and have an explicit removal condition.

---

## 12. Repository and Cleanup Rules

Before creating or changing a service:

1. identify the current owner;
2. search imports/references;
3. determine whether a stronger implementation exists;
4. classify touched code as active, misplaced, compatibility, experimental, dead, or dangerous;
5. merge into the canonical owner;
6. migrate consumers;
7. delete dead authority after reference audit;
8. add architecture tests preventing resurrection.

Never keep dead code "just in case."

Imported research/demo harnesses that own their own providers, planners, tools, memory, or runtimes remain experimental until useful capabilities are extracted behind KAREN contracts.

---

## 13. Required Proof

Relevant changes must run the applicable subset:

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

Architecture/cognitive changes additionally prove:

```text
[ ] CORTEX has no RuntimePolicy construction/execution
[ ] Runtime invokes CORTEX then RuntimePolicy in that order
[ ] RuntimePolicy owns allowed/denied reasoning modes
[ ] RuntimePolicy never invents a reasoning mode
[ ] Runtime remains the request/execution authority
[ ] capability and reasoning-mode domains remain distinct
[ ] Soft Reasoning does not choose providers or own memory retrieval
[ ] NeuroRecall has no provider/tool/workflow execution
[ ] durable writes remain governed by memory formation / NeuroVault
[ ] tenant/scope is explicit for production memory
[ ] novelty/retrieval gap is not mislabeled entropy
[ ] shared stateful dependencies are explicitly composed
```

Never report CI/tests green unless actually observed.

---

## 14. Research-Guided Development Rules

Research informs implementation; it does not gain architecture authority.

Current research guidance relevant to KAREN:

- test-time scaling protocols must be identified and budgeted by protocol, not hidden behind a generic reasoning-depth flag;
- adaptive compute allocation should learn or estimate when extra reasoning is worth its cost instead of uniformly scaling every request;
- verification and candidate-selection quality matter as much as raw generation count;
- memory should be treated as a governed write/manage/read lifecycle with explicit temporal scope, contradiction handling, privacy, retention, and recall policy;
- future learned memory selection should be evaluated against deterministic NeuroRecall baselines before becoming production authority.

Every research-derived capability must document:

1. source paper/repository;
2. mechanism implemented;
3. deviations from the paper;
4. compute/resource assumptions;
5. benchmark protocol;
6. production activation policy;
7. fallback/abstention behavior.

---

## 15. Documentation Authority

Read in this order:

1. `PROJECT_DEV_MANIFEST.md`
2. `docs/development/ARCHITECTURE_AUTHORITY.md`
3. accepted ADR/current dev sheet for the subsystem
4. subsystem documentation
5. live code and architecture tests
6. historical sprint sheets only as history

Current supporting docs include:

- `docs/development/ARCHITECTURE_AUTHORITY.md`
- `docs/development/ARCH_AUTH_02.md`
- `docs/development/CORTEX_RUNTIME.md`
- `docs/development/MEMORY.md`
- `docs/development/REASONING_LANGGRAPH_MEDUSA.md`
- `docs/development/EXTENSIONS_TOOLS.md`
- `docs/development/SECURITY_OBSERVABILITY.md`
- `docs/development/REPOSITORY_ENGINEERING.md`

---

## 16. Final Architecture Test

Before merging, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Does the change preserve local-first and prompt-first behavior?
5. Does it preserve RBAC, tenant isolation, audit, credentials, and telemetry?
6. Does CORTEX remain cognitive-only?
7. Does RuntimePolicy remain authorization-only?
8. Does Runtime remain the sole lifecycle/execution authority?
9. Does any subsystem silently construct or mutate an alternate authority?
10. What executable proof demonstrates the boundary?

If those answers are unclear, the design is not finished.

---

## 17. Canonical Mental Model

```text
CORTEX         = What does KAREN think should happen?
RuntimePolicy  = What is KAREN allowed to do now?
Runtime        = Execute the authorized work safely.
NeuroRecall    = Which authorized past information is useful now?
RecallPrimitives = Retrieve and locally score memory candidates.
SoftReasoning  = Explore solution space with a governed test-time reasoning protocol.
Reasoning      = Execute typed reasoning strategies.
LangGraph      = Execute explicit graph semantics.
AgentMedusa    = Execute governed specialist-agent topology.
ModelRuntime   = Resolve and execute an eligible healthy provider/model.
NeuroVault     = Govern durable memory mutation and lifecycle.
Observability  = Record what actually happened.
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
