# Architecture Authority

> Canonical architecture reference for AI KAREN.

## 1. Purpose

This document defines which subsystem is allowed to own which decision or side effect. It exists to prevent duplicate runtimes, registries, policy engines, prompt builders, provider routers, memory stores, reasoning orchestrators, and observability stacks.

## 2. Canonical authority chain

```text
Transport/API
   -> ChatRuntime
      -> normalize request/context
      -> CORTEX cognitive decision
      -> RuntimePolicy authorization
      -> AuthorizedExecutionPlan
      -> recall/prompt/execution composition
          -> direct model
          -> reasoning
              -> causal / verification / refinement / metacognition
              -> Soft Reasoning / soft_exploration when explicitly authorized
          -> LangGraph
          -> AgentMedusa
          -> governed action/tool/extension
      -> memory formation / NeuroVault persistence
      -> telemetry/audit
```

CORTEX decides what cognition is desirable. RuntimePolicy decides what is authorized. Runtime executes the resulting plan. No lower layer may broaden either decision.

### API routes

**Own:** HTTP validation, auth/session/tenant context, request/correlation IDs, delegation, HTTP error translation.

**Do not own:** provider choice, prompt building, recall, fallback logic, plugin execution, model orchestration.

### ChatRuntime

**Own:** normalized request execution, context assembly, recall coordination, policy invocation/consumption, prompt assembly coordination, execution selection, streaming/response lifecycle, persistence coordination, degradation metadata, telemetry/audit.

Runtime is the lifecycle owner, not a second cognitive head. It may enforce safety/executability invariants but must not invent intent, reasoning modes, recall policy, or workflow semantics.

### CORTEX

**Own:** cognitive interpretation and typed execution recommendations: intent, reasoning desirability, recall desirability/scope hints, verification needs, tool/agent/workflow eligibility signals, risk signals, and cognitive budgets.

**Does not execute:** RuntimePolicy, providers, agents, tools, extensions, memory writes, LangGraph, or AgentMedusa.

Target contract:

```text
TaskSignature / cognitive state
    -> CORTEX
    -> CortexDecision
    -> RuntimePolicy
```

### RuntimePolicy

**Own:** authorization over requested capabilities, reasoning modes, provider/resource constraints, tools/actions, side effects, risk restrictions, tenant/user permissions, and execution budgets.

Reasoning modes are a first-class authorization domain, not an opaque field inside generic topology metadata.

Target contract:

```text
requested_reasoning_modes
    -> RuntimePolicy
    -> allowed_reasoning_modes
    -> denied_reasoning_modes + reason codes
```

An empty reasoning request remains empty. RuntimePolicy must not invent a default reasoning mode.

### Provider/model runtime

**Own:** provider availability, model inventory, provider execution, model/provider health, actual provider/model selection under runtime policy, fallback execution metadata.

The UI and routes consume this truth; they do not maintain alternate inventories.

### Prompt runtime

**Own:** prompt registry, prompt contracts, deterministic assembly, system/persona/profile/task/memory/tool/provider-capability merge, token budget and output contract.

### Reasoning

**Own:** provider-independent reasoning contracts and governed reasoning execution.

Canonical reasoning modes include causal reasoning, counterfactual reasoning, evidence synthesis, hypothesis comparison, verification, refinement, metacognition, and `soft_exploration`.

Reasoning must consume runtime-selected model/runtime capabilities instead of choosing providers itself.

### Soft Reasoning

The term **Soft Reasoning** is reserved for the research-derived `soft_exploration` reasoning strategy based on first-token embedding intervention, latent search, verifier feedback, and Bayesian optimization.

Soft Reasoning is **not** a memory-retrieval subsystem.

Semantic search, lexical retrieval, graph expansion, recency, novelty/retrieval-gap scoring, and source-local candidate generation are called **recall primitives** and live below NeuroRecall.

### NeuroRecall

**Own:** authorized recall candidate governance, source coordination, fusion, deduplication, guardrails, ranking, selection, and recall disposition.

**Does not own:** durable storage, provider execution, prompt assembly, final synthesis, global policy, or general reasoning strategy.

### LangGraph

**Own:** workflows that truly require graph state, branching, checkpoint/resume, multi-step tool chains, or human approval nodes.

Complexity alone is not graph semantics. A difficult conceptual question may need deep reasoning while remaining a non-workflow request.

LangGraph is not the default chat runtime or a cognitive head.

### AgentMedusa

**Own:** multi-agent planning, specialist coordination, dependency-aware execution, selective arbitration, concurrency/budget lifecycle, trajectory assembly.

Medusa consumes canonical runtime/provider/prompt/security ports rather than reimplementing them.

### Memory

**Own:** memory-domain semantics and formation/retrieval contracts.

NeuroRecall selects/ranks recall. MemoryFormation creates governed candidate observations. NeuroVault governs durable mutation, recovery, lifecycle, and deletion. None of these is an alternate global runtime.

Memory reads and writes are independent policy decisions. Recall must not be used as an implicit prerequisite for authorized persistence.

### NeuroVault

**Own:** governed durable memory mutations and lifecycle operations.

CORTEX, reasoning engines, NeuroRecall, routes, tools, and agents may emit observations/candidates but may not bypass NeuroVault for durable writes.

### Extensions

**Own:** extension manifests, registration, lifecycle, governed action execution adapters, schemas, declared capability/permission metadata.

Global authorization remains runtime/policy/RBAC authority.

### Platform observability

**Own:** telemetry contracts, events, metrics, correlation context, redaction, diagnostics adapters.

Subsystems emit through this platform rather than creating parallel metric/logging systems.

## 3. Application composition

Supported process target:

```text
ai_karen_engine.app:create_app
```

Launch scripts and Docker must use the canonical ASGI entrypoint. Root-level `server/` code is transitional until each live responsibility has been migrated and reference-audited.

Application/runtime composition is the construction authority for stateful canonical collaborators. Compatibility getters may temporarily resolve through that composition graph, but subsystem constructors must not silently instantiate alternate policy engines, memory runtimes, recall authorities, model registries, reasoning runtimes, or workflow orchestrators.

Target composition includes:

```text
CORTEX
RuntimePolicy
PromptRuntime
provider/model runtime
ReasoningBridge
WorkflowRuntime
MemoryRuntimeManager
NeuroRecall source graph
MemoryFormation / NeuroVault adapters
observability
trajectory/outcome recorders
ExpressionGateway
```

Application composition coordinates startup/shutdown; it does not become a business-runtime owner.

## 4. Data plane vs application plane

```text
Frontend
  -> KAREN application/API runtime
      -> ChatRuntime / CORTEX / RuntimePolicy / providers / memory / Medusa / extensions
          -> Supabase/PostgreSQL, Redis STM, object storage, external providers
```

Supabase is a managed data platform, not KAREN's runtime orchestrator.

Production database schema changes are migration/CI concerns, not automatic API-startup behavior.

## 5. Local-first provider architecture

Provider selection is policy/config driven. A local OpenAI-compatible endpoint may represent vLLM or another compatible server. KAREN must not create engine-specific special cases where a standard provider interface is sufficient.

Forbidden architecture:

- `builtin_vllm`;
- route-selected providers;
- UI-maintained model availability;
- silent fake provider responses;
- provider-specific prompt authority;
- fallback order duplicated across modules.

## 6. Research-derived capability rule

Research mechanisms are capabilities beneath existing owners, not reasons to create new global orchestrators.

For test-time scaling/reasoning methods, record the inference protocol and its actual model-call/token/latency budget. `reasoning_depth=deep` is not an adequate description of Soft Reasoning, parallel sampling, sequential revision, or verifier-guided search.

For memory research, preserve the write-manage-read separation: formation/write governance, memory management/selection, and recall should remain separately testable authorities.

See `docs/development/ARCH_AUTH_02.md` for the current research-guided convergence program.

## 7. Transitional code rules

A compatibility shim must:

1. name its canonical replacement;
2. contain no new domain logic;
3. avoid creating new state/registries;
4. have a removal condition;
5. be covered by an architecture test when important.

A migration is not complete while both old and new code remain active authorities.

## 8. Change checklist

For every architecture change:

- identify current owner;
- search all references before adding/replacing;
- classify duplicate implementations;
- preserve security/tenant/audit behavior;
- preserve observable metadata;
- migrate consumers;
- delete dead code;
- add architecture tests preventing resurrection;
- verify terminology has one meaning across code and docs;
- verify requested cognition, policy authorization, and runtime execution remain separate typed stages.
