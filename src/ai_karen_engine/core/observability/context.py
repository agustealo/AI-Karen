"""Deprecated bridge to the platform observability correlation context.

Canonical ownership is ``ai_karen_engine.platform.observability.context``.
Delete this shim after all legacy Core imports are migrated.
"""

from typing import Any

from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    bind_correlation_context,
    clear_correlation_context,
    get_correlation_context,
    reset_correlation_context,
    set_correlation_context,
)


def bind_observability_context(**kwargs: Any) -> None:
    """Compatibility alias for the canonical correlation-context binder."""
    bind_correlation_context(**kwargs)


__all__ = [
    "CorrelationContext",
    "bind_observability_context",
    "bind_correlation_context",
    "clear_correlation_context",
    "get_correlation_context",
    "reset_correlation_context",
    "set_correlation_context",
]
