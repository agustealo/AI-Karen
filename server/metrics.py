# mypy: ignore-errors
"""
Metrics configuration for Kari FastAPI Server.
Handles Prometheus setup, counters, and metrics manager integration.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("kari")

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Histogram,
        Gauge,
        generate_latest,
    )
    PROMETHEUS_ENABLED = True
except ImportError:
    PROMETHEUS_ENABLED = False
    logger.warning("Prometheus client not available, metrics disabled")

# Initialize metrics using the enhanced metrics manager
from src.ai_karen_engine.platform.observability.metrics import get_metrics_collector as get_metrics_manager


def initialize_metrics() -> Dict[str, Any]:
    """Initialize HTTP metrics using the safe metrics manager."""
    manager = get_metrics_manager()
    
    metrics = {}
    # Initialize metrics directly without context manager
    metrics['REQUEST_COUNT'] = manager.counter(
        "kari_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"]
    )
    metrics['REQUEST_LATENCY'] = manager.histogram(
        "kari_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path"]
    )
    metrics['ERROR_COUNT'] = manager.counter(
        "kari_http_errors_total",
        "Total HTTP errors",
        ["method", "path", "error_type"]
    )
    
    # Extension-specific metrics
    metrics['EXTENSION_HEALTH_STATUS'] = manager.gauge(
        "kari_extension_health_status",
        "Extension health status (1=healthy, 0.5=degraded, 0=unhealthy)",
        ["extension_name", "extension_category"]
    )
    metrics['EXTENSION_RESPONSE_TIME'] = manager.histogram(
        "kari_extension_response_time_seconds",
        "Extension response time in seconds",
        ["extension_name", "operation"]
    )
    metrics['EXTENSION_BACKGROUND_TASKS'] = manager.gauge(
        "kari_extension_background_tasks_total",
        "Number of active background tasks per extension",
        ["extension_name", "task_status"]
    )
    metrics['EXTENSION_API_CALLS'] = manager.counter(
        "kari_extension_api_calls_total",
        "Total extension API calls",
        ["extension_name", "endpoint", "status_code"]
    )
    metrics['EXTENSION_ERRORS'] = manager.counter(
        "kari_extension_errors_total",
        "Total extension errors",
        ["extension_name", "error_type"]
    )
    metrics['EXTENSION_UPTIME'] = manager.gauge(
        "kari_extension_uptime_seconds",
        "Extension uptime in seconds",
        ["extension_name"]
    )
    
    # Runtime metrics
    metrics['REQUESTS_INFLIGHT'] = manager.gauge(
        "kari_requests_inflight",
        "Current number of in-flight HTTP requests",
        ["method", "path"]
    )
    metrics['DEGRADED_REQUESTS_TOTAL'] = manager.counter(
        "kari_degraded_requests_total",
        "Total requests served in degraded mode",
        ["reason"]
    )
    
    return metrics


# Initialize metrics safely
_http_metrics = initialize_metrics()
REQUEST_COUNT = _http_metrics['REQUEST_COUNT']
REQUEST_LATENCY = _http_metrics['REQUEST_LATENCY']
ERROR_COUNT = _http_metrics['ERROR_COUNT']

# Extension metrics
EXTENSION_HEALTH_STATUS = _http_metrics['EXTENSION_HEALTH_STATUS']
EXTENSION_RESPONSE_TIME = _http_metrics['EXTENSION_RESPONSE_TIME']
EXTENSION_BACKGROUND_TASKS = _http_metrics['EXTENSION_BACKGROUND_TASKS']
EXTENSION_API_CALLS = _http_metrics['EXTENSION_API_CALLS']
EXTENSION_ERRORS = _http_metrics['EXTENSION_ERRORS']
EXTENSION_UPTIME = _http_metrics['EXTENSION_UPTIME']

# Runtime metrics
REQUESTS_INFLIGHT = _http_metrics['REQUESTS_INFLIGHT']
DEGRADED_REQUESTS_TOTAL = _http_metrics['DEGRADED_REQUESTS_TOTAL']
