# AI Karen Engine - Core Domains

`ai_karen_engine.core` is a package marker and domain namespace, not a public umbrella API.

Import concrete functionality from the owning subpackage. Core must not become a second runtime, platform layer, provider layer, or application layer.

## Canonical live domains

### `core/runtime/`
LIVE CHAT EXECUTION AUTHORITY.

Owns:
- request normalization and runtime control flow
- execution requirements and authorized execution plans
- chat execution lifecycle
- provider-runtime delegation
- prompt-runtime delegation
- memory recall coordination
- request-context assembly
- service resolution/lifecycle coordination
- degraded-mode/runtime metadata
- persistence and telemetry coordination

### `core/ai_runtime/`
CORE CAPABILITY AUTHORITY.

Owns:
- capability identifiers and definitions
- capability registry
- capability lookup/status contracts
- capability request/attempt/result contracts
- default core capability registration

It does not select providers or execute models.

### `core/intelligence/`
INTELLIGENCE AUTHORITY.

Owns:
- `IntelligenceRuntime`
- linguistic intelligence
- ML-backed intelligence capabilities
- feature extraction
- task-signature construction

### `core/cognitive/`
Canonical cognitive state and cognitive-domain types.

### `core/contracts/`
Cross-cutting Core contracts that have one canonical authority, including cognitive and learning contracts. Compatibility contracts must have explicit migration/sunset intent.

### `core/cortex/`
DECISION LAYER.

Owns:
- intent resolution
- routing/execution decisions
- policy gates and reasoning hints
- memory/plugin/agent routing decisions

CORTEX decides; runtime executes.

### `core/expression/`
Provider-neutral expression/execution gateway contracts and engines.

It must not become a second provider router, RuntimePolicy implementation, personalization authority, prompt registry, or observability authority.

### `core/langgraph_orchestrator/`
Graph workflow executor for true graph-shaped work only.

Owns:
- LangGraph nodes, contracts, and context helpers
- workflow lifecycle
- human-in-the-loop approval
- checkpoint/resume
- parallel graph execution
- long-running workflow orchestration

Simple chat does not belong here.

### `core/personalization/`
USER/PERSONALIZATION MODEL AUTHORITY.

Owns:
- user preferences and preference evidence
- behavior patterns and drift
- user goals
- user/self/relationship model contracts
- communication and interaction preferences
- personalization snapshots and evaluation
- personalization-domain persistence ports/adapters

Personalization models the user and the Karen-user relationship. It does not own prompt construction, raw system prompts, memory storage, provider/model routing, agent execution, or UI visibility policy.

Assistant identity/profile defaults, if a live consumer requires them, must be represented as small versioned references/contracts that compose through the canonical PromptRuntime and personalization paths. Do not recreate a top-level Persona runtime, service, registry, store, or preference system.

### `core/services/`
Core-facing service helpers only.

Owns:
- base service primitives
- lightweight dependency-injection container helpers
- FastAPI dependency adapters that resolve through canonical Runtime service loading

It does not own a service registry, service classification runtime, health-monitoring registry, startup optimizer, or service lifecycle authority. Those duplicate registries/lifecycle managers were retired after reference audit. Runtime remains authoritative for live service resolution and lifecycle coordination.

### `core/model_runtime/`
Model-runtime support.

Owns model defaults/selection support and model-adjacent helpers. Provider execution authority belongs to the canonical runtime/provider path.

### `core/memory/`
Memory contracts and memory-adjacent runtime support.

Storage authority remains layered outside ad-hoc Core helpers; NeuroRecall coordinates retrieval rather than becoming a duplicate store.

### `core/reasoning/`
Specialist reasoning infrastructure.

Owns reusable reasoning primitives such as causal/graph/retrieval/synthesis helpers. It must not become a duplicate chat orchestrator.

### `core/security/`
Security-specific Core contracts/configuration/helpers.

### `core/errors/`
Error taxonomy and safe Core error contracts.

### `core/gateway/`
Gateway setup and middleware plumbing only. API/business orchestration does not belong here.

### `core/logging/`
Structured logging helpers and formatters.

## Transitional / non-runtime domains

### `core/adaptive/`
Shadow-mode adaptive recommendation subsystem under consolidation review.

It recommends only. It does not authorize or execute. New execution authority must not be added here. Useful learning/ranking behavior should converge on the canonical Intelligence/CORTEX/RuntimePolicy boundaries rather than creating a parallel decision runtime.

## Removed / nonexistent domains

`core/operations/` is not a live directory and must not be treated as an authority. Operational infrastructure belongs to explicit platform/runtime owners.

`core/cron/` was removed after a repository-wide reference audit found no imports, registry consumers, scheduler wiring, tests, or concrete job-name references. If scheduling is implemented later, it belongs to an explicit platform/database scheduling owner rather than Core.

`core/context/` was removed after a repository-wide reference audit found no imports or consumers of its exported context-plan types. The package also contained its own scoring and selection behavior, which would compete with canonical runtime context assembly if activated. Request context assembly belongs to `core/runtime/`; reusable cross-cutting context contracts belong only in the canonical contract owner when a live consumer requires them.

`core/automation/` was removed after a repository-wide reference audit found no imports or consumers of its automation and flow types. Its single contracts module mixed automation records with legacy flow orchestration, tool selection, memory, persona, Gmail, and weather schemas. Future automation belongs to an explicit automation/application or platform owner and must delegate agent/runtime execution through canonical runtime policy rather than recreating orchestration under Core.

`core/persona/` was removed after a fresh repository-wide symbol and package reference audit found no live consumers. Its orphaned contract mixed hardcoded system prompts, user preference state, memory weighting and duplicate memory-entry types, request-context resolution, and UI selector flags. Those responsibilities already have canonical owners: user preferences and relationship modeling belong to `core/personalization/`; prompt text and instruction assembly belong to PromptRuntime/PromptRegistry; memory belongs to `core/memory/`; agent specialization belongs to AgentMedusa; UI visibility belongs to frontend/backend capability configuration. If assistant identity/profile selection later gains a live consumer, add only the minimum versioned reference/definition contract under an existing canonical owner rather than recreating `core/persona/` as a runtime authority.

`core/observability/` was removed after all known callers had migrated and a fresh reference audit found no remaining package-path consumers. Canonical observability contracts and implementation live in `platform/observability/`. Core must not recreate metrics, sinks, exporters, telemetry buffers, event implementations, redaction implementations, regression detection, or observability tests under a second authority.

The legacy Core service registry stack was removed after reference audit and migration of `core/services/dependencies.py` to Runtime lazy loading. Removed files include `registry.py`, `service_registry.py`, `classified_service_registry.py`, `service_classification.py`, and `service_lifecycle_manager.py`. Required services now fail honestly when unavailable instead of returning dummy service/metric success.

## Import guidance

Use concrete owner paths instead of root-level Core re-exports.

Examples:

```python
from ai_karen_engine.core.ai_runtime import get_capability_registry
from ai_karen_engine.core.intelligence import IntelligenceRuntime
from ai_karen_engine.core.runtime.chat_runtime_control_plane import ChatRuntimeControlPlane
from ai_karen_engine.core.langgraph_orchestrator import LangGraphOrchestrator
from ai_karen_engine.platform.observability import get_correlation_context
```

Avoid:

```python
from ai_karen_engine.core import BaseService
from ai_karen_engine.core.observability import MetricsCollector
from ai_karen_engine.core.persona.contracts import Persona
from ai_karen_engine.core.services.service_registry import get_service_registry
```

## Architecture rules

- Live chat execution, request-context assembly, and Core service resolution/lifecycle coordination belong to `core/runtime/`.
- Capability identity belongs to `core/ai_runtime/`.
- AI/ML intelligence belongs to `core/intelligence/`.
- User preferences, user models, goals, behavior, and relationship personalization belong to `core/personalization/`.
- Prompt text/versioning and effective instruction assembly belong to the canonical PromptRuntime/PromptRegistry path, not persona/profile objects.
- Memory state and recall belong to `core/memory/`; profile/persona objects must not define parallel memory entries or storage behavior.
- Agent specialization, tools, permissions, execution budgets, and delegation belong to AgentMedusa/runtime policy, not assistant profiles.
- CORTEX decides; runtime executes.
- LangGraph is only for true graph workflows.
- Platform infrastructure, including observability implementations and future scheduling infrastructure, belongs under `platform/` or another explicit infrastructure owner.
- Automation must not recreate provider routing, prompt assembly, memory ownership, plugin execution, or agent orchestration under Core.
- Do not add a second service registry or lifecycle manager under `core/services/`.
- Do not recreate `core/persona/`, PersonaRuntime, PersonaService, PersonaStore, or a second personalization authority without a proven live responsibility that cannot fit an existing owner.
- Search before adding a new Core folder, registry, runtime, service, or helper.
- One responsibility -> one owner -> one registry/config/runtime path.
