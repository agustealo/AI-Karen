# Reasoning, LangGraph, and AgentMedusa

> **Authority:** subordinate to `src/ai_karen_engine/core/ARCHITECTURE.md`.
> If this document and the Core authority matrix ever disagree, the Core matrix wins.

## 1. Why the distinction matters

Reasoning, graph orchestration, and multi-agent execution solve different problems.
They may cooperate, but none may become a shadow ChatRuntime.

```text
Intelligence -> CORTEX -> RuntimePolicy -> ChatRuntime
                                         +-> DIRECT
                                         +-> ReasoningExecutor
                                         +-> WorkflowRuntime -> LangGraph
                                                              +-> ReasoningExecutor
                                                              +-> runtime tool ports
                                                              +-> AgentMedusa
```

The boundary rule is:

```text
ANALYZE != DECIDE != AUTHORIZE != ORCHESTRATE != REASON != EXECUTE
```

CORTEX recommends execution requirements/topology. RuntimePolicy authorizes.
ChatRuntime executes. LangGraph sequences an authorized workflow. AgentMedusa
coordinates an authorized multi-agent stage. ReasoningExecutor performs specialist
cognition.

## 2. Canonical reasoning

Reasoning owns structured cognitive work such as:

- goal/constraint modeling;
- cognitive decomposition inside a reasoning operation;
- hypothesis generation/comparison;
- evidence classification/synthesis;
- verification;
- confidence and uncertainty analysis;
- contradiction/unknown tracking;
- causal analysis;
- refinement and metacognition.

Reasoning consumes Runtime-injected model/generation/evidence capabilities. It does
not select providers, create execution authorization, own durable memory writeback,
or decide global execution topology.

### Reasoning rules

- use canonical cognitive contracts;
- keep reasoning state typed;
- separate evidence from assertions;
- distinguish confidence domains when semantics differ;
- represent unknowns and verification status explicitly;
- do not depend on hidden chain-of-thought persistence;
- preserve deterministic identifiers/state where reproducibility requires them;
- consume `AuthorizedExecutionPlan` rather than constructing one;
- emit outcomes, reason codes, evidence refs, and metrics rather than private chain of thought.

## 3. LangChain

LangChain is a library/toolkit, not an architectural owner.

Use individual LangChain components only when they materially reduce adapter/tool/
retrieval integration cost and do not introduce:

- a second provider router;
- a second memory store;
- a second prompt authority;
- an alternate agent runtime;
- hidden fallback behavior.

Wrap library-specific types behind KAREN contracts where they cross subsystem
boundaries.

## 4. LangGraph

LangGraph is appropriate when execution actually needs a graph.

### LangGraph owns

- workflow nodes/edges;
- conditional branching and loops;
- parallel workflow stages;
- checkpoint/resume;
- persistent workflow-local state;
- human approval waits;
- retry/compensation edges;
- cross-stage transitions.

### LangGraph does not own

- global intent classification;
- global topology selection;
- RuntimePolicy authorization;
- provider/model selection;
- fallback policy;
- durable memory/persistence truth;
- permanent prompt assembly;
- specialist reasoning algorithms;
- multi-agent team semantics.

### Graph node rule

Nodes consume canonical ports/services and the Runtime-provided
`AuthorizedExecutionPlan`. A graph node may narrow behavior inside the authorized
plan but may never expand capabilities, tools, plugins, agents, memory/resource
scope, budgets, or approval privileges.

A workflow-local classifier may classify an intermediate artifact/subtask. It must
not silently reclassify the original user request after CORTEX has made the global
decision.

## 5. AgentMedusa

AgentMedusa is KAREN's canonical **multi-agent coordination subsystem**, not the
global runtime.

The normal multi-agent path is:

```text
RuntimePolicy
   -> ChatRuntime
      -> WorkflowRuntime
         -> LangGraph multi-agent stage
            -> AgentMedusa
               -> specialist A
               -> specialist B
               -> arbitration/aggregation
```

Do not add a second direct Medusa runtime path unless a concrete use case proves
multi-agent execution needs no workflow semantics and the canonical architecture is
deliberately revised first.

### Medusa owns

- task decomposition **inside an already-authorized multi-agent stage**;
- specialist selection from the authorized agent/capability set;
- dependency-aware team planning;
- subagent coordination;
- bounded parallel execution;
- cancellation-aware agent lifecycle;
- selective arbitration/aggregation;
- trajectory/run assembly;
- multi-agent degradation reporting.

### Medusa enforces but does not originate

- execution budgets;
- allowed agents/capabilities;
- tool/plugin permissions;
- memory/resource scope;
- approval requirements.

Those originate in RuntimePolicy/Runtime authorization.

### Medusa does not own

- global execution-topology selection;
- provider/model policy or fallback order;
- canonical prompt building;
- global RBAC/policy;
- credentials;
- memory persistence;
- plugin permission authority;
- ordinary single-model chat;
- a second reasoning framework.

Medusa agents may invoke canonical ReasoningExecutor capabilities. Agent code must
not grow parallel causal/verifier/metacognition engines.

## 6. Agent definitions

An agent is an execution specialist, not a free-form persona. A governed definition
should identify, as applicable:

- stable agent ID/version;
- implementation ID/hash;
- capabilities;
- prompt contract ID/version;
- reasoning modes;
- allowed tools/extensions;
- output contract;
- execution-budget requirements;
- subagent/depth/parallelism limits;
- approval/human-gate requirements;
- memory scope requirements;
- tenant/role/permission constraints.

Registration declares requirements. RuntimePolicy determines what is authorized for
a request. Do not store arbitrary raw permanent system prompts in agent registration
when a canonical prompt contract can be referenced.

## 7. Plan hierarchy

These objects have different meanings:

```text
ExecutionRequirements   = what execution requires
AuthorizedExecutionPlan = what execution may do
WorkflowPlan            = how an authorized workflow intends to proceed
DeepExecutionPlan       = how an authorized Medusa team intends to proceed
```

The invariant is:

```text
WorkflowPlan       subset-of AuthorizedExecutionPlan
DeepExecutionPlan  subset-of AuthorizedExecutionPlan
```

No downstream planner may add authority.

## 8. Execution topology examples

### Direct response

```text
CORTEX -> RuntimePolicy -> ChatRuntime -> runtime provider/model path -> response
```

### Reasoned response

```text
CORTEX -> RuntimePolicy -> ChatRuntime -> ReasoningExecutor
                                      -> Runtime-injected generation/evidence
                                      -> verified reasoning result
```

### Graph workflow

```text
CORTEX -> RuntimePolicy -> ChatRuntime -> WorkflowRuntime -> LangGraph
                                                    -> canonical runtime ports
                                                    -> workflow result
```

### Multi-agent workflow

```text
CORTEX -> RuntimePolicy -> ChatRuntime -> WorkflowRuntime -> LangGraph
                                                    -> AgentMedusa
                                                       -> specialists
                                                       -> arbitration
                                                    -> workflow result
```

## 9. State boundaries

Keep state scopes separate:

```text
CognitiveState = canonical cognition state
WorkflowState  = resumable workflow state
AgentState     = one agent/subteam execution state
```

WorkflowState and AgentState may carry scoped cognitive snapshots or references but
must not redefine the whole-system `CognitiveState` contract.

## 10. Security

Every reasoning/agent/tool/graph action must preserve:

- authenticated actor;
- tenant scope;
- capability/permission eligibility;
- policy decision ID;
- action side-effect rules;
- memory/resource scope;
- audit context;
- correlation/request IDs;
- execution budget.

Subagent delegation and graph specialist stages fail closed when authorization or
contract validation fails.

## 11. Observability

Capture structured metadata such as:

- request/correlation/policy decision IDs;
- tenant/user/conversation IDs as permitted;
- execution topology;
- reasoning mode/depth;
- workflow/graph ID;
- agent ID/version and parent-child linkage;
- subagent count and dependency step;
- tool/extension IDs;
- budget consumption;
- actual provider/model/runtime engine;
- fallback/degradation;
- latency/status/error codes.

Do not log secrets or hidden reasoning.

## 12. Proof

Architecture and execution tests should prove:

- no provider authority leaks into Reasoning/LangGraph/Medusa;
- LangGraph is not required for simple chat;
- LangGraph cannot synthesize or expand authorization;
- Medusa selection comes from Runtime-authorized topology, not intent-name hacks;
- Medusa cannot self-authorize or expand the agent allowlist;
- WorkflowPlan/DeepExecutionPlan remain inside AuthorizedExecutionPlan;
- deterministic graph state/IDs where promised;
- runtime-injected generation clients;
- agent definition validation;
- tenant/RBAC/policy dominance;
- bounded parallelism/budgets;
- cancellation and failure semantics;
- multi-agent trajectory/provenance;
- no alternate memory/prompt/provider registries.
