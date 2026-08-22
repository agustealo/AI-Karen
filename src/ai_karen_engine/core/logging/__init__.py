from __future__ import annotations

from .logger import configure_runtime_logging, get_logger

# Compatibility aliases
KarenLogger = get_logger
get_structured_logger = get_logger
configure_logging = configure_runtime_logging

# Canonical observability re-exports.
# New code should import from ``ai_karen_engine.core.observability`` directly.
from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    bind_observability_context,
    clear_observability_context,
    get_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.observability.contracts import RuntimeEvent, RuntimeEventType
from ai_karen_engine.core.observability.emitter import (
    ObservabilityEmitter,
    emit,
    get_observability_emitter,
)
from ai_karen_engine.core.observability.events import (
    ConfigEvents as ObservabilityConfigEvents,
)
from ai_karen_engine.core.observability.events import (
    ExpressionEvents as ObservabilityExpressionEvents,
)
from ai_karen_engine.core.observability.events import (
    MemoryEvents as ObservabilityMemoryEvents,
)
from ai_karen_engine.core.observability.events import (
    ProviderEvents as ObservabilityProviderEvents,
)
from ai_karen_engine.core.observability.events import (
    RoutingEvents as ObservabilityRoutingEvents,
)
from ai_karen_engine.core.observability.events import (
    RuntimeEvents as ObservabilityRuntimeEvents,
)
from ai_karen_engine.core.observability.events import (
    SecurityEvents as ObservabilitySecurityEvents,
)
from ai_karen_engine.core.observability.events import (
    ToolEvents as ObservabilityToolEvents,
)
from ai_karen_engine.core.observability.redaction import redact_data, redact_text

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
from .structured_logging import PIIRedactor, get_structured_logging_service
from .telemetry import RuntimeTelemetry as Telemetry

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
    # Canonical observability API
    "ObservabilityContext",
    "get_observability_context",
    "set_observability_context",
    "bind_observability_context",
    "clear_observability_context",
    "RuntimeEvent",
    "RuntimeEventType",
    "ObservabilityEmitter",
    "get_observability_emitter",
    "emit",
    "redact_data",
    "redact_text",
    "ObservabilityRuntimeEvents",
    "ObservabilityExpressionEvents",
    "ObservabilityProviderEvents",
    "ObservabilityRoutingEvents",
    "ObservabilityMemoryEvents",
    "ObservabilityToolEvents",
    "ObservabilitySecurityEvents",
    "ObservabilityConfigEvents",
]
