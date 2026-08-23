"""
Performance regression detection extracted from core/operations/performance_metrics.

This module provides regression detection algorithms that can operate on
in-memory metric data without requiring a SQLite-backed metrics store.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.observability.contracts import RuntimeEvent, RuntimeEventType
from ai_karen_engine.core.observability.emitter import emit

logger = logging.getLogger(__name__)


class AlertSeverity:
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RegressionDetection:
    """Performance regression detection result."""
    metric_name: str
    service_name: str
    baseline_value: float
    current_value: float
    change_percent: float
    is_regression: bool
    severity: str
    detected_at: datetime
    description: str


class RegressionDetector:
    """Detects performance regressions by comparing against baselines."""

    def __init__(self):
        self.regression_thresholds = {
            "cpu_percent": 20.0,
            "memory_usage": 15.0,
            "response_time": 25.0,
            "error_count": 5.0,
        }
        self._baselines: Dict[Tuple[str, str], Tuple[float, int]] = {}

    async def detect_regressions(
        self,
        metrics: List[Any],
        lookback_hours: int = 24,
        min_samples: int = 10,
    ) -> List[RegressionDetection]:
        """Detect performance regressions from metric data."""
        regressions = []

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)

        recent_metrics = [
            m for m in metrics
            if hasattr(m, "timestamp") and m.timestamp >= start_time
            and hasattr(m, "name") and hasattr(m, "service_name")
        ]

        metric_groups: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
        for metric in recent_metrics:
            key = (metric.name, metric.service_name)
            metric_groups[key].append(metric)

        for (metric_name, service_name), group in metric_groups.items():
            if len(group) < min_samples:
                continue

            regression = await self._check_metric_regression(
                metric_name, service_name, group
            )
            if regression:
                regressions.append(regression)
                await emit(
                    event_type=RuntimeEventType.REQUEST_FAILED,
                    provider=service_name,
                    metadata={
                        "regression": regression.to_dict(),
                    },
                )

        return regressions

    async def _check_metric_regression(
        self,
        metric_name: str,
        service_name: str,
        metrics: List[Any],
    ) -> Optional[RegressionDetection]:
        """Check if a specific metric shows regression."""
        values = [m.value for m in metrics if hasattr(m, "value")]

        if not values:
            return None

        key = (metric_name, service_name)
        if key not in self._baselines:
            baseline_value = statistics.mean(values)
            self._baselines[key] = (baseline_value, len(values))
            return None

        baseline_value, _ = self._baselines[key]
        recent_values = values[-min(10, len(values)):]
        current_value = statistics.mean(recent_values)

        if baseline_value == 0:
            change_percent = 0.0
        else:
            change_percent = ((current_value - baseline_value) / baseline_value) * 100

        threshold = self._get_regression_threshold(metric_name)
        is_regression = abs(change_percent) > threshold

        if not is_regression:
            return None

        if abs(change_percent) > threshold * 2:
            severity = AlertSeverity.CRITICAL
        elif abs(change_percent) > threshold * 1.5:
            severity = AlertSeverity.WARNING
        else:
            severity = AlertSeverity.INFO

        direction = "increased" if change_percent > 0 else "decreased"
        description = (
            f"{metric_name} for {service_name} has {direction} by "
            f"{abs(change_percent):.1f}% from baseline"
        )

        return RegressionDetection(
            metric_name=metric_name,
            service_name=service_name,
            baseline_value=baseline_value,
            current_value=current_value,
            change_percent=change_percent,
            is_regression=is_regression,
            severity=severity,
            detected_at=datetime.now(),
            description=description,
        )

    def _get_regression_threshold(self, metric_name: str) -> float:
        """Get regression threshold for a metric."""
        for pattern, threshold in self.regression_thresholds.items():
            if pattern in metric_name.lower():
                return threshold
        return 10.0

    def update_baseline(
        self,
        metric_name: str,
        service_name: str,
        value: float,
        sample_count: int = 1,
    ) -> None:
        """Update baseline for a metric."""
        key = (metric_name, service_name)
        if key in self._baselines:
            old_value, old_count = self._baselines[key]
            total = old_count + sample_count
            new_value = (old_value * old_count + value * sample_count) / total
            self._baselines[key] = (new_value, total)
        else:
            self._baselines[key] = (value, sample_count)
