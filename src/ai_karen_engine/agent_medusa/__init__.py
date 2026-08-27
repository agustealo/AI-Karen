"""AgentMedusa, Karen's canonical multi-agent execution runtime.

AgentMedusa owns multi-agent planning, coordination, arbitration, specialist
execution topology, and run trajectories after RuntimePolicy has authorized a
multi-agent plan. It does not own provider/model selection, prompt assembly,
memory persistence, extension execution, authentication, or global policy.

Runtime-heavy exports are resolved lazily so importing a narrow Medusa contract
or execution utility does not pull API/framework dependencies into the process.
The public package API remains backward compatible.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .contracts import (
    AgentDefinition,
    AgentLifecycleState,
    AgentRegistration,
    ArbitrationDecision,
    ArbitrationRequest,
    DeepExecutionPlan,
    ExecutionAction,
    MedusaRuntimePolicy,
    RuntimeRequest,
    RuntimeResponse,
    SubagentContract,
)

__version__ = "0.2.0"
__author__ = "AI-Karen Team"

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "MedusaCoordinator": (".coordinator", "MedusaCoordinator"),
    "MedusaArbitrator": (".arbitration", "MedusaArbitrator"),
    "MedusaPlanner": (".planning", "MedusaPlanner"),
    "ExecutionEngine": (".execution", "ExecutionEngine"),
    "ExecutionPolicy": (".execution", "ExecutionPolicy"),
    "RuntimeTelemetry": (".telemetry", "RuntimeTelemetry"),
    "AuthContextAdapter": (".adapters", "AuthContextAdapter"),
    "ExtensionRuntimeAdapter": (".adapters", "ExtensionRuntimeAdapter"),
    "MemoryRuntimeAdapter": (".adapters", "MemoryRuntimeAdapter"),
    "PersistenceAdapter": (".adapters", "PersistenceAdapter"),
}


def __getattr__(name: str) -> Any:
    """Resolve runtime-heavy public exports only when callers request them."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    # Definition/runtime contracts
    "AgentDefinition",
    "AgentLifecycleState",
    "AgentRegistration",
    "RuntimeRequest",
    "RuntimeResponse",
    "ExecutionAction",
    "MedusaRuntimePolicy",
    "ArbitrationRequest",
    "ArbitrationDecision",
    "SubagentContract",
    "DeepExecutionPlan",
    # Multi-agent coordination
    "MedusaCoordinator",
    "MedusaArbitrator",
    "MedusaPlanner",
    # Execution
    "ExecutionEngine",
    "ExecutionPolicy",
    # Telemetry adapter surface
    "RuntimeTelemetry",
    # Canonical runtime adapters
    "AuthContextAdapter",
    "ExtensionRuntimeAdapter",
    "MemoryRuntimeAdapter",
    "PersistenceAdapter",
]
