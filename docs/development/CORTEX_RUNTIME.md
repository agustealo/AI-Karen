# CORTEX and Runtime Contracts

## 1. Separation of decision and execution

KAREN's cognitive architecture intentionally separates **deciding what should happen** from **performing the work**.

```text
request/context
   -> intelligence signals
   -> CORTEX
   -> RuntimePolicy / execution contract
   -> ChatRuntime
   -> provider/reasoning/graph/agent/action execution
```

## 2. CORTEX responsibilities

CORTEX may produce typed decisions/signals for:

- intent classification;
- capability requirements;
- reasoning depth/mode;
- verification/evidence requirements;
- memory recall strategy hints;
- execution topology;
- tool/extension eligibility;
- agent delegation eligibility;
- policy/RBAC action eligibility;
- confidence, constraints, unknowns, and reasoning hints.

Public cognitive boundaries should use canonical typed contracts rather than arbitrary dictionaries.

## 3. CORTEX prohibitions

CORTEX does not:

- invoke providers/models;
- select provider endpoints through ad-hoc networking;
- construct final provider prompts;
- persist chat messages;
- write an alternate memory store;
- invoke plugin/tool side effects;
- manage agent task execution;
- stream user responses.

A CORTEX implementation that performs those operations has crossed into Runtime authority.

## 4. ChatRuntime responsibilities

The runtime owns the complete execution lifecycle:

1. normalize request;
2. establish execution/correlation context;
3. coordinate memory recall;
4. consume CORTEX/policy decisions;
5. assemble canonical prompt/context;
6. select authorized execution topology;
7. execute provider/reasoning/LangGraph/Medusa/action path;
8. collect degradation/provenance metadata;
9. stream/assemble response;
10. persist messages and eligible memory candidates;
11. emit telemetry and audit events.

## 5. RuntimePolicy

RuntimePolicy is an execution contract/policy representation consumed by the runtime. It is not another orchestrator.

Policy must remain inspectable and testable. Important decisions should have stable reason codes where practical.

## 6. Cognitive contracts

The cognitive layer should centralize concepts such as:

- reasoning depth;
- evidence/verification requirements;
- goals and goal state;
- confidence domains;
- constraints/unknowns;
- cognitive state;
- action eligibility.

Do not create parallel versions of these concepts under providers, agents, API routes, or LangGraph state unless they are adapters to the canonical type.

## 7. Assistant profile vs personalization vs agents

These are distinct:

- **Assistant Profile**: selectable KAREN behavior/identity defaults, ideally referenced by stable versioned ID.
- **Personalization**: explicit/learned user-specific preferences and state.
- **Agent Definition**: execution specialist with capabilities, permissions, prompt-contract references, budgets, and topology metadata.

Precedence for behavior:

```text
system/policy
 > task/output contract
 > explicit turn override
 > explicit user preference
 > assistant-profile defaults
 > global defaults
```

Assistant profiles do not own memory, provider selection, tools, RBAC, or raw user preference storage.

## 8. API relationship

Routes pass authenticated and validated context into runtime. A route may not implement a shortcut around CORTEX/RuntimePolicy for privileged actions.

## 9. Observability

Cognitive decisions should be traceable without logging hidden chain-of-thought. Emit structured data such as:

- intent;
- topology;
- reasoning mode/depth;
- verification mode;
- capability requirements;
- policy decision/reason codes;
- confidence domain/score where appropriate;
- decision latency.

Do not persist private scratch reasoning as telemetry.

## 10. Tests

Required architecture proof should cover:

- CORTEX has no provider/platform authority;
- one canonical ReasoningDepth/verification/evidence/goal-state contract;
- policy dominance and RBAC gates;
- runtime consumes cognitive decisions;
- provider/model execution remains outside CORTEX;
- typed cognitive benchmark/contract tests remain green.
