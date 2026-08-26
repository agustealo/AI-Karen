# AI KAREN Context Runtime Architecture

Status: Canonical as of CONTEXT-CONVERGE-1

## Purpose

This document defines who owns request-time context in AI KAREN, how context reaches model input, and which boundaries must not regain authority.

The governing rule is:

> One responsibility -> one owner -> one runtime path.

Context is not a standalone orchestration subsystem. Runtime coordinates trusted inputs, PromptRuntime owns final prompt assembly and token pressure, domain services own ranking and retrieval, and provider execution consumes the resulting model input without rebuilding context.

## Canonical Context Flow

```text
Authenticated request
    |
    v
Runtime / LangGraph workflow state
    |-- conversation messages
    |-- tenant + user/session scope
    |-- profile/persona inputs
    |-- memory recall results
    |-- CORTEX intent/routing hints
    |-- workflow/tool/reasoning state
    |
    v
PromptRuntimeService.build_request_from_runtime_context()
    |
    v
PromptAssemblyRequest
    |-- system_policy / tenant_policy
    |-- system_instructions
    |-- persona / profile
    |-- cortex_intent
    |-- memory_items
    |-- messages
    |-- tool_contracts
    |-- workflow_context
    |-- provider_capabilities
    |
    v
HierarchicalTruncationPolicy
    |
    |  deterministic cross-section token pressure
    |  latest user message + protected policy survive
    |  domain ordering is preserved
    |  omissions produce provenance
    v
PromptAssembler
    |
    |-- canonical messages
    |-- prompt hash
    |-- included memory/tool refs
    |-- truncation events + context-policy metadata
    v
ProviderRuntime / LLMRouter
    |
    |  consumes PromptRuntime-produced prompt_text/messages
    |  does not choose context, recall memory, or rebuild prompts
    v
Model transport
```

## Ownership

### Runtime

Runtime owns request orchestration and decides when context-producing services execute. It is responsible for preserving authenticated tenant/user/session scope and for handing trusted inputs to PromptRuntime.

Runtime may coordinate:

- conversation history
- profile/persona data
- memory recall
- CORTEX intent and policy output
- workflow, reasoning, and tool state
- provider capability metadata

Runtime must not implement a second prompt budget or formatting policy.

### PromptRuntime

`src/ai_karen_engine/core/runtime/prompt/`

PromptRuntime is the canonical final model-input authority.

It owns:

- normalization into `PromptAssemblyRequest`
- exact duplicate suppression where appropriate
- cross-section token pressure
- protected-section behavior
- truncation provenance
- final message serialization
- deterministic prompt hashing
- plain-text rendering for transports that do not accept structured chat messages

PromptRuntime does **not** own:

- provider selection
- memory retrieval/scoring
- RBAC decisions
- tenant authorization
- tool execution
- inference
- persistence

### Memory Domain

Memory owners rank and authorize memory before it reaches PromptRuntime.

PromptRuntime must preserve that ranking. It may trim the tail under token pressure, but it must not invent an alternate relevance score.

The active mapping is:

| Runtime input | PromptRuntime field |
| --- | --- |
| User/project facts | `profile` |
| Episodic, semantic, recalled memory | `memory_items` |
| Active instructions | `system_instructions` |
| CORTEX intent | `cortex_intent` |
| Conversation | `messages` |
| Plan/tool/reasoning state | `workflow_context` |

### CORTEX

CORTEX decides intent, policy gates, routing eligibility, reasoning hints, and memory/plugin routing. It does not serialize the final model prompt.

### LangGraph

LangGraph is orchestration only for graph-shaped workflows.

LangGraph nodes must consume Runtime/PromptRuntime contracts. They must not own a parallel context-selection policy.

`ResponseSynthesisNode` currently converts graph state into a canonical PromptRuntime request, assembles the prompt, and hands the produced model input to ProviderRuntime.

### ProviderRuntime and LLMRouter

Provider execution consumes PromptRuntime-produced model input. It must not:

- rebuild conversation context
- choose memory
- impose arbitrary context limits
- reconstruct system/persona/profile sections

For plain-text transports, PromptRuntime renders the canonical assembled messages into `prompt_text`. Provider execution honors that text directly.

## Token Budget Authority

There is one cross-section budget path:

```text
PromptRuntimeService
    -> PromptRegistry.estimate_tokens()
    -> HierarchicalTruncationPolicy
    -> PromptAssembler
```

`PromptRegistry.enforce_token_budget()` was retired because it duplicated active PromptRuntime policy and had no callers.

`chat_helpers.py` must not regain hardcoded context limits such as fixed counts for user facts, project facts, episodic memory, recalled items, or instructions.

Domain services may impose domain-specific retrieval limits for legitimate retrieval reasons, but final prompt pressure belongs to PromptRuntime.

## Removed `structured_sections` Path

The old `structured_sections` path was removed because it was not a real model-input authority.

Previously:

```text
MemoryFetchNode
    -> build_structured_context_sections()
    -> memory_context["structured_sections"]
    -> ResponseSynthesisNode context blob
    -> provider prompt builder
    -> discarded / rebuilt from latest user message
```

That produced formatting work without reliable model consumption and created a shadow context policy in `chat_helpers.py`.

The replacement is direct mapping into `PromptAssemblyRequest` followed by canonical PromptRuntime assembly.

## Conversational Context vs File Context

These are separate responsibilities.

### Conversational context

`ContextManager` has been retired. `MemoryFetchNode` receives the canonical memory service from the LangGraph composition root and writes the retrieved tenant-scoped memory envelope into graph state.

Current path:

```text
LangGraphOrchestrator
    -> injected/lazy canonical WebUIMemoryService
    -> MemoryFetchNode
    -> tenant-scoped memory context
    -> graph state
    -> PromptRuntime
```

The node does not own retrieval policy or final prompt assembly.

### File-upload context

File-upload metadata is owned separately by:

`src/ai_karen_engine/core/langgraph_orchestrator/context/file_context_store.py`

The file-specific compatibility store owns:

- `ContextFile`
- `FileUploadStatus`
- `FileContextData`
- `FileContextUpdateRequest`
- `FileContextStore`

It must not evolve into another general context manager.

File contents or extracted text only become model context after an authorized runtime path deliberately selects them and passes them through PromptRuntime.

## Tenant and Security Boundary

Context assembly must never weaken authenticated scope.

Required invariants:

1. Tenant identity is derived from authenticated runtime context, not arbitrary prompt payload.
2. Cross-tenant memory retrieval is denied by memory-domain policy before prompt assembly.
3. PromptRuntime consumes trusted/authorized inputs and does not authorize them itself.
4. Tool/plugin context is included only after Runtime/CORTEX permission checks.
5. Prompt metadata must not expose secrets.
6. Provider fallbacks may change execution transport, not context authorization semantics.

## Observability

Context behavior should remain observable through existing runtime telemetry and PromptRuntime metadata.

Important fields include:

- `correlation_id`
- `request_id`
- `tenant_id`
- `user_id`
- `session_id`
- `conversation_id`
- `intent`
- `memory_recall_count`
- `provider`
- `model`
- `runtime_engine`
- `prompt_hash`
- initial/final token estimates
- token budget
- truncation count/events
- degraded/fallback metadata

PromptRuntime truncation events are the canonical explanation for prompt omissions caused by token pressure.

## Forbidden Regressions

Do not add or restore:

- `structured_sections`
- `build_structured_context_sections()`
- hardcoded cross-domain context caps in `chat_helpers.py`
- another `ContextManager` or generic context service
- route-level context assembly
- provider-level memory selection
- provider-level prompt reconstruction
- duplicate token-budget enforcement
- file-upload state inside conversational context management
- LangGraph-specific prompt policy that bypasses PromptRuntime

## Tests and Proof

The permanent gate is:

`.github/workflows/context-authority-contract.yml`

Key proof includes:

- `tests/architecture/test_context_authority_convergence.py`
- `tests/architecture/test_context_langgraph_consumption.py`
- import proof for `FileUploadService` / `FileContextStore`
- compilation of PromptRuntime, provider, LangGraph, and file-context boundaries
- Beta Real Model Proof for model-facing runtime continuity

Useful local commands:

```bash
python -m compileall src
pytest tests/architecture/test_context_authority_convergence.py -q
pytest tests/architecture/test_context_langgraph_consumption.py -q
ruff check src tests
mypy src
```

## Remaining Intentional Debt

### 1. Classify memory-domain retrieval shaping

`MemoryContextBuilder` still applies a memory-domain retrieval/context cap before PromptRuntime. This must be explicitly classified as retrieval shaping versus duplicate final-prompt budgeting before changing it. PromptRuntime remains the final cross-section token authority.

### 2. Decide the future of `FileContextStore`

`FileContextStore` is process-local compatibility state. It is separated correctly, but production behavior still needs an explicit decision:

- make file metadata durable through an existing canonical persistence layer, or
- retire this subsystem if uploads are handled elsewhere.

Do not silently turn this compatibility store into a new persistence authority.

### 3. Remove duplicated runtime-context adapters

`context_manager_adapter.py` still combines memory-service resolution, session continuity, message serialization helpers, and runtime-context projection. Those responsibilities should be audited and split/reused through existing runtime ports rather than growing the adapter.

## Architectural End State

The desired end state is deliberately boring:

```text
Domain services produce trusted ranked data
              |
              v
           Runtime
              |
              v
        PromptRuntime
              |
              v
       ProviderRuntime
              |
              v
            Model
```

No shadow context brain. No arbitrary helper caps. No provider prompt reconstruction. No file state mixed with conversation state.

Protect architecture. Use the existing source of truth. Collapse duplicates. Keep Runtime authoritative and PromptRuntime canonical for final model input.
