"""Database and Redis metrics for KAREN."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class DatabaseMetrics:
    """Collects database and Redis health metrics."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.postgres_health = self.metrics_manager.register_gauge(
                "karen_postgres_health",
                "PostgreSQL health status (1=healthy, 0=unhealthy)",
            )
            self.redis_health = self.metrics_manager.register_gauge(
                "karen_redis_health",
                "Redis health status (1=healthy, 0=unhealthy)",
            )
            self.db_query_seconds = self.metrics_manager.register_histogram(
                "karen_db_query_seconds",
                "Database query latency in seconds",
                ["database", "operation"],
                buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
            )
            self.queue_depth = self.metrics_manager.register_gauge(
                "karen_queue_depth",
                "Current depth of internal queues",
                ["queue_name"],
            )

    def set_postgres_health(self, healthy: bool) -> None:
        try:
            self.postgres_health.set(1 if healthy else 0)
        except Exception as exc:
            logger.debug("Failed to set postgres health metric: %s", exc)

    def set_redis_health(self, healthy: bool) -> None:
        try:
            self.redis_health.set(1 if healthy else 0)
        except Exception as exc:
            logger.debug("Failed to set redis health metric: %s", exc)

    def record_query(
        self,
        database: str,
        operation: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.db_query_seconds.labels(
                database=database, operation=operation
            ).observe(duration_seconds)
        except Exception as exc:
            logger.debug("Failed to record db query metric: %s", exc)

    def set_queue_depth(self, queue_name: str, depth: int) -> None:
        try:
            self.queue_depth.labels(queue_name=queue_name).set(depth)
        except Exception as exc:
            logger.debug("Failed to set queue depth metric: %s", exc)


_database_metrics: Optional[DatabaseMetrics] = None


def get_database_metrics() -> DatabaseMetrics:
    global _database_metrics
    if _database_metrics is None:
        _database_metrics = DatabaseMetrics()
    return _database_metrics
