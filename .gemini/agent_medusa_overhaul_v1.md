# AgentMedusa Overhaul V1 - RETIRED

> **Status:** RETIRED / HISTORICAL ONLY
> **Retired:** 2026-08-26
> **Canonical authority:** `src/ai_karen_engine/core/ARCHITECTURE.md`

This document previously described an architecture in which `LangGraphOrchestrator`
was the sole production runtime authority and AgentMedusa owned broad planning,
routing, execution policy, provider/model choice, persistence, and orchestration.
That design is no longer authoritative and must not be used as implementation
guidance.

## Why this was retired

The repository has since converged on a stricter single-authority model:

```text
Intelligence -> CORTEX -> RuntimePolicy -> Runtime
                                      |
                                      +-> DIRECT
                                      +-> ReasoningExecutor
                                      +-> WorkflowRuntime -> LangGraph
                                                           +-> ReasoningExecutor
                                                           +-> Tool runtime ports
                                                           +-> AgentMedusa
```

The important distinction is:

```text
ANALYZE != DECIDE != AUTHORIZE != ORCHESTRATE != REASON != EXECUTE
```

## Current AgentMedusa role

AgentMedusa is a **bounded multi-agent topology coordinator**. It may:

- compose an authorized specialist team,
- decompose an authorized multi-agent stage into subtasks,
- assign specialists,
- coordinate agent execution,
- arbitrate competing agent outputs,
- aggregate structured results,
- emit scoped telemetry and execution events.

AgentMedusa must consume RuntimePolicy/Runtime authority. It may not:

- decide the global execution topology,
- create or expand `AuthorizedExecutionPlan`,
- select providers/models independently,
- own permanent prompt assembly,
- create a parallel memory subsystem,
- own durable conversation/memory persistence,
- bypass tool/plugin permission gates,
- become a second chat runtime.

## Current LangGraph role

LangGraph owns workflow semantics only:

- nodes and edges,
- branching and loops,
- parallel workflow stages,
- checkpoint/resume,
- human-in-the-loop waits,
- workflow-local state.

LangGraph consumes the Runtime execution decision and authorized plan. It does not
own global intent classification, provider policy, RuntimePolicy authorization, or
persistence truth.

## Current plan hierarchy

```text
ExecutionRequirements   = what execution requires
AuthorizedExecutionPlan = what execution may do
WorkflowPlan            = how an authorized workflow intends to proceed
DeepExecutionPlan       = how an authorized Medusa team intends to proceed
```

`WorkflowPlan` and `DeepExecutionPlan` must remain subsets of the
`AuthorizedExecutionPlan`.

## Historical implementation board

The old implementation board, folder instructions, and cutover steps from this file
are intentionally removed rather than left as ambiguous compatibility guidance.
Use the canonical architecture plus current live code/tests for all future work.

Before changing Medusa, LangGraph, CORTEX, Intelligence, Reasoning, RuntimePolicy,
or Runtime, read:

1. `src/ai_karen_engine/core/ARCHITECTURE.md`
2. `tests/architecture/test_import_boundaries.py`
3. `tests/architecture/test_agent_medusa_authority.py`
4. the relevant current Runtime/CORTEX/Reasoning architecture tests

Do not resurrect this retired authority model through a compatibility shim.
