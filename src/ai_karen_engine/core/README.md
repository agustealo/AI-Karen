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

It must not become a second provider router, RuntimePolicy implementation, or observability authority.

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

### `core/services/`
Service governance and service plumbing.

Owns:
- service registry/lifecycle infrastructure
- service classification
- dependency resolution
- shared service-container helpers

This domain is under DRY review. New registries must not be added when an existing canonical registry can be extended.

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

### `core/automation/`
Automation domain contracts only. This folder is not an automation execution runtime.

### `core/context/`
Context contracts only. Live request context assembly belongs to the owning runtime boundary.

### `core/observability/`
LEGACY / TRANSITIONAL COMPATIBILITY SURFACE.

Canonical observability implementation now lives in:

```text
src/ai_karen_engine/platform/observability/
```

Do not add new metrics, sinks, exporters, diagnostics buffers, event implementations, or telemetry infrastructure under `core/observability/`. Existing callers must migrate to the platform observability contracts/implementation before legacy Core observability modules are deleted.

## Removed / nonexistent domains

`core/operations/` is not a live directory and must not be treated as an authority. Operational infrastructure belongs to explicit platform/runtime owners.

`core/cron/` was removed after a repository-wide reference audit found no imports, registry consumers, scheduler wiring, tests, or concrete job-name references. If scheduling is implemented later, it belongs to an explicit platform/database scheduling owner rather than Core.

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
```

## Architecture rules

- Live chat execution belongs to `core/runtime/`.
- Capability identity belongs to `core/ai_runtime/`.
- AI/ML intelligence belongs to `core/intelligence/`.
- CORTEX decides; runtime executes.
- LangGraph is only for true graph workflows.
- Platform infrastructure, including observability implementations and future scheduling infrastructure, belongs under `platform/` or another explicit infrastructure owner.
- Search before adding a new Core folder, registry, runtime, service, or helper.
- One responsibility -> one owner -> one registry/config/runtime path.
