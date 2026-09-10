"""Performance metrics and monitoring system for core observability."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PerformanceMetric:
    name: str
    value: float
    metric_type: MetricType = MetricType.GAUGE
    service_name: str = "ai-karen"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: Dict[str, str] = field(default_factory=dict)
    unit: str = ""
    description: str = ""


class PerformanceMonitoringSystem:
    """In-memory performance monitoring system manager."""

    def __init__(self) -> None:
        self.metrics: List[PerformanceMetric] = []

    async def get_dashboard_data(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_services": ["ai-karen"],
            "total_metrics": len(self.metrics),
            "system_health": "healthy",
        }

    async def get_metrics(
        self,
        metric_name: Optional[str] = None,
        service_name: Optional[str] = None,
        hours: int = 1,
    ) -> List[Dict[str, Any]]:
        return [m.__dict__ for m in self.metrics]

    async def record_metric(self, metric: PerformanceMetric) -> None:
        self.metrics.append(metric)


_monitoring_system_instance: Optional[PerformanceMonitoringSystem] = None


def get_performance_monitoring_system() -> PerformanceMonitoringSystem:
    global _monitoring_system_instance
    if _monitoring_system_instance is None:
        _monitoring_system_instance = PerformanceMonitoringSystem()
    return _monitoring_system_instance
