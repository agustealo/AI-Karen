from __future__ import annotations

"""Runtime composition authority.

This module owns construction of stateful runtime collaborators. Cognitive code
must define decision behavior, not hide process-wide instances. Runtime callers
that still depend on compatibility accessors resolve through this composition
boundary until application startup owns the container directly.

The composition contract intentionally keeps concrete imports lazy. Importing
an operational runtime module must not eagerly initialize or import the cognitive
stack merely to refer to the dependency graph type.
"""

from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
    from ai_karen_engine.core.expression.gateway import ExpressionGateway


@dataclass(frozen=True)
class RuntimeComposition:
    """Process-wide runtime collaborators assembled in one place."""

    cortex: CortexExecutionDecider
    expression_gateway: ExpressionGateway


_composition: Optional[RuntimeComposition] = None
_composition_lock = Lock()


def build_runtime_composition() -> RuntimeComposition:
    """Build a fresh runtime dependency graph at the composition edge."""
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
    from ai_karen_engine.core.expression.gateway import ExpressionGateway

    return RuntimeComposition(
        cortex=CortexExecutionDecider(),
        expression_gateway=ExpressionGateway(),
    )


def get_runtime_composition() -> RuntimeComposition:
    """Return the process composition assembled by the runtime boundary."""
    global _composition
    if _composition is None:
        with _composition_lock:
            if _composition is None:
                _composition = build_runtime_composition()
    return _composition


def get_cortex_execution_decider() -> CortexExecutionDecider:
    """Compatibility accessor backed by the runtime-owned composition graph."""
    return get_runtime_composition().cortex


def get_expression_gateway() -> ExpressionGateway:
    """Return the runtime-owned expression gateway."""
    return get_runtime_composition().expression_gateway


def set_runtime_composition(composition: RuntimeComposition) -> None:
    """Install an explicit composition, primarily for application startup/tests."""
    global _composition
    with _composition_lock:
        _composition = composition


def reset_runtime_composition() -> None:
    """Clear process composition so a subsequent access rebuilds dependencies."""
    global _composition
    with _composition_lock:
        _composition = None


__all__ = [
    "RuntimeComposition",
    "build_runtime_composition",
    "get_cortex_execution_decider",
    "get_expression_gateway",
    "get_runtime_composition",
    "reset_runtime_composition",
    "set_runtime_composition",
]
