"""Platform monitoring package boundary.

Monitoring subsystems are loaded lazily so importing one focused monitoring
module does not initialize unrelated metrics, tracing, extension, or startup
stacks. This keeps package import side effects out of auth/database/runtime
paths while preserving the existing public package API.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "get_model_orchestrator_metrics": (".model_orchestrator_metrics", "get_model_orchestrator_metrics"),
    "ModelOrchestratorMetrics": (".model_orchestrator_metrics", "ModelOrchestratorMetrics"),
    "ModelOperationType": (".model_orchestrator_metrics", "ModelOperationType"),
    "ModelOperationStatus": (".model_orchestrator_metrics", "ModelOperationStatus"),
    "ModelMetricsContext": (".model_orchestrator_metrics", "ModelMetricsContext"),
    "create_operation_context": (".model_orchestrator_metrics", "create_operation_context"),
    "get_model_orchestrator_tracer": (".model_orchestrator_tracing", "get_model_orchestrator_tracer"),
    "ModelOrchestratorTracer": (".model_orchestrator_tracing", "ModelOrchestratorTracer"),
    "TraceContext": (".model_orchestrator_tracing", "TraceContext"),
    "create_correlation_id": (".model_orchestrator_tracing", "create_correlation_id"),
    "get_current_correlation_id": (".model_orchestrator_tracing", "get_current_correlation_id"),
    "get_model_storage_monitor": (".model_storage_monitor", "get_model_storage_monitor"),
    "ModelStorageMonitor": (".model_storage_monitor", "ModelStorageMonitor"),
    "StorageInfo": (".model_storage_monitor", "StorageInfo"),
    "ModelStorageStats": (".model_storage_monitor", "ModelStorageStats"),
    "CorrelationService": (".correlation_service", "CorrelationService"),
    "create_correlation_logger": (".correlation_service", "create_correlation_logger"),
    "get_correlation_service": (".correlation_service", "get_correlation_service"),
    "get_request_id": (".correlation_service", "get_request_id"),
    "MetricsService": (".metrics_service", "MetricsService"),
    "get_metrics_service": (".metrics_service", "get_metrics_service"),
    "StructuredLoggingService": (".structured_logging_service", "StructuredLoggingService"),
    "get_structured_logging_service": (".structured_logging_service", "get_structured_logging_service"),
    "ExtensionMetricsCollector": (".extensions", "ExtensionMetricsCollector"),
    "ExtensionAlertManager": (".extensions", "ExtensionAlertManager"),
    "ExtensionMonitoringDashboard": (".extensions", "ExtensionMonitoringDashboard"),
    "extension_dashboard": (".extensions", "extension_dashboard"),
    "monitoring_router": (".extensions", "monitoring_router"),
    "MonitoringMiddleware": (".extensions", "MonitoringMiddleware"),
    "ExtensionAlertingSystem": (".extensions", "ExtensionAlertingSystem"),
    "extension_alerting": (".extensions", "extension_alerting"),
    "NotificationChannel": (".extensions", "NotificationChannel"),
    "EscalationLevel": (".extensions", "EscalationLevel"),
    "NotificationConfig": (".extensions", "NotificationConfig"),
    "AlertRule": (".extensions", "AlertRule"),
    "ExtensionPerformanceMonitor": (".extensions", "ExtensionPerformanceMonitor"),
    "extension_performance_monitor": (".extensions", "extension_performance_monitor"),
    "PerformanceMetric": (".extensions", "PerformanceMetric"),
    "ResourceUsage": (".extensions", "ResourceUsage"),
    "EndpointStats": (".extensions", "EndpointStats"),
    "MetricType": (".extensions", "MetricType"),
    "AlertSeverity": (".extensions", "AlertSeverity"),
    "Alert": (".extensions", "Alert"),
    "platform_monitoring_lifespan": (".startup_integration", "platform_monitoring_lifespan"),
    "setup_platform_monitoring_app": (".startup_integration", "setup_platform_monitoring_app"),
    "create_platform_monitoring_app": (".startup_integration", "create_platform_monitoring_app"),
    "get_platform_monitoring_status": (".startup_integration", "get_platform_monitoring_status"),
    "monitor_platform_endpoint": (".startup_integration", "monitor_platform_endpoint"),
    "monitor_platform_operation": (".startup_integration", "monitor_platform_operation"),
    "RuntimeMetrics": (".runtime_metrics", "RuntimeMetrics"),
    "get_runtime_metrics": (".runtime_metrics", "get_runtime_metrics"),
    "MLMetrics": (".ml_metrics", "MLMetrics"),
    "get_ml_metrics": (".ml_metrics", "get_ml_metrics"),
    "PersonalizationMetrics": (".personalization_metrics", "PersonalizationMetrics"),
    "get_personalization_metrics": (".personalization_metrics", "get_personalization_metrics"),
    "AdaptiveMetrics": (".adaptive_metrics", "AdaptiveMetrics"),
    "get_adaptive_metrics": (".adaptive_metrics", "get_adaptive_metrics"),
    "DatabaseMetrics": (".database_metrics", "DatabaseMetrics"),
    "get_database_metrics": (".database_metrics", "get_database_metrics"),
    "AgentPrometheusMetrics": (".agent_metrics_prometheus", "AgentPrometheusMetrics"),
    "get_agent_prometheus_metrics": (".agent_metrics_prometheus", "get_agent_prometheus_metrics"),
}

__all__ = [*_EXPORTS, "get_monitoring_service"]


def __getattr__(name: str) -> Any:
    if name == "get_monitoring_service":
        value = __getattr__("get_metrics_service")
        globals()[name] = value
        return value

    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
