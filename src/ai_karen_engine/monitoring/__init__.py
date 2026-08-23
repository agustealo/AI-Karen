"""
Platform Monitoring Integration.

This module provides a unified interface for all platform monitoring,
including model orchestrator monitoring, extension monitoring, metrics,
logging, and health check functionality.
"""

from .model_orchestrator_metrics import (
    get_model_orchestrator_metrics,
    ModelOrchestratorMetrics,
    ModelOperationType,
    ModelOperationStatus,
    ModelMetricsContext,
    create_operation_context,
)

from .model_orchestrator_tracing import (
    get_model_orchestrator_tracer,
    ModelOrchestratorTracer,
    TraceContext,
    create_correlation_id,
    get_current_correlation_id,
)

from .model_storage_monitor import (
    get_model_storage_monitor,
    ModelStorageMonitor,
    StorageInfo,
    ModelStorageStats,
)
from .correlation_service import (
    CorrelationService,
    create_correlation_logger,
    get_correlation_service,
    get_request_id,
)
from .metrics_service import MetricsService, get_metrics_service
from .structured_logging_service import (
    StructuredLoggingService,
    get_structured_logging_service,
)

from .extensions import (
    ExtensionMetricsCollector,
    ExtensionAlertManager,
    ExtensionMonitoringDashboard,
    extension_dashboard,
    monitoring_router,
    MonitoringMiddleware,
    ExtensionAlertingSystem,
    extension_alerting,
    NotificationChannel,
    EscalationLevel,
    NotificationConfig,
    AlertRule,
    ExtensionPerformanceMonitor,
    extension_performance_monitor,
    PerformanceMetric,
    ResourceUsage,
    EndpointStats,
    MetricType,
    AlertSeverity,
    Alert,
)

from .startup_integration import (
    platform_monitoring_lifespan,
    setup_platform_monitoring_app,
    create_platform_monitoring_app,
    get_platform_monitoring_status,
    monitor_platform_endpoint,
    monitor_platform_operation,
)

__all__ = [
    # Metrics
    "get_model_orchestrator_metrics",
    "ModelOrchestratorMetrics",
    "ModelOperationType",
    "ModelOperationStatus",
    "ModelMetricsContext",
    "create_operation_context",
    # Tracing
    "get_model_orchestrator_tracer",
    "ModelOrchestratorTracer",
    "TraceContext",
    "create_correlation_id",
    "get_current_correlation_id",
    # Storage Monitoring
    "get_model_storage_monitor",
    "ModelStorageMonitor",
    "StorageInfo",
    "ModelStorageStats",
    # Services
    "CorrelationService",
    "create_correlation_logger",
    "get_correlation_service",
    "get_request_id",
    "MetricsService",
    "get_metrics_service",
    "StructuredLoggingService",
    "get_structured_logging_service",
    # Extension Monitoring
    "ExtensionMetricsCollector",
    "ExtensionAlertManager",
    "ExtensionMonitoringDashboard",
    "extension_dashboard",
    "monitoring_router",
    "MonitoringMiddleware",
    "ExtensionAlertingSystem",
    "extension_alerting",
    "NotificationChannel",
    "EscalationLevel",
    "NotificationConfig",
    "AlertRule",
    "ExtensionPerformanceMonitor",
    "extension_performance_monitor",
    "PerformanceMetric",
    "ResourceUsage",
    "EndpointStats",
    "MetricType",
    "AlertSeverity",
    "Alert",
    # Platform Monitoring Startup
    "platform_monitoring_lifespan",
    "setup_platform_monitoring_app",
    "create_platform_monitoring_app",
    "get_platform_monitoring_status",
    "monitor_platform_endpoint",
    "monitor_platform_operation",
    "get_monitoring_service",
]


get_monitoring_service = get_metrics_service
