# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract and live architecture truth map
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, infrastructure, tests, and documentation
> **Live audit baseline:** `main` at `de9356fcc89ce5d3100de5d7c990fdb5163c0ff6` on 2026-08-27
> **Rule:** Live code is implementation truth. This manifest distinguishes what exists now from the target architecture. Historical sprint sheets and compatibility layers never override it.

AI KAREN is a **local-first, prompt-first, modular AI runtime** evolving toward **human-like cognitive continuity** with durable governed memory, evidence-backed models, provider/model orchestration, governed reasoning, RBAC, audit, extensibility, and first-class observability.

KAREN is not framework-first. Libraries, research systems, and agent harnesses are implementation capabilities. **KAREN-owned contracts remain architectural authority.**

---

## 1. Engineering Mission

Every major responsibility must have one owner, one canonical contract, one runtime path, one registry/config source where applicable, explicit tenant/security boundaries, observable lifecycle events, and tests proving the boundary.

Core rules:

- **Local-first:** prefer healthy local capabilities when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable contracts.
- **Runtime-authoritative:** routes, UI, providers, agents, and plugins never become alternate runtimes.
- **CORTEX is KAREN's central cognitive authority. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **DRY by authority:** one responsibility -> one owner -> one execution path.
- **Typed and async-safe:** public cognitive/runtime boundaries are typed; budgets, cancellation, and concurrency are explicit.
- **Config-driven:** providers, models, endpoints, fallbacks, feature flags, and security modes are centralized.
- **Honest degradation:** unavailable capabilities produce explicit degraded/unavailable results, never fabricated model output.
- **Evidence-preserving cognition:** retrieval evidence must not be flattened into untyped text before reasoning or model revision.
- **Test-proven architecture:** architecture rules are executable where practical.

### 1.1 Cognitive north star

The target is not merely long-term memory. The target is **cognitive continuity**:

```text
experience
 -> interpret
 -> remember
 -> revise beliefs/models
 -> decide
 -> act
 -> observe outcome
 -> learn
 -> consolidate
 -> update future cognition
```

Memory, belief, identity, user understanding, relationship continuity, temporal reasoning, goals, metacognition, selective forgetting, prospective commitments, and outcome learning are separate concerns with explicit contracts.

---

## 2. Canonical Authority Map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP ingress | `api_routes/` + app composition | provider choice, prompts, recall, orchestration |
| Request lifecycle | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive decisions | `core/cortex/` | authorization, provider execution, persistence |
| Signal extraction / ML inference | `core/intelligence/` | final cognitive authority, execution, authorization |
| Cognitive state vocabulary | `core/cognitive/` | orchestration, provider execution, persistence |
| Context vocabulary | `core/context/` | independent cognitive authority |
| Runtime authorization | `core/runtime/policy/` | cognitive classification, provider execution |
| Prompt assembly | `core/runtime/prompt/` | providers, routes, agents, memory retrieval |
| Reasoning execution | `core/reasoning/` | provider routing, durable writes, global orchestration |
| Soft Reasoning | `core/reasoning/soft_reasoning/` | memory retrieval authority, provider routing |
| Memory recall strategy | NeuroRecall under `core/memory/` | durable storage, provider/tool execution |
| Persistence governance | NeuroVault / memory formation path | reasoning engines, recall engines |
| Self/User/Relationship models | `core/personalization/` contracts/services | global execution, policy authorization |
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, global routing |
| Multi-agent execution | AgentMedusa | provider routing, global policy |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Observability | `platform/observability/` | subsystem shadow telemetry |
| Configuration | `src/ai_karen_engine/config/` + environment | React fallbacks, launch scripts |

**CORTEX is the central cognitive authority, not the supreme system authority.** Security/policy, execution, persistence, provider routing, prompt assembly, and observability remain independent authorities in their own domains.

---

## 3. Live Implementation Truth: 2026-08-27

This section records the audited production shape of `main`. It is intentionally different from the target model where wiring is incomplete.

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
      |      |
      |      +--> IntelligenceRuntime.analyze(raw user text)
      |              +--> linguistic analysis when available
      |              +--> semantic encoding
      |              +--> ML predictors
      |              +--> deterministic heuristics/fallbacks
      |      |
      |      +--> requested intent/topology/reasoning/recall/tools/budgets
      |
      +--> RuntimePolicyEnforcer.evaluate
      |      +--> allowed/denied capabilities
      |      +--> allowed/denied reasoning modes
      |      +--> side-effect constraints
      |
      v
ExecutionDecision carrying policy result
      |
      v
ChatRuntime builds AuthorizedExecutionPlan
      |
      +--> memory recall, only if CORTEX requested it
      |
      +--> DIRECT -> PromptRuntime -> ExpressionGateway -> provider/model runtime
      |
      +--> REASONING -> Reasoning bridge/executor
      |
      +--> WORKFLOW / MULTI-AGENT -> WorkflowRuntime
      |
      +--> memory persistence under policy gate, currently coupled to recall
      |
      +--> trajectory / outcome / telemetry
```

### 3.2 What CORTEX actually is today

`CortexExecutionDecider` is active and is the current cognitive decision head. It does not execute providers, tools, memory, graphs, or persistence. It consumes `IntelligenceRuntime` analysis and translates signals into an `ExecutionDecision` containing intent, topology, reasoning modes, memory recall/write requests, tool/plugin requirements, capabilities, risk, human-gate hints, and budgets.

**Current limitation:** CORTEX is **single-pass**. It analyzes the raw request before memory or model context is resolved. The runtime then retrieves memory after the CORTEX + RuntimePolicy decision. There is no second CORTEX decision using the retrieved evidence.

Therefore current KAREN is not yet the target evidence-informed executive loop. It is currently:

```text
raw request
 -> CORTEX
 -> RuntimePolicy
 -> recall
 -> execute
```

not yet:

```text
raw request
 -> CORTEX stage 1: determine evidence requirements
 -> authorized evidence resolution
 -> CognitiveContext
 -> CORTEX stage 2: final cognitive decision
 -> RuntimePolicy
 -> execute
```

### 3.3 What `core/intelligence` actually is

`IntelligenceRuntime` is an active subordinate analysis layer, not a second cognitive head. It currently owns linguistic parsing, semantic encoding, and ML predictors for intent, domain, complexity, ambiguity, memory relevance, capability hints, and execution-topology signals, with heuristic/degraded fallbacks.

This is legitimate **signal production** only if CORTEX remains the sole owner that interprets those signals into cognitive decisions. Any future code in `core/intelligence` that directly selects runtime execution, tools, providers, workflows, or authorization is an authority violation.

### 3.4 What `core/cognitive` and `core/context` actually are

`core/cognitive/state.py` already defines a substantial `CognitiveState` envelope with belief, goals, salience, context, reasoning, metacognition, adaptive, policy, confidence, tenant, user, session, conversation, and project state.

`core/context` currently owns almost no runtime behavior. Its canonical contract aliases `ContextScope` to the cross-domain `CognitiveScope` and re-exports `ContextSnapshot` from cognitive state. There is no active canonical EvidenceResolver/ContextResolver service in this package.

**Critical gap:** canonical `ChatRuntime` does not currently carry `CognitiveState` through the request lifecycle. Rich cognitive state exists as contract vocabulary but is not the central production chat envelope.

### 3.5 Prompt reality

`ChatRuntime._assemble_prompt()` calls canonical PromptRuntime for final assembly, which is correct, but it constructs `PromptAssemblyRequest` directly in `ChatRuntime`.

The direct request currently carries messages, selected memory items, tool contracts, workflow metadata, and token budget. It does not carry a resolved SelfModel, UserModel, RelationshipModel, belief state, commitments, goal state, metacognitive state, or evidence-preserving CognitiveContext.

A stronger `PromptRuntimeService.build_request_from_runtime_context(...)` path already exists and should be reused/extended rather than creating another prompt-context builder.

### 3.6 Memory reality

Memory governance is materially stronger than the final-mile cognitive wiring. Runtime recall calls the canonical memory manager with explicit user, tenant, session/conversation, query, top-k, and correlation context.

However, returned results are currently flattened before use to approximately:

```text
id
content
timestamp
```

This discards memory type/class, salience, confidence, retrieval score components, provenance, temporal validity, contradiction/supersession state, scope, graph/entity/causal links, and retrieval rationale when those fields are available upstream.

The reasoning path then reconstructs `ReasoningEvidence` with fixed `relevance=0.5` and `confidence=0.5` for every recalled item. This erases evidence quality and prevents calibrated reasoning.

**Critical lifecycle defect:** non-stream chat persistence is currently attempted only when `decision.memory_recall_required` is true. A request can therefore produce a novel interaction or valuable outcome that should be learned even when no prior recall was needed. Read need and write/formation need are distinct decisions and must not remain coupled.

### 3.7 Self/User/Relationship reality

Personalization contains rich contracts and services, including evidence/provenance-oriented model vocabulary. Those models are not currently resolved into the canonical `ChatRuntime` decision/prompt path before generation.

Until that wiring exists, KAREN has model contracts but not full operational self/user/relationship continuity in ordinary chat.

### 3.8 Compatibility and naming debt

`RuntimeComposition.cortex` currently returns the **Runtime-owned `RuntimeDecisionPipeline`**, not the underlying `CortexExecutionDecider`. This preserves legacy `ChatRuntime._decide()` behavior but blurs the meaning of `cortex` at the call site.

The alias is a compatibility shim. The target is explicit runtime stages:

```text
cognitive_decision = cortex.decide(...)
authorization = runtime_policy.evaluate(...)
plan = runtime.build_authorized_plan(...)
```

Do not add new code that depends on the compatibility alias.

### 3.9 Tenant contract risk

`ChatExecutionContext` still defines `tenant_id="default"` as a dataclass default. Production architecture requires explicit tenant scope. Ingress may currently supply a concrete tenant, but the canonical runtime contract itself still permits an implicit default and must be tightened with compatibility impact audited first.

### 3.10 Live maturity classification

| Capability | Live status | Assessment |
|---|---|---|
| Runtime lifecycle authority | ACTIVE | strong |
| CORTEX cognitive decision head | ACTIVE | strong but single-pass |
| RuntimePolicy separation | ACTIVE | strong |
| Intelligence signal layer | ACTIVE | useful subordinate capability |
| Typed CognitiveState | CONTRACT-ONLY / PARTIALLY USED | rich schema, not canonical chat envelope |
| Context resolver | UNWIRED | vocabulary exists, resolver does not |
| PromptRuntime authority | ACTIVE | final assembly canonical, input normalization bypassed |
| Governed memory recall | ACTIVE | final-mile semantics flattened |
| Governed memory formation/persistence | ACTIVE/PARTIAL | write path coupled to recall in ChatRuntime |
| SelfModel in ordinary chat | CONTRACT/PARTIAL | not resolved into canonical execution context |
| UserModel in ordinary chat | PARTIAL | not central to canonical execution context |
| RelationshipModel in ordinary chat | CONTRACT/PARTIAL | not resolved into canonical execution context |
| Belief revision | PARTIAL/UNWIRED | state vocabulary exists; no canonical request-loop authority proven |
| Metacognition | CONTRACT/REASONING MODE | not persistent calibrated metamemory |
| Evidence-preserving recall -> reasoning | RED | fixed 0.5 relevance/confidence destroys signal |
| Two-stage evidence-informed CORTEX | RED | not implemented |
| Cognitive consolidation loop | PARTIAL | memory systems exist; full model-update loop not canonical |
| Human-like cognitive continuity | PARTIAL | architecture foundation exists, continuity highway does not |

---

## 4. Target Cognitive Continuity Model

The canonical target is a **two-stage CORTEX**. Stage 1 determines what evidence is needed. Runtime resolves only authorized evidence. Stage 2 makes the final cognitive decision using a typed CognitiveContext. RuntimePolicy then authorizes execution.

```text
                         EXPERIENCE
                             |
                +------------+------------+
                |                         |
                v                         v
         Memory Formation          Outcome / Learning
                |                         |
                +------------+------------+
                             v
                       Consolidation
                             |
                      Belief Revision
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
      Self Model         User Model      Relationship Model
          ^                  ^                  ^
          |                  |                  |
          +----------- Evidence / Claims -------+
                             ^
                             |
                       Memory Graph
             episodic / semantic / temporal /
                       associative
                             |
                             v
                        NEW REQUEST
                             |
                             v
                      BootstrapContext
                             |
                             v
                    CORTEX STAGE ONE
                  "what evidence is needed?"
                             |
                             v
                    ContextRequirements
                             |
                             v
                  Runtime EvidenceResolver
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
       Memory             Models            Live State
          |                  |                  |
          +------------------+------------------+
                             v
                     CognitiveContext
                             |
                             v
                    CORTEX STAGE TWO
                    "what should happen?"
                             |
                             v
                     CognitiveDecision
                             |
                             v
                       RuntimePolicy
              RBAC / tenant / safety / budget /
                   capability authorization
                             |
                             v
                  AuthorizedExecutionPlan
                             |
                             v
                          Runtime
              +--------------+--------------+
              |              |              |
              v              v              v
          Reasoning        Tools         Workflow
              |              |              |
              +--------------+--------------+
                             v
                       PromptRuntime
                             |
                             v
                        Expression
                             |
                             v
                     Provider Router
                             |
                             v
                            LLM
                             |
                             v
                          Outcome
                             |
                             +-------> learning loop
```

### 4.1 Stage boundaries

**CORTEX Stage 1 owns:** intent hypothesis, uncertainty estimate, context/evidence requirements, temporal horizon, memory classes/scopes, model facets needed, retrieval budget hints, and verification need.

**Runtime EvidenceResolver owns:** executing only authorized retrieval/resolution against memory, SelfModel, UserModel, RelationshipModel, goals, commitments, current state, and external/live state. It does not decide the final action.

**CORTEX Stage 2 owns:** final intent/goal interpretation, cognitive topology, reasoning modes, recall sufficiency, evidence conflicts, abstention/clarification/escalation recommendations, tool/workflow desirability, and requested compute budget.

**RuntimePolicy owns:** whether requested capabilities, side effects, tools, reasoning modes, resources, and human gates are allowed.

**Runtime owns:** execution, retries/fallbacks, provider/model invocation, streaming, persistence coordination, telemetry, and audit.

---

## 5. Cognitive Semantics

Do not collapse all remembered information into "memory" or all model state into "context".

Canonical semantic layers:

```text
Observation  = an observed event or input
Memory       = stored representation of an observation/experience/derived artifact
Claim        = proposition attributed to a source
Belief       = current evidence-weighted proposition held by KAREN
Knowledge    = sufficiently supported belief within explicit confidence/validity bounds
Decision     = cognitive recommendation selected by CORTEX
Action       = authorized execution performed by Runtime
Outcome      = observed result of an action
```

Historical memory is immutable evidence except for governed retention/deletion. Belief/model state may be revised. **Model revision must never silently rewrite historical evidence.**

### 5.1 Belief revision

Conflicting evidence must flow through a canonical revision policy:

```text
new evidence
 -> conflict detection
 -> temporal resolution
 -> provenance/source weighting
 -> confidence/calibration update
 -> supersession/dispute/abstention decision
 -> model revision
```

Simple newest-wins replacement is not sufficient for durable cognitive continuity.

### 5.2 Identity and self separation

Do not overload persona:

```text
IdentityBaseline = designed identity, principles, immutable product constraints
SelfBelief       = evidence-backed beliefs about KAREN's capabilities/history
SelfState        = temporary operational/session capability state
PersonaProfile   = optional communication/behavior overlay
```

Natural-language self-assessment from an LLM may propose evidence but must not directly mutate SelfBelief. Self updates require governed evidence such as tests, tool availability, runtime health, verified outcomes, benchmarks, observed failures, user corrections, or verified artifacts.

---

## 6. Memory Architecture

Memory follows a governed **write -> manage -> read** lifecycle.

```text
STM       recent/session state
Episodic  meaningful interactions, decisions, outcomes, reusable experience
LTM       durable facts, preferences, knowledge
```

NeuroRecall owns candidate-source coordination, semantic/temporal/graph/case fusion, ranking/reranking, contradiction/redundancy/diversity handling, scope-aware selection, recall abstention, recall confidence, and future learned selection policy behind evaluation gates.

NeuroVault and the canonical memory formation path own durable mutation. Recall engines do not persist. Reasoning engines do not directly persist. Runtime coordinates authorized formation.

**Read and write are independent:** `memory_recall_required` must not imply or gate `memory_write_requested`, and lack of recall must never prevent a separately authorized learning/formation event.

Production memory contracts preserve explicit tenant, user/workspace/project, session/conversation where applicable, namespace/class, provenance, lifecycle state, policy/schema version, temporal validity, and timestamps.

No implicit production `tenant_id="default"` fallback is permitted.

---

## 7. Prompt-First Rules

Canonical prompt assembly accounts for system policy, task/output contract, explicit turn override, identity/persona/profile, tenant context, authorized memory evidence, Self/User/Relationship model slices, goals/commitments where relevant, CORTEX intent/reasoning requirements, authorized tools/extensions, provider capability, token budget, safety, and output schema.

PromptRuntime owns prompt assembly. Runtime owns the resolved input context supplied to PromptRuntime. CORTEX does not construct final prompts.

Do not create another prompt-context builder while `PromptRuntimeService.build_request_from_runtime_context(...)` can be extended as the stronger existing normalization path.

---

## 8. Reasoning Architecture

Reasoning modes are typed execution protocols, not generic capability strings. Canonical modes include:

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

Soft Reasoning remains a specialist research-derived strategy under Runtime-authorized execution. It does not choose providers, build canonical prompts, own memory retrieval, or persist memory. It must report compute cost and fail closed when required runtime capabilities are unavailable.

Evidence entering reasoning must preserve upstream retrieval/provenance confidence. Fixed synthetic defaults such as `relevance=0.5` and `confidence=0.5` are transitional defects and must not become permanent semantics.

---

## 9. Provider, Workflow, and Agent Boundaries

Provider/model availability, selection, health, execution, and fallback remain centralized under the canonical model runtime/provider registry. CORTEX may request capabilities or locality constraints but does not select/execute a provider outside the canonical router.

Target local-first fallback order remains config-driven:

```text
requested provider/model
 -> local primary
 -> OpenAI-compatible local endpoint, including vLLM deployments
 -> Transformers when enabled
 -> Ollama when enabled/healthy
 -> explicitly enabled external provider
 -> honest unavailable/degraded result
```

`builtin_vllm` must not be resurrected.

LangGraph is only for true graph semantics: branching, checkpoint/resume, dependency chains, human approval nodes, and explicit long-running stateful workflows. Complexity alone does not imply LangGraph.

AgentMedusa is only for authorized multi-agent topology requiring specialist coordination, dependencies, concurrency, or arbitration. Neither LangGraph nor AgentMedusa is KAREN's cognitive head.

---

## 10. Security and Governance

Preserve authentication/session validation, RBAC, tenant isolation, least privilege, credential redaction, extension/tool permission checks, audit logs, safe exception translation, request/correlation IDs, and production fail-closed behavior.

Never let CORTEX authorize itself, let context retrieval bypass tenant/policy scope, let memory bypass deletion/retention policy, persist raw untrusted model output as authoritative belief without provenance, rely on UI checks for authorization, or introduce policy-bypassing fallbacks.

RuntimePolicy must remain independently testable from CORTEX.

---

## 11. Observability

Canonical structured metadata includes, when applicable:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
cortex_stage
intent
topology
context_requirements
context_sources
context_item_count
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
belief_conflicts
model_revisions
model_calls
reasoning_steps
latency_ms
status
error_type
error_code
```

Use one observability authority under `platform/observability/`. High-cardinality IDs belong in structured events/traces, not Prometheus labels.

The two-stage CORTEX migration must make Stage 1, evidence resolution, Stage 2, policy authorization, execution, formation, and consolidation separately traceable.

---

## 12. Composition and No-Hidden-Construction Rule

Stateful canonical services are composed at the application/runtime boundary. Today the live composition is:

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

Target composition must make the two cognitive stages explicit without turning CORTEX into an executor:

```text
CortexExecutionDecider
       +
EvidenceResolver
       +
RuntimePolicyEnforcer
       |
       v
Runtime cognitive decision lifecycle
       |
       v
ChatRuntime execution
```

Do not create a second global orchestrator merely to implement two-stage cognition. Runtime remains the lifecycle owner.

Subsystems must not silently instantiate alternate provider registries, memory managers, NeuroRecall instances, reasoning engines, prompt runtimes, policy engines, workflow orchestrators, or CORTEX instances.

Compatibility accessors may remain temporarily only when they resolve to canonical composed instances and have explicit removal conditions.

---

## 13. Priority Migration: COGNITIVE-CONTINUITY-1

The next canonical migration order is:

1. **CORTEX-CONTEXT-1:** introduce typed `ContextRequirements` and `CognitiveContext`; split CORTEX into preliminary evidence-needs and final decision stages without duplicating runtime orchestration.
2. **EVIDENCE-1:** preserve typed memory provenance, temporal state, relevance, confidence, contradictions, scope, and retrieval rationale through ChatRuntime and ReasoningEvidence.
3. **FORMATION-1:** decouple memory formation/write eligibility from recall eligibility; outcome and learning capture execute independently under policy.
4. **PROMPT-CONTEXT-1:** route canonical resolved cognitive context through existing PromptRuntime normalization instead of direct minimal `PromptAssemblyRequest` construction.
5. **SELF-1:** operationalize evidence-backed SelfModel/SelfBelief and temporary SelfState; never let LLM self-description mutate durable self state directly.
6. **USER-REL-1:** resolve UserModel, RelationshipModel, goals, preferences, and commitments into scoped CognitiveContext.
7. **BELIEF-1:** establish canonical claim/evidence/belief revision with temporal conflict and supersession semantics.
8. **METACOGNITION-1:** add calibrated knowledge-gap, memory reliability, evidence sufficiency, retrieval-needed, abstention, and capability-awareness behavior.
9. **CONSOLIDATION-1:** connect outcomes to consolidation, semantic extraction, model revision, selective forgetting/retention, and reconsolidation policy.
10. **COGNITIVE-EVAL-1:** benchmark multi-session recall, temporal reasoning, knowledge updates, contradiction handling, abstention, long-range understanding, selective forgetting, and self-capability calibration.

Do not add a new persona framework, context orchestrator, memory framework, or agent harness before checking whether the existing contracts/services can be extended behind these owners.

---

## 14. Repository and Cleanup Rules

Before creating or changing a service: identify the current owner, search imports/references, find stronger existing implementations, classify touched code as active/misplaced/useful-incomplete/compatibility/experimental/dead/dangerous, merge into the canonical owner, migrate consumers, delete dead authority after reference audit, and add architecture tests preventing resurrection.

Broad namespaces are not authorities by name. In particular:

- `core/cortex` = decisions;
- `core/intelligence` = signals/features/predictions consumed by CORTEX;
- `core/cognitive` = typed cognitive state/vocabulary unless a future ADR assigns a specific subordinate service;
- `core/context` = context vocabulary/resolution primitives, never a competing cognitive executive;
- `core/reasoning` = authorized reasoning execution;
- `core/adaptive` = learning/adaptation capability, never global request routing;
- `core/runtime` = lifecycle/execution authority.

Any module violating those definitions must be moved/merged or explicitly documented as transitional compatibility.

Never keep dead code "just in case."

---

## 15. Required Proof

Relevant changes run the applicable subset:

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

Cognitive/runtime changes additionally prove:

```text
[ ] CORTEX has no RuntimePolicy construction/execution
[ ] CORTEX has no provider/tool/memory/persistence execution
[ ] Stage 1 emits typed context requirements
[ ] EvidenceResolver cannot self-authorize retrieval scope
[ ] Stage 2 receives typed CognitiveContext
[ ] RuntimePolicy runs after final CORTEX decision
[ ] RuntimePolicy owns allowed/denied reasoning modes and capabilities
[ ] RuntimePolicy never invents a reasoning mode
[ ] Runtime remains the sole lifecycle/execution authority
[ ] IntelligenceRuntime remains signal-producing, not final cognitive authority
[ ] capability and reasoning-mode domains remain distinct
[ ] rich recall evidence survives into reasoning/prompt context
[ ] no fixed fake confidence/relevance replaces real evidence metadata
[ ] memory formation is not gated by whether recall occurred
[ ] Self/User/Relationship model slices are tenant/user scoped
[ ] durable writes remain governed by MemoryFormation / NeuroVault
[ ] tenant/scope is explicit for production memory and runtime contracts
[ ] shared stateful dependencies are explicitly composed
[ ] compatibility `composition.cortex` alias has no new consumers
```

Never report CI/tests green unless actually observed.

---

## 16. Research-Guided Development Rules

Research informs implementation; it does not gain architecture authority.

For human-like continuity, favor mechanisms that can be expressed through KAREN-owned contracts: consolidation, interference/retention policy, reconsolidation, temporal knowledge updates, associative/entity links, multi-cue retrieval, evidence-aware memory evolution, metacognitive calibration, and explicit abstention.

Every research-derived capability must document source paper/repository, mechanism implemented, deviations, compute/resource assumptions, benchmark protocol, production activation policy, and fallback/abstention behavior.

Do not import a research system's entire orchestration model when its useful mechanism can be extracted behind KAREN's Runtime/CORTEX/Memory/Reasoning contracts.

---

## 17. Documentation Authority

Read in this order:

1. `PROJECT_DEV_MANIFEST.md`
2. live code and architecture tests for implementation truth
3. `docs/development/ARCHITECTURE_AUTHORITY.md`
4. accepted ADR/current dev sheet for the subsystem
5. subsystem documentation
6. historical sprint sheets only as history

Supporting docs include:

- `docs/development/ARCHITECTURE_AUTHORITY.md`
- `docs/development/ARCH_AUTH_02.md`
- `docs/development/CORTEX_RUNTIME.md`
- `docs/development/MEMORY.md`
- `docs/development/REASONING_LANGGRAPH_MEDUSA.md`
- `docs/development/EXTENSIONS_TOOLS.md`
- `docs/development/SECURITY_OBSERVABILITY.md`
- `docs/development/REPOSITORY_ENGINEERING.md`

If documentation disagrees with tested live behavior, classify the difference explicitly as **documentation drift** or **implementation debt**. Never silently reinterpret one as the other.

---

## 18. Final Architecture Test

Before merging, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Is this signal production, cognitive decision, authorization, execution, persistence, or presentation?
5. Does the change preserve local-first and prompt-first behavior?
6. Does it preserve RBAC, tenant isolation, audit, credentials, and telemetry?
7. Does CORTEX remain the central cognitive authority without becoming an executor?
8. Does RuntimePolicy remain authorization-only?
9. Does Runtime remain the sole lifecycle/execution authority?
10. Does any subsystem silently construct or mutate an alternate authority?
11. Does evidence retain provenance, confidence, temporal state, and contradiction semantics across boundaries?
12. Can a learning event be formed independently of whether recall happened?
13. What executable proof demonstrates the boundary?

If those answers are unclear, the design is not finished.

---

## 19. Canonical Mental Model

```text
CORTEX            = What evidence is needed, and what does KAREN think should happen?
Intelligence      = Produce typed signals/features/predictions for cognition.
CognitiveState    = Typed snapshot vocabulary, not an orchestrator.
EvidenceResolver  = Resolve authorized evidence/context requested by CORTEX.
RuntimePolicy     = What is KAREN allowed to do now?
Runtime           = Execute the authorized work safely and own the request lifecycle.
NeuroRecall       = Which authorized past information is useful now?
RecallPrimitives  = Retrieve and locally score memory candidates.
MemoryFormation   = Decide what experience/outcome is eligible to become memory.
NeuroVault        = Govern durable memory mutation and lifecycle.
SelfModel         = Evidence-backed model of KAREN, not persona text.
UserModel         = Evidence-backed model of the user within scope.
RelationshipModel = Evidence-backed shared history/norms/commitments within scope.
BeliefRevision    = Reconcile new evidence with current beliefs without rewriting history.
Reasoning         = Execute typed, authorized reasoning strategies.
SoftReasoning     = Governed specialist test-time exploration protocol.
LangGraph         = Execute explicit graph semantics only.
AgentMedusa       = Execute governed specialist-agent topology only.
PromptRuntime     = Serialize authorized resolved context into prompt contracts.
Expression        = Request model generation through canonical runtime boundaries.
ModelRuntime      = Resolve and execute an eligible healthy provider/model.
Observability     = Record what actually happened.
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
