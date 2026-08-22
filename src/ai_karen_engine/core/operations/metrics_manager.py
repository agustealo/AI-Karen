"""
DEPRECATED: metrics_manager has moved to ai_karen_engine.core.observability.metrics.

This shim exists for backward compatibility only. Update imports to use:
    from ai_karen_engine.core.observability.metrics import get_metrics_manager
"""

from ai_karen_engine.core.observability.metrics import (  # noqa: F401
    MetricsManager,
    get_metrics_manager,
    register_service_metrics,
)

__all__ = [
    "MetricsManager",
    "get_metrics_manager",
    "register_service_metrics",
]
