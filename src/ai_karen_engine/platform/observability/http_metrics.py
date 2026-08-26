from __future__ import annotations

from typing import Any

from .metrics import get_metrics_collector


_collector = get_metrics_collector()

# Preserve the existing public metric names while moving ownership out of the
# transitional root server package. A later metric-vocabulary migration can
# version/rename these without coupling application composition to metrics.
REQUEST_COUNT = _collector.counter(
    "kari_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = _collector.histogram(
    "kari_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
ERROR_COUNT = _collector.counter(
    "kari_http_errors_total",
    "Total HTTP errors",
    ["method", "path", "error_type"],
)

EXTENSION_HEALTH_STATUS = _collector.gauge(
    "kari_extension_health_status",
    "Extension health status (1=healthy, 0.5=degraded, 0=unhealthy)",
    ["extension_name", "extension_category"],
)
EXTENSION_RESPONSE_TIME = _collector.histogram(
    "kari_extension_response_time_seconds",
    "Extension response time in seconds",
    ["extension_name", "operation"],
)
EXTENSION_BACKGROUND_TASKS = _collector.gauge(
    "kari_extension_background_tasks_total",
    "Number of active background tasks per extension",
    ["extension_name", "task_status"],
)
EXTENSION_API_CALLS = _collector.counter(
    "kari_extension_api_calls_total",
    "Total extension API calls",
    ["extension_name", "endpoint", "status_code"],
)
EXTENSION_ERRORS = _collector.counter(
    "kari_extension_errors_total",
    "Total extension errors",
    ["extension_name", "error_type"],
)
EXTENSION_UPTIME = _collector.gauge(
    "kari_extension_uptime_seconds",
    "Extension uptime in seconds",
    ["extension_name"],
)

REQUESTS_INFLIGHT = _collector.gauge(
    "kari_requests_inflight",
    "Current number of in-flight HTTP requests",
    ["method", "path"],
)
DEGRADED_REQUESTS_TOTAL = _collector.counter(
    "kari_degraded_requests_total",
    "Total requests served in degraded mode",
    ["reason"],
)


def initialize_metrics() -> dict[str, Any]:
    """Return the canonical process-wide HTTP/runtime metric instruments."""

    return {
        "REQUEST_COUNT": REQUEST_COUNT,
        "REQUEST_LATENCY": REQUEST_LATENCY,
        "ERROR_COUNT": ERROR_COUNT,
        "EXTENSION_HEALTH_STATUS": EXTENSION_HEALTH_STATUS,
        "EXTENSION_RESPONSE_TIME": EXTENSION_RESPONSE_TIME,
        "EXTENSION_BACKGROUND_TASKS": EXTENSION_BACKGROUND_TASKS,
        "EXTENSION_API_CALLS": EXTENSION_API_CALLS,
        "EXTENSION_ERRORS": EXTENSION_ERRORS,
        "EXTENSION_UPTIME": EXTENSION_UPTIME,
        "REQUESTS_INFLIGHT": REQUESTS_INFLIGHT,
        "DEGRADED_REQUESTS_TOTAL": DEGRADED_REQUESTS_TOTAL,
    }


__all__ = [
    "DEGRADED_REQUESTS_TOTAL",
    "ERROR_COUNT",
    "EXTENSION_API_CALLS",
    "EXTENSION_BACKGROUND_TASKS",
    "EXTENSION_ERRORS",
    "EXTENSION_HEALTH_STATUS",
    "EXTENSION_RESPONSE_TIME",
    "EXTENSION_UPTIME",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "REQUESTS_INFLIGHT",
    "initialize_metrics",
]
