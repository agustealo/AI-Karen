from __future__ import annotations

"""CORTEX cognitive authority and contract exports.

Canonical live chat cognition enters through ``CortexExecutionDecider`` in this
package. IntelligenceRuntime supplies signals, RuntimePolicy authorizes requested
capabilities, and Runtime executes the resulting decision.

Legacy dispatch/orchestration names remain available through ``__getattr__`` for
import compatibility, but they are deliberately excluded from ``__all__`` so
new code does not treat them as first-class execution authorities.
"""

from importlib import import_module

from ai_karen_engine.core.cortex.contracts import (
    CorrelationIdFactory,
    CortexOutput,
    ExecutionMode,
    IntentEngine,
    IntentSignal,
    KireEngine,
    KireSignal,
    PredictorEngine,
    PredictorSignal,
    ReasoningDepth,
    RouteFamily,
    RoutingDecision,
    RoutingEngine,
    RuntimeRequest,
    UserContext,
)
from ai_karen_engine.core.cortex.executive import (
    CortexExecutionDecider,
    get_cortex_execution_decider,
)

_COMPAT_EXPORTS = {
    "build_orchestration_input",
    "build_reasoning_request",
    "dispatch",
    "evaluate_cortex",
    "CortexDispatchError",
}

_LEGACY_CONTRACT_EXPORTS = {
    "KROOrchestrator",
    "LangGraphRuntime",
    "OrchestrationInput",
    "OrchestrationResult",
    "ReasoningRequest",
    "ReasoningResult",
    "RbacValidator",
}


def __getattr__(name: str):
    if name in _COMPAT_EXPORTS:
        dispatch_module = import_module("ai_karen_engine.core.cortex.dispatch")
        return getattr(dispatch_module, name)
    if name in _LEGACY_CONTRACT_EXPORTS:
        contracts_module = import_module("ai_karen_engine.core.cortex.contracts")
        return getattr(contracts_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CorrelationIdFactory",
    "CortexExecutionDecider",
    "CortexOutput",
    "ExecutionMode",
    "IntentEngine",
    "IntentSignal",
    "KireEngine",
    "KireSignal",
    "PredictorEngine",
    "PredictorSignal",
    "ReasoningDepth",
    "RouteFamily",
    "RoutingDecision",
    "RoutingEngine",
    "RuntimeRequest",
    "UserContext",
    "get_cortex_execution_decider",
]
