# AI KAREN Project Developer Manifest

> **Status:** Canonical developer contract and live architecture truth map
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, infrastructure, tests, and documentation
> **Live audit baseline:** `main` at `5883bc4e25983ce283f0a5a38d42932df87d351d` on 2026-08-27
> **Rule:** Live code is implementation truth. This manifest separates what is implemented now from the target architecture. Historical sprint sheets, compatibility layers, framework conventions, and research systems never override it.

AI KAREN is a **local-first, prompt-first, modular AI runtime** evolving toward **human-like cognitive continuity** with durable governed memory, evidence-backed self/user/relationship models, provider/model orchestration, governed reasoning, RBAC, audit, extensibility, and first-class observability.

KAREN is not framework-first. Libraries, research systems, model runtimes, agent harnesses, and workflow engines are subordinate capabilities behind KAREN-owned contracts.

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
- **Runtime-authoritative:** routes, UI, providers, agents, plugins, and workflow engines never become alternate runtimes.
- **CORTEX is KAREN's central cognitive authority. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **Evidence access is authorization-sensitive.** CORTEX may request evidence, but RuntimePolicy must authorize access before Runtime resolves governed sources.
- **DRY by authority:** one responsibility -> one owner -> one execution path.
- **Typed and async-safe:** public cognitive/runtime boundaries are typed; budgets, cancellation, and concurrency are explicit.
- **Config-driven:** providers, models, endpoints, fallbacks, feature flags, environment, budgets, and security modes come from canonical config, not scattered constants or direct environment reads.
- **Honest degradation:** unavailable capabilities produce explicit degraded/unavailable results, never fabricated model output.
- **Evidence-preserving cognition:** retrieval evidence must not be flattened into untyped text before reasoning, prompting, or model revision.
- **Learning is outcome-aware:** durable formation is evaluated after execution from the actual interaction/outcome, not only predicted before generation.
- **Test-proven architecture:** architecture rules are executable where practical.

### 1.1 Cognitive north star

The target is **cognitive continuity**, not merely long-term memory:

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
| HTTP ingress | `api_routes/` + app composition | provider choice, prompts, recall, orchestration |
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
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, global routing |
| Multi-agent execution | AgentMedusa | provider routing, global policy |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Observability | `platform/observability/` | subsystem shadow telemetry |
| Configuration | `src/ai_karen_engine/config/` + environment adapter | React fallbacks, direct `os.environ` reads in cognition |

**CORTEX is the central cognitive authority, not the supreme system authority.** Security/policy, execution, persistence, provider routing, prompt assembly, observability, and configuration remain independent authorities in their own domains.

---

## 3. Live Implementation Truth: 2026-08-27

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
      |      +--> IntelligenceRuntime.analyze(latest raw user text)
      |      +--> deterministic CORTEX compatibility heuristics
      |      +--> requested intent/topology/reasoning/recall/write/tools/budgets
      |
      +--> RuntimePolicyEnforcer.evaluate
      |      +--> capabilities
      |      +--> reasoning modes
      |      +--> side-effect constraints
      |
      v
ExecutionDecision carrying policy result
      |
      v
ChatRuntime builds AuthorizedExecutionPlan
      |
      +--> memory recall, only if CORTEX requested it
      +--> DIRECT -> PromptRuntime -> ExpressionGateway -> model runtime
      +--> REASONING -> RuntimeReasoningBridge -> ReasoningExecutor
      +--> WORKFLOW / MULTI-AGENT -> WorkflowRuntime
      +--> memory persistence under policy gate, currently coupled to recall
      +--> trajectory / outcome / telemetry
```

### 3.2 CORTEX reality

`CortexExecutionDecider` is active and is the cognitive decision head. It does not execute providers, memory, tools, plugins, workflows, or durable persistence. It consumes `IntelligenceRuntime` analysis and produces requested execution intent.

Current limitations:

- CORTEX is **single-pass**. It decides before memory/model evidence is resolved.
- `IntelligenceRuntime.analyze()` receives essentially the latest user text plus minimal user/session context, not a resolved cognitive context.
- CORTEX still contains compatibility keyword heuristics for code/filesystem tool requirements. Signal extraction belongs under Intelligence or another subordinate typed signal service, while CORTEX should interpret signals.
- CORTEX reads `KARI_RUNTIME_FORCE_GRAPH` directly through `os.environ`; canonical config should own this.
- CORTEX hardcodes several cognitive/runtime budget defaults, including the Soft Reasoning model-call floor. Defaults must move behind validated runtime/cognitive config where they are policy/configurable.

Current KAREN therefore behaves approximately as:

```text
raw request
 -> Intelligence signals
 -> CORTEX
 -> RuntimePolicy
 -> optional recall
 -> execute
```

It is not yet an evidence-informed executive loop.

### 3.3 RuntimePolicy reality

`RuntimeDecisionPipeline` correctly keeps CORTEX and RuntimePolicy as separate objects and applies policy after cognition.

However, the live policy request currently hardcodes:

```text
environment="production"
```

This violates canonical config ownership and can make development/test/runtime-level behavior semantically dishonest. Environment must come from validated runtime configuration/context.

The current pipeline has only one main authorization point **before execution**. The target two-stage cognitive loop also requires a policy authorization checkpoint **before governed evidence resolution**.

This does not create a second policy engine. It is the same RuntimePolicy authority evaluated for two different operations:

```text
Policy Gate A = may Runtime resolve these evidence sources/scopes?
Policy Gate B = may Runtime execute this final cognitive plan?
```

### 3.4 Cognitive state and context reality

`core/cognitive/state.py` already defines a substantial typed `CognitiveState` envelope including belief, goals, salience, context, reasoning, metacognition, adaptive state, policy snapshot, confidence domains, tenant, user, session, conversation, project, and temporal metadata.

Its tenant contract correctly rejects empty/default tenant scope.

`core/context` remains mostly vocabulary/resolution primitives rather than a competing cognitive executive.

**Critical gap:** canonical `ChatRuntime` does not carry `CognitiveState` or a richer `CognitiveContext` through ordinary chat execution.

### 3.5 Prompt reality

`ChatRuntime._assemble_prompt()` delegates final assembly to PromptRuntime, preserving the correct owner. But ChatRuntime directly constructs a minimal `PromptAssemblyRequest`.

Today that input contains messages, selected memory items, tool contracts, workflow metadata, and token budget. It does not yet carry resolved:

- SelfModel;
- UserModel;
- RelationshipModel;
- belief/claim state;
- goals/commitments;
- metacognitive state;
- evidence conflicts;
- typed provenance-preserving CognitiveContext.

A stronger existing PromptRuntime normalization path should be extended rather than creating another prompt-context builder.

### 3.6 Memory reality

Runtime recall correctly passes explicit `user_id`, `tenant_id`, session/conversation, query, top-k, and correlation context to the canonical memory manager.

But recalled results are flattened before downstream use to approximately:

```text
id
content
timestamp
```

Reasoning then reconstructs every recalled item with:

```text
relevance = 0.5
confidence = 0.5
```

This destroys evidence calibration and can make verified, stale, inferred, contradicted, or low-quality memories indistinguishable.

**Critical lifecycle defect:** both non-stream and stream persistence are gated by `decision.memory_recall_required`. Therefore a novel interaction can fail to become a learning candidate merely because no prior recall was needed.

There is a second coupling defect: `_persist_memory()` skips writes when recall failed/degraded. Read failure must not automatically suppress an independently authorized learning event.

### 3.7 Formation reality

The current memory-write request is predicted by CORTEX/Intelligence **before generation**. That can be useful as a preliminary write-intent hint, but it is not a sufficient formation decision because the actual assistant response, tool results, user correction, task success/failure, and observed outcome do not exist yet.

Target formation must therefore have two distinct concepts:

```text
pre-execution write intent / policy eligibility
post-execution formation evaluation based on actual outcome
```

Only the post-execution governed formation stage decides what becomes a durable memory candidate.

### 3.8 Self/User/Relationship reality

Personalization contains useful evidence/provenance-oriented contracts and services, but those models are not yet resolved into the canonical ChatRuntime decision/prompt path before ordinary generation.

KAREN therefore has model foundations, not yet full operational self/user/relationship continuity in normal chat.

### 3.9 Compatibility and naming debt

`RuntimeComposition.cortex` returns the **Runtime-owned `RuntimeDecisionPipeline`**, not `CortexExecutionDecider`.

`get_cortex_execution_decider()` also returns `RuntimeDecisionPipeline` despite its name.

These are compatibility shims whose names now misrepresent authority. No new consumer may depend on either misleading accessor.

The composition module's explanatory chain must also avoid implying that `RuntimeDecisionPipeline` is a stage after CORTEX and RuntimePolicy. The pipeline is the Runtime-owned container that invokes those two stages.

Target call sites should become explicit:

```text
requirements = cortex.determine_context_requirements(...)
evidence_auth = runtime_policy.evaluate_evidence_access(...)
context = runtime.resolve_authorized_evidence(...)
cognitive_decision = cortex.decide_with_context(...)
execution_auth = runtime_policy.evaluate_execution(...)
plan = runtime.build_authorized_plan(...)
```

### 3.10 Tenant contract risk

`ChatExecutionContext` still defines:

```text
tenant_id: str = "default"
```

while newer cognitive contracts reject default tenant scope. Production architecture requires explicit tenant scope. Removal must be preceded by ingress/caller/reference audit so compatibility does not accidentally bypass tenant isolation.

### 3.11 Live maturity classification

| Capability | Live status | Assessment |
|---|---|---|
| Runtime lifecycle authority | ACTIVE | strong |
| CORTEX cognitive decision head | ACTIVE | strong but single-pass |
| RuntimePolicy separation | ACTIVE | strong, but only one canonical execution authorization stage today |
| Evidence-access authorization | RED | target requires explicit pre-resolution policy gate |
| Intelligence signal layer | ACTIVE | useful, but CORTEX still contains compatibility feature heuristics |
| Typed CognitiveState | CONTRACT/PARTIAL | rich schema, not canonical chat envelope |
| Context/Evidence resolver | UNWIRED | vocabulary exists, canonical resolver does not |
| PromptRuntime authority | ACTIVE | final assembly canonical, context normalization thin |
| Governed memory recall | ACTIVE | final-mile evidence semantics flattened |
| Governed formation/persistence | ACTIVE/PARTIAL | coupled to recall; formation not outcome-aware enough |
| SelfModel in ordinary chat | CONTRACT/PARTIAL | not resolved into canonical execution context |
| UserModel in ordinary chat | PARTIAL | not central to canonical execution context |
| RelationshipModel in ordinary chat | CONTRACT/PARTIAL | not resolved into canonical execution context |
| Belief revision | PARTIAL/UNWIRED | vocabulary exists; canonical request-loop authority not proven |
| Metacognition | CONTRACT/REASONING MODE | not persistent calibrated metamemory |
| Evidence-preserving recall -> reasoning | RED | fixed synthetic relevance/confidence destroys signal |
| Two-stage evidence-informed CORTEX | RED | not implemented |
| Config purity at cognitive/policy boundary | RED/PARTIAL | direct env read, hardcoded environment/budgets remain |
| Cognitive consolidation loop | PARTIAL | subsystems exist; end-to-end loop not canonical |
| Human-like cognitive continuity | PARTIAL | strong organs, incomplete nervous system |

---

## 4. Target Cognitive Continuity Model

The target is a two-stage CORTEX with **two RuntimePolicy evaluations owned by the same policy authority**.

```text
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
                  RUNTIMEPOLICY GATE A
             evidence source / scope / RBAC /
             tenant / privacy / budget approval
                              |
                              v
                  Runtime EvidenceResolver
            +-----------------+-----------------+
            |                 |                 |
            v                 v                 v
         Memory            Models          Live State
            |                 |                 |
            +-----------------+-----------------+
                              v
                       CognitiveContext
                              |
                              v
                    CORTEX STAGE TWO
                 "what should happen now?"
                              |
                              v
                     CognitiveDecision
                              |
                              v
                  RUNTIMEPOLICY GATE B
          capability / side-effect / reasoning /
            resource / tool / human-gate auth
                              |
                              v
                  AuthorizedExecutionPlan
                              |
                              v
                           Runtime
            +-----------------+-----------------+
            |                 |                 |
            v                 v                 v
        Reasoning           Tools           Workflow
            +-----------------+-----------------+
                              |
                              v
                        PromptRuntime
                              |
                              v
                         Expression
                              |
                              v
                        ModelRuntime
                              |
                              v
                            Outcome
                              |
                              v
               Post-Execution Formation Eval
                              |
                              v
                        Consolidation
                              |
                              v
                       Belief Revision
              +---------------+---------------+
              |               |               |
              v               v               v
           SelfModel       UserModel    RelationshipModel
```

### 4.1 Stage boundaries

**CORTEX Stage 1 owns:** intent hypothesis, uncertainty estimate, evidence/context requirements, temporal horizon, requested memory classes/scopes, requested model facets, retrieval budget hints, and verification need.

**RuntimePolicy Gate A owns:** authorization of requested evidence sources, tenant/user/project scope, privacy/RBAC constraints, source-specific permissions, external lookup eligibility, and retrieval budget.

**Runtime EvidenceResolver owns:** execution of only Gate-A-authorized retrieval/resolution. It does not decide the final action and cannot expand its own authorization scope.

**CORTEX Stage 2 owns:** final intent/goal interpretation, evidence sufficiency/conflicts, cognitive topology, reasoning-mode requests, abstention/clarification/escalation recommendations, tool/workflow desirability, and requested compute budget.

**RuntimePolicy Gate B owns:** final capability, side-effect, tool, reasoning-mode, resource, provider constraint, and human-gate authorization.

**Runtime owns:** lifecycle, execution, retries/fallbacks, provider/model invocation, streaming, persistence coordination, telemetry, and audit.

**MemoryFormation owns:** post-execution evaluation of what experience/outcome is eligible to become memory.

---

## 5. Cognitive Semantics

Canonical semantic layers:

```text
Observation  = an observed event or input
Evidence     = typed, scoped, provenance-bearing support or contradiction
Memory       = stored representation of observation/experience/derived artifact
Claim        = proposition attributed to a source
Belief       = current evidence-weighted proposition held by KAREN
Knowledge    = sufficiently supported belief within explicit confidence/validity bounds
Decision     = cognitive recommendation selected by CORTEX
Action       = authorized execution performed by Runtime
Outcome      = observed result of an action
```

Historical evidence is immutable except for governed retention/deletion. Belief/model state may be revised. **Model revision must never silently rewrite historical evidence.**

Conflicting evidence follows:

```text
new evidence
 -> conflict detection
 -> temporal resolution
 -> provenance/source weighting
 -> confidence/calibration update
 -> supersede / dispute / abstain
 -> model revision
```

Do not overload persona:

```text
IdentityBaseline = designed identity and immutable product constraints
SelfBelief       = evidence-backed beliefs about KAREN's capabilities/history
SelfState        = temporary operational/session capability state
PersonaProfile   = optional communication/behavior overlay
```

Natural-language self-assessment may propose evidence but must not directly mutate durable SelfBelief.

---

## 6. Memory Architecture

```text
STM       recent/session state
Episodic  meaningful interactions, decisions, outcomes, reusable experience
LTM       durable facts, preferences, knowledge
```

NeuroRecall owns candidate-source coordination, semantic/temporal/graph/case fusion, ranking/reranking, contradiction/redundancy/diversity handling, scope-aware selection, recall abstention, recall confidence, and learned selection policy only behind evaluation gates.

MemoryFormation + NeuroVault own durable mutation and lifecycle governance.

Rules:

- recall engines do not persist;
- reasoning engines do not persist;
- CORTEX does not persist;
- Runtime coordinates authorized formation;
- read and write/formation decisions are independent;
- recall failure does not automatically cancel authorized formation;
- formation evaluates the **actual completed interaction/outcome**;
- tenant/user/workspace/project/session/conversation scope and provenance are explicit;
- no implicit production `tenant_id="default"` fallback.

---

## 7. Prompt-First Rules

PromptRuntime owns final prompt assembly. Runtime owns the resolved authorized context supplied to it. CORTEX does not construct final prompts.

Canonical prompt assembly may include system policy, task/output contract, explicit turn override, identity/persona/profile, tenant context, authorized evidence, Self/User/Relationship slices, goals/commitments, CORTEX intent/reasoning requirements, authorized tools/extensions, provider capability, token budget, safety, and output schema.

Do not create a second prompt-context builder while the existing PromptRuntime normalization path can be extended.

---

## 8. Reasoning Architecture

Reasoning modes are typed execution protocols, not capability strings.

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

Capabilities such as `memory.read`, `memory.write`, `web`, `code_execution`, and `filesystem_read` do not belong in reasoning-mode fields.

Soft Reasoning remains a specialist research-derived strategy under Runtime-authorized execution. It does not choose providers, build canonical prompts, own memory retrieval, or persist memory.

Reasoning evidence must preserve upstream provenance, relevance, confidence, temporal state, contradiction status, and scope. Synthetic defaults such as fixed `0.5` relevance/confidence are transitional defects only.

---

## 9. Provider, Workflow, and Agent Boundaries

Provider/model availability, selection, health, execution, and fallback remain centralized under the canonical model runtime/provider registry. CORTEX requests capability/locality constraints but does not bypass that router.

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

LangGraph is only for true graph semantics. Complexity alone does not imply LangGraph.

AgentMedusa is only for authorized multi-agent topology. Neither LangGraph nor AgentMedusa is KAREN's cognitive head.

---

## 10. Security and Governance

Preserve authentication/session validation, RBAC, tenant isolation, least privilege, credential redaction, extension/tool permission checks, audit logs, safe exception translation, request/correlation IDs, deletion/retention policy, and fail-closed production behavior.

Never let:

- CORTEX authorize itself;
- EvidenceResolver expand its own scope;
- evidence retrieval happen before policy authorization when the source is governed;
- memory bypass deletion/retention policy;
- raw untrusted model output become authoritative belief without provenance;
- UI checks substitute for backend authorization;
- fallback paths bypass policy.

RuntimePolicy remains independently testable from CORTEX and is reused for both evidence-access authorization and final execution authorization.

---

## 11. Configuration Authority

All runtime/cognitive configuration belongs under canonical configuration services in `src/ai_karen_engine/config` with environment adapters and validation.

Remove or migrate scattered direct configuration reads, including:

- direct `os.environ` feature-flag reads in CORTEX;
- hardcoded policy `environment="production"`;
- hardcoded reasoning/model-call floors that should be runtime-configurable;
- duplicated provider/model/fallback settings.

Every option needs a safe default where appropriate, environment override, validation, documentation, telemetry exposure when relevant, and fail-safe behavior.

---

## 12. Observability

Trace, when applicable:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
cortex_stage
intent
context_requirements
requested_evidence_sources
authorized_evidence_sources
denied_evidence_sources
context_item_count
requested_reasoning_modes
allowed_reasoning_modes
denied_reasoning_modes
policy_gate
policy_decision_id
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
formation_disposition
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

---

## 13. Composition and No-Hidden-Construction Rule

Live composition:

```text
RuntimeDecisionPipeline
   |- CortexExecutionDecider
   `- RuntimePolicyEnforcer

ChatRuntime
   |- RuntimeDecisionPipeline
   `- ExpressionGateway
```

This is the accurate containment model. Do not document `RuntimeDecisionPipeline` as though it executes after CORTEX and RuntimePolicy.

Target composition:

```text
Runtime cognitive lifecycle
   |- CortexExecutionDecider Stage 1
   |- RuntimePolicyEnforcer Gate A
   |- EvidenceResolver
   |- CortexExecutionDecider Stage 2
   `- RuntimePolicyEnforcer Gate B

ChatRuntime execution
```

Do not create a second global orchestrator to implement two-stage cognition. Runtime remains lifecycle owner.

Stateful canonical services must not silently instantiate alternate provider registries, memory managers, NeuroRecall instances, reasoning engines, prompt runtimes, policy engines, workflow orchestrators, or CORTEX instances.

Compatibility accessors may remain only when they resolve to canonical composed instances and have explicit removal conditions.

---

## 14. Priority Migration: COGNITIVE-CONTINUITY-1

Canonical implementation order:

1. **CORTEX-CONTEXT-1:** introduce typed `ContextRequirements` and `CognitiveContext`; split CORTEX into Stage 1 evidence-needs and Stage 2 evidence-informed decision without duplicating runtime orchestration.
2. **EVIDENCE-AUTH-1:** reuse RuntimePolicy as Gate A before evidence resolution; authorize source, scope, tenant/privacy/RBAC, and retrieval budget. No new policy engine.
3. **EVIDENCE-1:** preserve typed memory/model/live-state provenance, temporal state, relevance, confidence, contradictions, scope, and retrieval rationale through Runtime, PromptRuntime, and ReasoningEvidence.
4. **FORMATION-1:** decouple formation from recall and move durable formation eligibility to a post-execution, outcome-aware stage. Recall failure must not suppress independent authorized formation.
5. **PROMPT-CONTEXT-1:** route canonical resolved CognitiveContext through existing PromptRuntime normalization instead of direct minimal request construction.
6. **CONFIG-COGNITIVE-1:** migrate direct CORTEX environment reads, hardcoded policy environment, and cognitive budget constants into validated config.
7. **SELF-1:** operationalize evidence-backed SelfModel/SelfBelief and temporary SelfState.
8. **USER-REL-1:** resolve UserModel, RelationshipModel, goals, preferences, and commitments into scoped CognitiveContext.
9. **BELIEF-1:** establish canonical evidence/claim/belief revision with temporal conflict and supersession semantics.
10. **METACOGNITION-1:** add calibrated knowledge-gap, memory reliability, evidence sufficiency, retrieval-needed, abstention, and capability-awareness behavior.
11. **CONSOLIDATION-1:** connect outcomes to consolidation, semantic extraction, model revision, retention/forgetting, and reconsolidation policy.
12. **COGNITIVE-EVAL-1:** benchmark multi-session recall, temporal reasoning, knowledge updates, contradiction handling, abstention, long-range understanding, selective forgetting, and self-capability calibration.
13. **COMPAT-CORTEX-1:** remove/rename misleading `composition.cortex` and `get_cortex_execution_decider()` compatibility accessors after all callers migrate.

Do not add a new persona framework, context orchestrator, memory framework, policy engine, or agent harness before checking whether existing canonical contracts/services can be extended.

---

## 15. Repository and Cleanup Rules

Before changing a service:

1. identify the current owner;
2. search imports/references;
3. find stronger existing implementations;
4. classify touched code as active, misplaced, useful-incomplete, compatibility, experimental, dead, or dangerous;
5. merge into the canonical owner;
6. migrate consumers;
7. delete dead authority after reference audit;
8. add architecture tests preventing resurrection.

Broad namespaces are not authorities by name:

- `core/cortex` = cognitive decisions;
- `core/intelligence` = typed signals/features/predictions consumed by CORTEX;
- `core/cognitive` = typed cognitive state/vocabulary;
- `core/context` = context vocabulary/resolution primitives, never a competing cognitive executive;
- `core/reasoning` = authorized reasoning execution;
- `core/adaptive` = learning/adaptation capability, never global request routing;
- `core/runtime` = lifecycle/execution authority.

Never keep dead code "just in case."

---

## 16. Required Proof

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

Cognitive/runtime changes additionally prove:

```text
[ ] CORTEX has no RuntimePolicy construction/execution
[ ] CORTEX has no provider/tool/memory/persistence execution
[ ] Stage 1 emits typed ContextRequirements
[ ] RuntimePolicy Gate A runs before governed evidence resolution
[ ] EvidenceResolver cannot self-authorize or expand scope
[ ] Stage 2 receives typed CognitiveContext
[ ] RuntimePolicy Gate B runs after final CORTEX decision
[ ] both policy gates use the same canonical policy authority
[ ] environment/runtime level comes from canonical config, not hardcoded production
[ ] CORTEX has no direct environment feature-flag authority
[ ] cognitive budgets are config/policy driven
[ ] RuntimePolicy owns allowed/denied reasoning modes and capabilities
[ ] RuntimePolicy never invents a reasoning mode
[ ] Runtime remains the sole lifecycle/execution authority
[ ] IntelligenceRuntime remains signal-producing, not final cognitive authority
[ ] CORTEX compatibility feature heuristics are removed or explicitly sunset
[ ] capability and reasoning-mode domains remain distinct
[ ] rich recall evidence survives into reasoning and prompt context
[ ] no fixed fake confidence/relevance replaces upstream evidence metadata
[ ] memory formation is not gated by whether recall occurred
[ ] recall failure does not suppress independent authorized formation
[ ] post-execution formation evaluates actual outcome/response/tool results
[ ] Self/User/Relationship model slices are tenant/user scoped
[ ] durable writes remain governed by MemoryFormation / NeuroVault
[ ] production tenant scope is explicit
[ ] shared stateful dependencies are explicitly composed
[ ] no new consumer uses `composition.cortex`
[ ] no new consumer uses misleading `get_cortex_execution_decider()` compatibility accessor
```

Never report CI/tests green unless actually observed.

---

## 17. Research-Guided Development Rules

Research informs implementation; it does not gain architecture authority.

Favor mechanisms that fit KAREN-owned contracts: consolidation, interference/retention policy, reconsolidation, temporal knowledge updates, associative/entity links, multi-cue retrieval, evidence-aware memory evolution, metacognitive calibration, and explicit abstention.

Every research-derived capability documents source paper/repository, implemented mechanism, deviations, compute/resource assumptions, benchmark protocol, production activation policy, and fallback/abstention behavior.

Do not import a research system's whole orchestration model when its useful mechanism can be extracted behind KAREN's Runtime/CORTEX/Memory/Reasoning contracts.

---

## 18. Documentation Authority

Read in this order:

1. `PROJECT_DEV_MANIFEST.md`
2. live code and architecture tests
3. `docs/development/ARCHITECTURE_AUTHORITY.md`
4. accepted ADR/current dev sheet
5. subsystem documentation
6. historical sprint sheets as history only

If documentation disagrees with tested live behavior, classify it explicitly as **documentation drift** or **implementation debt**.

---

## 19. Final Architecture Test

Before merging, answer:

1. Who owns this responsibility now?
2. Is it duplicated elsewhere?
3. Does a stronger implementation already exist?
4. Is this signal production, cognitive decision, evidence authorization, evidence resolution, execution authorization, execution, formation, persistence, or presentation?
5. Does the change preserve local-first and prompt-first behavior?
6. Does it preserve RBAC, tenant isolation, audit, credentials, retention/deletion, and telemetry?
7. Does CORTEX remain cognitive authority without becoming an executor?
8. Does RuntimePolicy remain authorization-only while gating both governed evidence access and final execution?
9. Does Runtime remain the sole lifecycle/execution authority?
10. Does any subsystem silently construct or mutate an alternate authority?
11. Does evidence retain provenance, confidence, temporal state, contradiction state, and scope across boundaries?
12. Can a learning event form independently of whether recall happened or succeeded?
13. Is formation based on the actual completed interaction/outcome?
14. Are environment, budgets, flags, providers, and fallbacks sourced from canonical config?
15. What executable proof demonstrates the boundary?

If those answers are unclear, the design is not finished.

---

## 20. Canonical Mental Model

```text
CORTEX Stage 1    = What evidence does KAREN need?
RuntimePolicy A   = What evidence may KAREN access now?
EvidenceResolver  = Resolve only authorized evidence/context.
CORTEX Stage 2    = Given the evidence, what should KAREN do?
RuntimePolicy B   = What final work is KAREN allowed to perform?
Runtime           = Execute authorized work and own the request lifecycle.
Intelligence      = Produce typed signals/features/predictions for cognition.
CognitiveState    = Typed cognitive snapshot vocabulary, not an orchestrator.
NeuroRecall       = Which authorized past information is useful now?
MemoryFormation   = Which completed experiences/outcomes are eligible to become memory?
NeuroVault        = Govern durable memory mutation and lifecycle.
SelfModel         = Evidence-backed model of KAREN, not persona text.
UserModel         = Evidence-backed model of the user within scope.
RelationshipModel = Evidence-backed shared history/norms/commitments within scope.
BeliefRevision    = Reconcile evidence with current beliefs without rewriting history.
Reasoning         = Execute typed, authorized reasoning strategies.
SoftReasoning     = Governed specialist test-time exploration protocol.
LangGraph         = Execute explicit graph semantics only.
AgentMedusa       = Execute governed specialist-agent topology only.
PromptRuntime     = Serialize authorized resolved context into prompt contracts.
Expression        = Request generation through canonical runtime boundaries.
ModelRuntime      = Resolve and execute an eligible healthy provider/model.
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
