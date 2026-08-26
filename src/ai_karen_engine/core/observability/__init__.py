"""Legacy Core observability compatibility surface.

Canonical observability implementation authority lives in
``ai_karen_engine.platform.observability``.

Do not add new metrics, sinks, exporters, diagnostics buffers, event
implementations, or telemetry infrastructure here. Existing imports are kept
only while callers migrate to the platform owner; this package is a retirement
candidate once the reference audit reaches zero external callers.
"""

from __future__ import annotations

from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    bind_observability_context,
    clear_observability_context,
    get_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.observability.contracts import (
    RuntimeEvent,
    RuntimeEventType,
)
from ai_karen_engine.core.observability.emitter import (
    ObservabilityEmitter,
    emit,
    get_observability_emitter,
)
from ai_karen_engine.core.observability.redaction import redact_data, redact_text
from ai_karen_engine.core.observability.performance_metrics import (
    MetricType,
    AlertSeverity,
    PerformanceMetric,
    SystemMetrics,
    ServiceMetrics,
    MetricsCollector,
    PerformanceDashboard,
    PerformanceBenchmark,
    PerformanceMonitoringSystem,
    PerformanceMetrics,
    get_performance_monitoring_system,
    initialize_performance_monitoring,
    shutdown_performance_monitoring,
)
from ai_karen_engine.core.observability.regression_detection import (
    RegressionDetector,
    RegressionDetection,
)
from ai_karen_engine.core.observability.metrics import (
    MetricsManager,
    get_metrics_manager,
    register_service_metrics,
)

__all__ = [
    "ObservabilityContext",
    "ObservabilityEmitter",
    "RuntimeEvent",
    "RuntimeEventType",
    "bind_observability_context",
    "clear_observability_context",
    "emit",
    "get_observability_context",
    "get_observability_emitter",
    "redact_data",
    "redact_text",
    "set_observability_context",
    "MetricType",
    "AlertSeverity",
    "PerformanceMetric",
    "SystemMetrics",
    "ServiceMetrics",
    "MetricsCollector",
    "PerformanceDashboard",
    "PerformanceBenchmark",
    "PerformanceMonitoringSystem",
    "PerformanceMetrics",
    "get_performance_monitoring_system",
    "initialize_performance_monitoring",
    "shutdown_performance_monitoring",
    "RegressionDetector",
    "RegressionDetection",
    "MetricsManager",
    "get_metrics_manager",
    "register_service_metrics",
]
