"""Deprecated compatibility bridge for canonical platform observability.

Observability ownership lives in :mod:`ai_karen_engine.platform.observability`.
This package exists only to keep legacy runtime imports operational while callers
are migrated to the platform authority. Do not add observability logic here.
"""

from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    bind_correlation_context,
    clear_correlation_context,
    get_correlation_context,
    reset_correlation_context,
    set_correlation_context,
)

__all__ = [
    "CorrelationContext",
    "bind_correlation_context",
    "clear_correlation_context",
    "get_correlation_context",
    "reset_correlation_context",
    "set_correlation_context",
]
