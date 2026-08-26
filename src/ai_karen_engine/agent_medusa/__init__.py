"""AgentMedusa, Karen's canonical multi-agent execution runtime.

AgentMedusa owns multi-agent planning, coordination, arbitration, specialist
execution topology, and run trajectories after RuntimePolicy has authorized a
multi-agent plan. It does not own provider/model selection, prompt assembly,
memory persistence, extension execution, authentication, or global policy.
"""

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
from .coordinator import MedusaCoordinator
from .arbitration import MedusaArbitrator
from .planning import MedusaPlanner
from .execution import ExecutionEngine, ExecutionPolicy
from .telemetry import RuntimeTelemetry
from .adapters import (
    AuthContextAdapter,
    ExtensionRuntimeAdapter,
    MemoryRuntimeAdapter,
    PersistenceAdapter,
)

__version__ = "0.2.0"
__author__ = "AI-Karen Team"

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
