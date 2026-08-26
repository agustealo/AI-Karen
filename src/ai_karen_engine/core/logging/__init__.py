"""Canonical Core logging package boundary.

The retired ``core.observability`` package is intentionally not re-exported
here. Runtime logging owns log context, structured event helpers, formatters,
redaction service access, and telemetry. Observability authorities live on
their current runtime/platform paths and must not be resurrected through a
logging compatibility facade.
"""

from __future__ import annotations

from .context import (
    RuntimeLogContext,
    bind_log_context,
    clear_log_context,
    get_log_context,
    set_log_context,
)
from .events import (
    ConfigEvents,
    ExpressionEvents,
    MemoryEvents,
    ProviderEvents,
    RoutingEvents,
    RuntimeEvents,
    SecurityEvents,
    ToolEvents,
)
from .formatters import JSONFormatter, StructuredFormatter
from .logger import configure_runtime_logging, get_logger
from .structured_logging import PIIRedactor, get_structured_logging_service
from .telemetry import RuntimeTelemetry as Telemetry

KarenLogger = get_logger
get_structured_logger = get_logger
configure_logging = configure_runtime_logging

__all__ = [
    "ConfigEvents",
    "ExpressionEvents",
    "JSONFormatter",
    "KarenLogger",
    "MemoryEvents",
    "PIIRedactor",
    "ProviderEvents",
    "RoutingEvents",
    "RuntimeEvents",
    "RuntimeLogContext",
    "SecurityEvents",
    "StructuredFormatter",
    "Telemetry",
    "ToolEvents",
    "bind_log_context",
    "clear_log_context",
    "configure_logging",
    "configure_runtime_logging",
    "get_log_context",
    "get_logger",
    "get_structured_logger",
    "get_structured_logging_service",
    "set_log_context",
]
