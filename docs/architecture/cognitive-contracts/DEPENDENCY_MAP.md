# Dependency Direction Map

Target architecture:

```text
Memory ─────┐
Goals ──────┤
User Model ─┤
Belief ─────┤
Salience ───┤
            ▼
          Context
            ▼
         Reasoning
            ▼
           Meta
            ▼
         Adaptive
            ▼
          CORTEX
```

## Observed dependency edges

| Source package | Target package | Edge count | Notes |
| -------------- | -------------- | ---------- | ----- |
| adaptive       | context        | 2          | Reverse dependency: adaptive imports context (allowed for context assembly) |
| cortex         | reasoning      | 1+         | Expected: cortex consumes canonical reasoning contracts |
| adaptive/drift | adaptive/learning | 1       | Expected: drift monitors learning policies |

## Cycles

**None detected** at the package level across the cognitive subsystem boundaries.

## Reverse dependencies

| Source | Target | File | Reason |
| ------ | ------ | ---- | ------ |
| adaptive | context | adaptive/runtime.py | Context assembly for adaptive ranking |

**Flag:** `REVERSE_DEPENDENCY` — adaptive imports `ai_karen_engine.core.observability.context` and `ai_karen_engine.core.adaptive.context`. The observability import is a provider/platform leak inside adaptive runtime.

## Implementation imports from contract files

**None detected** — contract files in the cognitive packages do not import implementation modules from other cognitive packages.

## Forbidden imports found in cognitive packages

The following forbidden provider/platform imports were found inside the cognitive directories. These are **not** in pure contract files, but in implementation modules that should be isolated behind provider boundaries.

| File | Forbidden module |
| ---- | ---------------- |
| memory/agent_memory_service.py | requests |
| memory/chat_memory_config.py | requests |
| memory/memory_runtime_manager.py | sqlalchemy, requests |
| memory/protocols.py | openai |
| memory/unified_memory_service.py | sqlalchemy |
| memory/profile_synthesis/profile_manager.py | openai, requests |
| memory/profile_synthesis/profile_service.py | sqlalchemy |
| memory/signals/nlp_health_monitor.py | openai |
| memory/signals/nlp_service_manager.py | ollama |
| neuro_recall/client/agent.py | openai, ollama, vllm |
| neuro_recall/client/agent_local_server.py | openai, ollama |
| neuro_recall/client/no_parametric_cbr.py | openai, ollama, vllm |
| reasoning/executor.py | requests |
| reasoning/kro_orchestrator.py | vllm, requests |
| reasoning/synthesis/ice_wrapper.py | requests |
| adaptive/candidates/catalog.py | ollama, vllm |
| cortex/kire_kro_integration.py | requests |
| cortex/rbac_validator.py | requests |
| cortex/analysis/spacy_analyzer.py | requests |

## Flagged issues

| Flag | Location | Description |
| ---- | -------- | ----------- |
| PROVIDER_LEAK | memory/signals/nlp_service_manager.py | Imports ollama client inside cognitive memory |
| PROVIDER_LEAK | neuro_recall/client/*.py | Imports openai/ollama/vllm in labs client (expected for labs, but should be behind provider boundary) |
| PLATFORM_LEAK | memory/memory_runtime_manager.py | Imports sqlalchemy inside cognitive memory runtime |
| PLATFORM_LEAK | memory/unified_memory_service.py | Imports sqlalchemy inside cognitive memory |
| REVERSE_DEPENDENCY | adaptive/runtime.py | adaptive imports observability.context |
