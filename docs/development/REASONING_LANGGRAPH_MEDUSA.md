# Reasoning, LangGraph, and AgentMedusa

## 1. Why the distinction matters

Reasoning, graph orchestration, and multi-agent execution solve different problems. They may cooperate, but none may become a shadow ChatRuntime.

```text
CORTEX / RuntimePolicy
        |
        v
ChatRuntime
   +--> canonical reasoning
   +--> LangGraph when graph semantics are required
   +--> AgentMedusa when specialist multi-agent topology is required
```

## 2. Canonical reasoning

Reasoning owns structured cognitive work such as:

- decomposition;
- goal/constraint modeling;
- hypothesis generation;
- evidence classification;
- verification requirements;
- confidence analysis;
- contradiction/unknown tracking;
- reasoning depth/mode;
- synthesis contracts.

Reasoning should consume runtime-injected model/generation capabilities. It does not select provider infrastructure itself.

### Reasoning rules

- use canonical cognitive contracts;
- keep reasoning state typed;
- separate evidence from assertions;
- distinguish confidence domains rather than one universal confidence number when semantics differ;
- represent unknowns and verification status explicitly;
- do not depend on hidden chain-of-thought persistence;
- preserve deterministic identifiers/state where execution reproducibility requires them.

## 3. LangChain

LangChain is a library/toolkit, not an architectural owner.

Use individual LangChain components only when they materially reduce adapter/tool/retrieval integration cost and do not introduce:

- a second provider router;
- a second memory store;
- a second prompt authority;
- an alternate agent runtime;
- hidden fallback behavior.

Wrap library-specific types behind KAREN contracts where they cross subsystem boundaries.

## 4. LangGraph

LangGraph is appropriate when execution actually needs a graph.

Good uses:

- conditional branching;
- checkpoint/resume;
- persistent graph state;
- human approval nodes;
- retries represented as workflow edges;
- multi-stage tool chains with explicit topology;
- long-running workflows that benefit from durable state transitions.

Bad uses:

- ordinary request/response chat;
- simple provider fallback;
- a generic wrapper around every runtime call;
- replacing CORTEX policy decisions;
- replacing AgentMedusa specialist coordination;
- duplicating prompt/memory/provider services inside graph nodes.

### Graph node rule

Nodes consume canonical ports/services. A node should not invent private versions of provider selection, prompt assembly, memory recall, or authorization.

## 5. AgentMedusa

AgentMedusa is the canonical multi-agent execution topology.

### Medusa owns

- task decomposition into specialist work;
- specialist/agent selection using declared capability;
- dependency-aware execution planning;
- subagent coordination;
- bounded parallelism;
- execution budgets/depth/subagent limits;
- cancellation-aware lifecycle;
- selective arbitration/synthesis;
- trajectory/run assembly;
- multi-agent degradation metadata.

### Medusa does not own

- provider/model policy;
- provider fallback order;
- canonical prompt building;
- global RBAC/policy;
- credentials;
- memory persistence;
- plugin permission authority;
- ordinary single-model chat.

## 6. Agent definitions

An agent is an execution specialist, not a free-form persona.

A governed definition should identify, as applicable:

- stable agent ID/version;
- implementation ID/hash;
- capabilities;
- prompt contract ID/version;
- reasoning modes;
- allowed tools/extensions;
- output contract;
- execution budget;
- subagent/depth/parallelism limits;
- approval/human-gate requirements;
- memory scope;
- tenant/role/permission constraints.

Do not store arbitrary raw system prompts inside agent registration if a canonical prompt contract can be referenced.

## 7. Execution topology examples

### Direct response

```text
RuntimePolicy -> ChatRuntime -> provider/model -> response
```

### Reasoned response

```text
RuntimePolicy -> ChatRuntime -> reasoning contract -> runtime-selected model -> verification -> response
```

### Graph workflow

```text
RuntimePolicy -> ChatRuntime -> LangGraph -> canonical tools/services -> final graph result -> response
```

### Multi-agent

```text
RuntimePolicy -> ChatRuntime -> AgentMedusa
                              -> specialist A
                              -> specialist B
                              -> arbitration/synthesis
                              -> response
```

Medusa specialists still reach model/tools/memory through canonical runtime ports.

## 8. Security

Every agent/tool/graph action must preserve:

- authenticated actor;
- tenant scope;
- capability/permission eligibility;
- action side-effect rules;
- audit context;
- correlation/request IDs.

Subagent delegation must fail closed when permission or definition validation fails.

## 9. Observability

Capture structured metadata such as:

- topology;
- reasoning mode/depth;
- workflow/graph ID;
- agent ID/version;
- subagent count;
- dependency step;
- tool/extension IDs;
- execution budget consumption;
- provider/model actually used;
- fallback/degradation;
- latency/status/error codes.

Do not log secrets or hidden reasoning.

## 10. Tests

Prove:

- no provider authority leaks into reasoning/Medusa;
- LangGraph is not required for simple chat;
- deterministic graph node IDs/state where promised;
- runtime-injected generation clients;
- agent definition validation;
- RBAC/permission dominance;
- bounded parallelism/budgets;
- cancellation and failure semantics;
- multi-agent trajectory/provenance;
- no alternate memory/prompt/provider registries.
