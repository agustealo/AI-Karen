# Karen Core Architecture: Authority Matrix & Layer Model

> **Status**: COG-AUTHORITY-1 (canonical)
> **Last updated**: 2026-08-26
> **Supersedes**: any document that makes LangGraph, AgentMedusa, Reasoning, Intelligence, or a provider layer the global runtime authority

## Cognitive Authority Model

Karen's cognitive architecture is authority-first, not pipeline-first. **CORTEX is the
global cognitive decision authority.** `core/intelligence` is a bounded analysis and ML
capability consumed by CORTEX. Intelligence produces observations, predictors,
embeddings, classifications, task signatures, and calibrated signals; it does not sit
above CORTEX and it does not independently decide what Karen should do.

Directory separation does not imply authority separation. `core/intelligence` remains
modular because analysis/ML machinery benefits from an isolated contract and lifecycle,
but that module is subordinate to the CORTEX decision boundary.

```text
1. CORTEX / Cognitive Decision -- understands/decides --> what should Karen do?
   +-- IntelligenceRuntime      -- analyzes/signals  --> what does the evidence suggest?
   +-- Adaptive                 -- advises           --> what has tended to work?
   +-- Personalization          -- contextualizes    --> what matters for this user?
   +-- governed memory evidence -- informs           --> what prior state is relevant?

2. RuntimePolicy               -- authorizes         --> what may Karen do?
3. Runtime                     -- executes           --> perform the authorized decision
4. Specialist Engines          -- serve              --> bounded cognition/workflows/agents
5. State                       -- retains            --> memory, recall, governance
6. Platform Kernel             -- governs            --> security, observability, infrastructure
```

The global authority chain is:

```text
                 +------------------------------+
                 |            CORTEX            |
                 | GLOBAL COGNITIVE DECISION    |
                 +------------------------------+
                   ^       ^        ^        ^
                   |       |        |        |
 IntelligenceRuntime   Adaptive  Personalization  governed memory evidence
 analysis/signals      advice    user context     recalled evidence
                   \       |        |        /
                    \------+--------+-------/
                              |
                              v
                       RuntimePolicy
                              |
                              v
                           Runtime
                              |
          +-------------------+-------------------+
          |                   |                   |
        DIRECT        ReasoningExecutor   WorkflowRuntime --> LangGraph
                                                |              +--> ReasoningExecutor
                                                |              +--> Tool runtime ports
                                                |              +--> AgentMedusa
                                                +--> provider/model runtime through Runtime
```

The verbs are intentionally different:

```text
ANALYZE != DECIDE != AUTHORIZE != ORCHESTRATE != REASON != EXECUTE
```

No subsystem may acquire a neighboring verb merely because it has enough context to
do so.

## Canonical Authority Matrix

| Domain | Owns | May Consume | Forbidden |
|---|---|---|---|
| **Intelligence** | linguistic analysis, embeddings, ML predictors, task signatures, feature/scoring signals | models, training data, safe data contracts | global cognitive decisions, execution decisions, authorization, provider routing, side effects |
| **CORTEX** | global intent, execution-topology recommendation, capability requirements, reasoning/verification requirements, risk and policy hints, RBAC-informed eligibility | Intelligence, Adaptive, Personalization, governed memory evidence | provider execution, direct model invocation, tool execution, persistence, graph execution |
| **RuntimePolicy** | final execution authorization, capability allowlists, budgets, human gates, policy decision identity | CORTEX decision, trusted auth/session/tenant context, security policy | provider execution, workflow planning, specialist reasoning |
| **Runtime** | chat lifecycle, request normalization, context assembly, memory recall coordination, prompt assembly, authorized execution-plan creation, topology dispatch, provider execution, tools/plugins, streaming, persistence, telemetry | CORTEX, RuntimePolicy, specialist engines | independent replacement of CORTEX intent/risk decisions |
| **Model Runtime** | inference, model loading, provider configuration and execution adapters | provider config, model artifacts, Runtime execution request | chat orchestration, global routing decisions, memory/policy ownership |
| **Reasoning** | specialist cognition: causal analysis, hypothesis work, evidence synthesis, verification, refinement, metacognition | AuthorizedExecutionPlan, evidence/context ports, Runtime-injected generation/tool capabilities | provider selection, persistence, global topology decisions, self-authorization |
| **LangGraph** | workflow topology, nodes/edges, branching, loops, parallelism, checkpoint/resume, HITL, workflow-local state | Runtime execution decision, AuthorizedExecutionPlan, Runtime service ports | global intent reclassification, authorization creation/expansion, provider policy, persistence ownership |
| **AgentMedusa** | bounded multi-agent team composition, specialist assignment, subtask decomposition, agent coordination, arbitration, agent-result aggregation | AuthorizedExecutionPlan, Runtime execution requirements, specialist registry, Runtime service ports | global topology selection, self-authorization, provider selection, prompt authority, memory/persistence ownership, policy expansion |
| **Adaptive** | recommendations, candidate ranking, learning from outcomes | outcomes, user state, Intelligence signals | authorization, provider execution |
| **Personalization** | user model, preferences, behavior adaptation, goals | memory evidence, Intelligence signals | memory storage, authorization, execution |
| **Memory** | storage lifecycle, episodic/LTM/graph stores | persistence infrastructure | routing, provider selection, global decision authority |
| **NeuroRecall** | retrieval strategy, ranking, signal extraction | memory stores, Intelligence signals | persistence ownership, routing, authorization |
| **NeuroVault** | governed persistence, archive, recovery, deletion/retention controls | Memory | everyday recall strategy, routing, model execution |
| **Prompt Runtime** | versioned prompt contracts and assembly | policy/persona/context/tool/provider capability inputs | provider selection, business decisions |
| **Observability** | metrics, traces, events, emitters | events from all domains | business logic, routing, authorization |
| **Security** | auth, RBAC, policy sources, secrets, tenant/session trust | identity, config | UI-only enforcement, provider execution |

## Execution Topology Contract

CORTEX recommends the topology. RuntimePolicy authorizes it. Runtime executes it.
The canonical topology vocabulary is:

```text
DIRECT
REASONING
WORKFLOW
MULTI_AGENT
```

The normal execution mapping is:

```text
DIRECT      -> Runtime
REASONING   -> Runtime -> ReasoningExecutor
WORKFLOW    -> Runtime -> WorkflowRuntime -> LangGraph
MULTI_AGENT -> Runtime -> WorkflowRuntime -> LangGraph multi-agent stage -> AgentMedusa
```

A direct AgentMedusa runtime path must not be added unless a concrete use case proves
that multi-agent execution requires no workflow semantics and the architecture
contract is deliberately revised. Do not create a second path speculatively.

### Topology invariants

1. CORTEX may recommend a topology but may not execute it.
2. RuntimePolicy may authorize a topology but may not perform it.
3. Runtime is the only global execution authority.
4. LangGraph expresses an authorized workflow. It does not decide whether the user
   request globally requires a workflow.
5. AgentMedusa coordinates an authorized multi-agent stage. It does not decide
   whether the user request globally requires multiple agents.
6. ReasoningExecutor performs specialist cognition. It does not decide whether the
   request globally requires reasoning.

## Plan Semantics

Karen has multiple legitimate plan-like objects. They are not interchangeable.

### ExecutionRequirements

Produced from CORTEX/Runtime analysis. Describes what execution requires.

### AuthorizedExecutionPlan

Created at the Runtime/RuntimePolicy boundary. Describes what execution **may** do.
It is immutable execution authority for downstream specialists.

### WorkflowPlan

Created inside an already-authorized workflow. Describes how LangGraph intends to
sequence work.

### DeepExecutionPlan

Created by AgentMedusa inside an authorized multi-agent stage. Describes how the
agent team intends to assign and sequence specialist work.

The containment rule is:

```text
WorkflowPlan    subset-of AuthorizedExecutionPlan
DeepExecutionPlan subset-of AuthorizedExecutionPlan
```

Neither LangGraph nor AgentMedusa may add a capability, tool, plugin, provider,
action, budget, filesystem scope, memory scope, or human-gate bypass that the
AuthorizedExecutionPlan did not allow.

## Scope-Specific State

Three state scopes are intentionally distinct:

```text
CognitiveState = canonical cognition state
WorkflowState  = resumable workflow state
AgentState     = one agent/subteam execution state
```

`core/cognitive/state.py::CognitiveState` is the whole-system cognitive-state
authority. Workflow and agent state may reference or carry a scoped cognitive
snapshot but must not redefine the global cognitive contract.

## Cross-Cutting Authority Rules

### Provider/model routing

Runtime/provider routing is the only provider-selection authority.

- CORTEX expresses requirements and preferences only.
- LangGraph requests model execution through Runtime ports.
- Reasoning consumes Runtime-injected generation capabilities.
- AgentMedusa specialists consume Runtime generation ports/bridges.
- No specialist subsystem may instantiate or query a provider registry to choose
  the active model for itself.

### Memory

Memory stores, NeuroRecall, and NeuroVault are canonical memory authorities.

- CORTEX decides whether memory is relevant and what scope is required.
- Runtime coordinates governed recall and persistence.
- Reasoning consumes evidence/context; it does not own durable writeback.
- LangGraph may sequence memory operations through canonical Runtime ports.
- AgentMedusa receives agent-scoped memory/evidence access; it does not create a
  parallel memory subsystem.

### Prompts

Permanent prompt behavior belongs to versioned Prompt Runtime contracts.
CORTEX, LangGraph nodes, Reasoning strategies, AgentMedusa specialists, tools, and
providers consume prompt contracts rather than growing independent permanent prompt
assembly systems.

### Tools/plugins

Runtime owns governed tool/plugin execution. Workflows, reasoners, and agents may
request actions only through allowed ports and only within the AuthorizedExecutionPlan.

### Persistence

Runtime owns request/response persistence coordination and audit correlation.
Specialists emit structured outcomes/events. They do not silently persist parallel
conversation, memory, or execution truth.

## Generation Classification

### Generation A (old generalized framework) -- REMOVE

- `core/services/` (service registry monolith)
- `core/data_models/` (generic data model namespace)
- `core/echo_core/` (prototype echo/demo code)
- `core/response/` (compatibility fossil, superseded by Runtime contracts)
- `core/operations/` (metrics/monitoring, belongs in observability)

### Generation B (transitional orchestration) -- CONVERGE

- `langgraph_orchestrator/decision_engine.py`
- `langgraph_orchestrator/runtime_policy.py`
- legacy runtime helpers
- old AgentMedusa design documents that call LangGraph or Medusa the global runtime
- reasoning graph/provider/memory vertical slices
- agent memory mega-services

### Generation C (current canonical) -- PRESERVE

- `runtime/` -- execution authority
- `cortex/` -- global decision authority
- `intelligence/` -- analysis/signals
- `model_runtime/` -- inference
- `reasoning/` -- specialist cognition
- `langgraph_orchestrator/` -- workflows only
- `agent_medusa/` -- bounded multi-agent topology coordinator
- `adaptive/` -- advisory only
- `personalization/` -- advisory/contextual
- `observability/` -- metrics/traces
- `security/` -- auth/RBAC/policy sources
- `memory/` -- storage/lifecycle
- `neuro_recall/` -- retrieval/ranking
- `neuro_vault/` -- governance/archive

## Domains to Remove (CORE-PRUNE-1 targets)

```text
echo_core/      -- prototype/demo, no production imports
response/       -- compatibility fossil, Runtime contracts supersede
data_models/    -- generic namespace, contracts scattered or dead
operations/     -- metrics/collection, belongs in observability
```

## Domains to Preserve

```text
adaptive/               GOVERNED ADVISOR
agent_medusa/            MULTI-AGENT COORDINATION ONLY
automation/              KEEPS
cognitive/               COGNITIVE STATE/TYPED COGNITION
cortex/                  GLOBAL DECISION AUTHORITY
errors/                  KEEPS
intelligence/            ANALYSIS / ML SIGNALS
langgraph_orchestrator/  WORKFLOWS ONLY
logging/                 KEEPS
memory/                  STORAGE/LIFECYCLE
model_runtime/           INFERENCE
neuro_recall/            RETRIEVAL/RANKING
neuro_vault/             GOVERNANCE/ARCHIVE
observability/           METRICS/TRACES
personalization/         ADVISORY
reasoning/               SPECIALIST COGNITION
runtime/                 GLOBAL EXECUTION AUTHORITY
security/                AUTH/RBAC/POLICY SOURCES
```

## Platform Adapters (not core domains)

These are platform/infrastructure concerns, not core cognitive domains. They belong
in coherent platform boundaries, not as duplicate cognitive authorities:

```text
config/supabase/ -- adapter/platform behavior
queues/          -- task queue infrastructure
realtime/        -- realtime event infrastructure
cron/            -- scheduling infrastructure
storage/         -- artifact/object storage
```

## Import-Boundary Rules

Dependency-direction rules are enforced by architecture tests.

```text
intelligence  -/-> runtime execution
personalization -/-> runtime execution
adaptive      -/-> provider execution
cortex        -/-> provider execution
cortex        -/-> langgraph execution
reasoning     -/-> api routes
reasoning     -/-> provider selection
reasoning     -/-> durable memory persistence authority
langgraph     -/-> provider selection
langgraph     -/-> global intent classification
langgraph     -/-> authorization creation/expansion
agent_medusa  -/-> global topology decision
agent_medusa  -/-> provider selection
agent_medusa  -/-> prompt authority
agent_medusa  -/-> authorization creation/expansion
model_runtime -/-> chat runtime orchestration
memory        -/-> cortex execution
observability -/-> business runtime services
```

Any compatibility exception must identify its owner, replacement, sunset condition,
and expiry. A compatibility shim is not a second authority.

## Cognitive Continuity Invariant

> Karen's behavior MUST be capable of being influenced by relevant prior experience,
> learned user knowledge, temporal state, active goals, relationships, unresolved
> intentions, and consolidated learning without requiring raw conversation history to
> remain in the model context.
>
> Memory retrieval MUST NOT depend solely on vector similarity.
>
> Durable beliefs MUST retain provenance, confidence, temporal validity, and
> contradiction/supersession relationships.
>
> Episodic memory, semantic consolidation, associative recall, temporal reasoning,
> and controlled forgetting are Core cognitive responsibilities.
>
> Concrete storage, vector databases, caches, graph databases, embedding
> implementations, and scheduling infrastructure are not Core cognitive authority.

## Memory Cognitive Architecture

Karen's cognitive memory model follows this lifecycle:

```text
PERCEIVE -> ENCODE -> SCORE_SALIENCE -> ASSOCIATE -> STORE_EPISODE ->
REPLAY_REFLECT -> CONSOLIDATE -> GENERALIZE -> RETRIEVE ->
RECONSOLIDATE -> DECAY_SUPERSEDE_FORGET
```

### Memory Types

1. **Working Memory** -- current mental workspace
2. **Episodic Memory** -- specific interactions and experiences
3. **Semantic Memory** -- durable facts and generalized knowledge
4. **Autobiographical Memory** -- Karen-user history and meaningful shared events
5. **Preference Memory** -- likes, dislikes, styles, recurring choices
6. **Procedural Memory** -- successful ways of doing things
7. **Prospective Memory** -- intentions, commitments, unfinished work
8. **Relational Memory** -- people, projects, objects and how they connect
9. **Temporal Memory** -- when something was true and for how long
10. **Salience Memory** -- importance, surprise, emotional relevance, consequences
11. **Belief Memory** -- claims with confidence and evidence
12. **Meta Memory** -- what Karen knows, doubts, forgot, or needs to verify

### Recall Score Formula

```text
RecallScore =
    semantic_similarity
  + associative_activation
  + temporal_relevance
  + salience
  + relationship_relevance
  + current_goal_relevance
  + repetition_strength
  + causal_relevance
  + unresolved_intention_relevance
  + explicit_user_priority
  - contradiction_penalty
  - staleness
  - interference
```

### Controlled Forgetting

Three mechanisms:

- **DECAY**: low-value unused memories become less retrievable
- **SUPPRESSION**: irrelevant memories lose activation in current context
- **CONSOLIDATION**: many similar episodes become stronger generalized memory

## Cognitive Proof Suite

The cognitive benchmark proves behavior. Architecture tests separately prove that the
behavior travels through the correct authority path. Both are required.

```text
[ ] recalls explicit user preference after session boundary
[ ] retrieves related memory without lexical overlap
[ ] newer preference supersedes older preference
[ ] old episode remains available as provenance
[ ] distinguishes event time from conversation time
[ ] repeated episodes consolidate into semantic memory
[ ] one isolated event does not become strong user preference
[ ] contradictory memories lower confidence
[ ] unresolved intention can resurface when relevant
[ ] irrelevant old memories decay in retrieval rank
[ ] high-salience decision survives longer than trivial detail
[ ] recall spans associative graph neighbors
[ ] retrieved memories influence CORTEX action selection
[ ] CORTEX cannot treat inferred memory as verified fact
[ ] cross-tenant memories can never activate
[ ] deleted/retracted memories cannot reappear from vector/graph indexes
[ ] memory reconstruction preserves provenance
[ ] provider replacement does not change memory semantics
[ ] Redis/Milvus outage degrades honestly rather than inventing recall
[ ] CORTEX is the only global cognitive decision owner
[ ] RuntimePolicy is the authorization gate
[ ] Runtime is the only global execution owner
[ ] LangGraph cannot expand authorization or reclassify global intent
[ ] ReasoningExecutor cannot select providers or persist memory directly
[ ] AgentMedusa cannot self-authorize or expand capabilities
[ ] WorkflowPlan and DeepExecutionPlan remain subsets of AuthorizedExecutionPlan
```
