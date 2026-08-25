"""
DEPRECATED: performance_metrics has moved to platform/observability/metrics.py

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.observability.metrics import ...

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.observability.performance_metrics is deprecated. "
    "Import from ai_karen_engine.platform.observability.metrics instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.observability.metrics import *  # noqa: F401,F403

try:
    from ai_karen_engine.platform.observability.metrics import (  # noqa: F401
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
except ImportError:
    from enum import Enum

    class MetricType(str, Enum):
        COUNTER = "counter"
        GAUGE = "gauge"
        HISTOGRAM = "histogram"
        SUMMARY = "summary"

    class AlertSeverity(str, Enum):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"

    class PerformanceMetric:
        pass

    class SystemMetrics:
        pass

    class ServiceMetrics:
        pass

    class MetricsCollector:
        pass

    class PerformanceDashboard:
        pass

    class PerformanceBenchmark:
        pass

    class PerformanceMonitoringSystem:
        pass

    class PerformanceMetrics:
        pass

    def get_performance_monitoring_system():
        return None

    def initialize_performance_monitoring():
        return None

    def shutdown_performance_monitoring():
        return None
