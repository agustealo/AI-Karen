from __future__ import annotations

from .logger import get_logger, configure_runtime_logging

# Compatibility aliases
KarenLogger = get_logger
get_structured_logger = get_logger
configure_logging = configure_runtime_logging

from .formatters import StructuredFormatter, JSONFormatter
from .structured_logging import PIIRedactor, get_structured_logging_service
from .telemetry import RuntimeTelemetry as Telemetry
from .context import (
    get_log_context,
    set_log_context,
    clear_log_context,
    bind_log_context,
    RuntimeLogContext,
)
from .events import (
    RuntimeEvents,
    ExpressionEvents,
    ProviderEvents,
    RoutingEvents,
    MemoryEvents,
    ToolEvents,
    SecurityEvents,
    ConfigEvents,
)

__all__ = [
    "get_logger",
    "configure_runtime_logging",
    "get_log_context",
    "set_log_context",
    "clear_log_context",
    "bind_log_context",
    "RuntimeLogContext",
    "RuntimeEvents",
    "ExpressionEvents",
    "ProviderEvents",
    "RoutingEvents",
    "MemoryEvents",
    "ToolEvents",
    "SecurityEvents",
    "ConfigEvents",
]
