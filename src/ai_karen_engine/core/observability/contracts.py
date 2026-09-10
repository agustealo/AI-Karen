"""Compatibility shim for core.observability.contracts.

Canonical implementation lives in ai_karen_engine.platform.observability.contracts.
"""

from ai_karen_engine.platform.observability.contracts import (
    HIGH_CARDINALITY_LABELS,
    ErrorCategory,
    EventType,
    ExecutionEvent,
    OperationalState,
)

# Alias for backward-compatibility
RuntimeEventType = EventType

__all__ = [
    "HIGH_CARDINALITY_LABELS",
    "ErrorCategory",
    "EventType",
    "ExecutionEvent",
    "OperationalState",
    "RuntimeEventType",
]
