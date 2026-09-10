"""Compatibility shim for core.observability.emitter.

Canonical implementation lives in ai_karen_engine.platform.observability.events.
"""

from ai_karen_engine.platform.observability.events import (
    ObservabilityEmitter,
    ObservabilitySink,
    StructuredLoggingSink,
    emit_event,
    get_observability_emitter,
)

__all__ = [
    "ObservabilityEmitter",
    "ObservabilitySink",
    "StructuredLoggingSink",
    "emit_event",
    "get_observability_emitter",
]
