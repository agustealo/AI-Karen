from __future__ import annotations

"""Runtime composition authority.

This module owns construction of stateful runtime collaborators. Cognitive code
must define decision behavior, not hide process-wide instances. Runtime callers
that still depend on compatibility accessors resolve through this composition
boundary until application startup owns the container directly.

The decision path is explicit here:

    CORTEX -> RuntimePolicy -> RuntimeDecisionPipeline -> ChatRuntime execution

CORTEX decides. RuntimePolicy authorizes. Runtime executes.
"""

from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
    from ai_karen_engine.core.expression.gateway import ExpressionGateway
    from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer


@dataclass(frozen=True)
class RuntimeComposition:
    """Process-wide runtime collaborators assembled in one place."""

    cognitive_cortex: CortexExecutionDecider
    runtime_policy: RuntimePolicyEnforcer
    decision_pipeline: RuntimeDecisionPipeline
    expression_gateway: ExpressionGateway

    @property
    def cortex(self) -> RuntimeDecisionPipeline:
        """Compatibility view used by ChatRuntime.

        ``ChatRuntime._decide`` historically calls ``composition.cortex.decide``.
        The property now resolves to the Runtime-owned decision pipeline, whose
        first stage is the pure cognitive CORTEX and whose second stage is
        RuntimePolicy. Remove this alias when ChatRuntime is decomposed into
        explicit decision and authorization stages.
        """

        return self.decision_pipeline


_composition: Optional[RuntimeComposition] = None
_composition_lock = Lock()


def build_runtime_composition() -> RuntimeComposition:
    """Build a fresh runtime dependency graph at the composition edge."""
    from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
    from ai_karen_engine.core.expression.gateway import ExpressionGateway
    from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer

    cognitive_cortex = CortexExecutionDecider()
    runtime_policy = RuntimePolicyEnforcer()
    decision_pipeline = RuntimeDecisionPipeline(
        cortex=cognitive_cortex,
        policy=runtime_policy,
    )

    return RuntimeComposition(
        cognitive_cortex=cognitive_cortex,
        runtime_policy=runtime_policy,
        decision_pipeline=decision_pipeline,
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


def get_cortex_execution_decider() -> RuntimeDecisionPipeline:
    """Compatibility accessor for the Runtime-owned decision pipeline."""
    return get_runtime_composition().decision_pipeline


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
