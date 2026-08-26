# mypy: ignore-errors
"""Compatibility shim for canonical platform observability metrics.

New code must import metric instruments from
``ai_karen_engine.platform.observability.http_metrics``. This root module is
retained temporarily while remaining imports are audited and migrated.
"""

from ai_karen_engine.platform.observability.http_metrics import (
    DEGRADED_REQUESTS_TOTAL,
    ERROR_COUNT,
    EXTENSION_API_CALLS,
    EXTENSION_BACKGROUND_TASKS,
    EXTENSION_ERRORS,
    EXTENSION_HEALTH_STATUS,
    EXTENSION_RESPONSE_TIME,
    EXTENSION_UPTIME,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    REQUESTS_INFLIGHT,
    initialize_metrics,
)

PROMETHEUS_ENABLED = True

__all__ = [
    "DEGRADED_REQUESTS_TOTAL",
    "ERROR_COUNT",
    "EXTENSION_API_CALLS",
    "EXTENSION_BACKGROUND_TASKS",
    "EXTENSION_ERRORS",
    "EXTENSION_HEALTH_STATUS",
    "EXTENSION_RESPONSE_TIME",
    "EXTENSION_UPTIME",
    "PROMETHEUS_ENABLED",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "REQUESTS_INFLIGHT",
    "initialize_metrics",
]
