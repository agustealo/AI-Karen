# Architecture Authority

> Canonical architecture reference for AI KAREN.

## 1. Purpose

This document defines which subsystem is allowed to own which decision or side effect. It exists to prevent duplicate runtimes, registries, policy engines, prompt builders, provider routers, memory stores, and observability stacks.

## 2. Authority chain

```text
Transport/API
   -> ChatRuntime
      -> context + recall coordination
      -> CORTEX/RuntimePolicy decisions
      -> prompt assembly
      -> execution topology
          -> direct model
          -> reasoning
          -> LangGraph
          -> AgentMedusa
          -> governed action/tool/extension
      -> persistence
      -> telemetry/audit
```

### API routes

**Own:** HTTP validation, auth/session/tenant context, request/correlation IDs, delegation, HTTP error translation.

**Do not own:** provider choice, prompt building, recall, fallback logic, plugin execution, model orchestration.

### ChatRuntime

**Own:** normalized request execution, context assembly, recall coordination, policy consumption, prompt assembly coordination, execution selection, streaming/response lifecycle, persistence, degradation metadata, telemetry/audit.

The runtime executes decisions. It should not duplicate CORTEX classification/policy rules internally unless a runtime safety invariant requires enforcement.

### CORTEX

**Own:** cognitive/intent/policy decision signals and execution eligibility.

**Does not execute:** providers, agents, tools, extensions, memory writes.

### Provider/model runtime

**Own:** provider availability, model inventory, provider execution, model/provider health, actual provider/model selection under runtime policy, fallback execution metadata.

The UI and routes consume this truth; they do not maintain alternate inventories.

### Prompt runtime

**Own:** prompt registry, prompt contracts, deterministic assembly, system/persona/profile/task/memory/tool/provider-capability merge, token budget and output contract.

### Reasoning

**Own:** cognitive/reasoning contracts and reasoning execution utilities that are independent of provider-specific wiring.

Reasoning must remain compatible with runtime-selected model clients instead of choosing providers itself.

### LangGraph

**Own:** graph workflows that truly require graph state, branching, checkpoint/resume, or human approval nodes.

It is not the default chat runtime.

### AgentMedusa

**Own:** multi-agent planning, specialist coordination, dependency-aware execution, selective arbitration, concurrency/budget lifecycle, trajectory assembly.

Medusa consumes canonical runtime/provider/prompt/security ports rather than reimplementing them.

### Memory

**Own:** memory domain semantics and persistence/retrieval contracts.

NeuroRecall selects/ranks recall. NeuroVault governs durability/recovery/deletion. Neither is an alternate memory database.

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

Application composition coordinates startup/shutdown; it does not become a business-runtime owner.

## 4. Data plane vs application plane

```text
Frontend
  -> KAREN application/API runtime
      -> ChatRuntime / CORTEX / providers / memory / Medusa / extensions
          -> Supabase/PostgreSQL, Redis, object storage, external providers
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

## 6. Transitional code rules

A compatibility shim must:

1. name its canonical replacement;
2. contain no new domain logic;
3. avoid creating new state/registries;
4. have a removal condition;
5. be covered by an architecture test when important.

A migration is not complete while both old and new code remain active authorities.

## 7. Change checklist

For every architecture change:

- identify current owner;
- search all references before adding/replacing;
- classify duplicate implementations;
- preserve security/tenant/audit behavior;
- preserve observable metadata;
- migrate consumers;
- delete dead code;
- add architecture tests preventing resurrection.
