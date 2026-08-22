# AI Karen Engine - Core Domains

`ai_karen_engine.core` is now a package marker and domain namespace, not a public umbrella API.

The old root-level re-export surface has been removed. Import concrete functionality from the preserved subpackages directly.

## Current domain map

### `core/langgraph_orchestrator/`
Graph workflow executor.

Owns:
- LangGraph nodes, contracts, and context helpers
- workflow lifecycle
- human-in-the-loop approval
- checkpoint/resume
- parallel graph execution
- long-running workflow orchestration

### `core/runtime/`
LIVE EXECUTION AUTHORITY.

Owns:
- chat runtime lifecycle
- runtime control plane
- execution decisions
- degraded mode policy
- lazy loading
- resource monitoring
- async task orchestration

### `core/operations/`
Operational support and observability.

Owns:
- health checks
- health monitoring
- metrics
- migration tooling
- routing decision persistence

### `core/services/`
Service governance and service plumbing.

Owns:
- service registry
- service classification
- lifecycle management
- dependency resolution
- plugin registry
- cache helpers
- user preference helpers

### `core/model_runtime/`
Model selection and model-default support.

Owns:
- model defaults
- model selection
- embedding manager
- Milvus client wrapper

### `core/memory/`
Memory and memory-adjacent support.

Owns:
- memory manager
- memory types and protocols
- session buffering
- Zvec API service
- memory config

### `core/cortex/`
Routing and intent intelligence.

Owns:
- intent resolution
- predictor registry
- routing intent helpers
- KIRE/KRO integration
- RBAC validation for CORTEX dispatch

### `core/reasoning/`
Specialist reasoning infrastructure.

Owns:
- soft reasoning
- causal reasoning
- graph reasoning
- retrieval adapters
- synthesis helpers and ICE integration

### `core/security/`
Security-specific configuration and helpers.

### `core/errors/`
Error taxonomy and error handling.

### `core/gateway/`
FastAPI gateway setup and middleware wiring.

### `core/logging/`
Structured logging helpers and formatters.

## Import guidance

Use the concrete module paths instead of `ai_karen_engine.core` re-exports.

Examples:

```python
from ai_karen_engine.core.model_runtime.default_models import load_default_models
from ai_karen_engine.core.services.service_registry import get_service_registry
from ai_karen_engine.core.runtime.chat_runtime_control_plane import ChatRuntimeControlPlane
from ai_karen_engine.core.langgraph_orchestrator import LangGraphOrchestrator
```

Avoid imports like:

```python
from ai_karen_engine.core import default_models
from ai_karen_engine.core import BaseService
```

Those compatibility exports were removed to keep authority boundaries clear.

## Architecture rule

The top-level `core/` package should not become a second runtime.

If a responsibility is part of live chat execution, it belongs in:
- `core/runtime/`

If it is workflow/graph execution, it belongs in:
- `core/langgraph_orchestrator/`

If it is support infrastructure, it belongs in the most specific preserved domain folder.
