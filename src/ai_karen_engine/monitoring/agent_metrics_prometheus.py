"""Agent and tool Prometheus metrics for KAREN."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class AgentPrometheusMetrics:
    """Prometheus metrics for agent execution and tool usage."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.agent_execution_total = self.metrics_manager.register_counter(
                "karen_agent_execution_total",
                "Total agent executions",
                ["agent_id", "status"],
            )
            self.agent_execution_seconds = self.metrics_manager.register_histogram(
                "karen_agent_execution_seconds",
                "Agent execution latency in seconds",
                ["agent_id"],
                buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            )
            self.tool_execution_total = self.metrics_manager.register_counter(
                "karen_tool_execution_total",
                "Total tool executions",
                ["tool_id", "status"],
            )

    def record_agent_execution(
        self,
        agent_id: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.agent_execution_total.labels(
                agent_id=agent_id, status=status
            ).inc()
            self.agent_execution_seconds.labels(agent_id=agent_id).observe(
                duration_seconds
            )
        except Exception as exc:
            logger.debug("Failed to record agent execution metric: %s", exc)

    def record_tool_execution(
        self,
        tool_id: str,
        status: str,
    ) -> None:
        try:
            self.tool_execution_total.labels(tool_id=tool_id, status=status).inc()
        except Exception as exc:
            logger.debug("Failed to record tool execution metric: %s", exc)


_agent_prometheus_metrics: Optional[AgentPrometheusMetrics] = None


def get_agent_prometheus_metrics() -> AgentPrometheusMetrics:
    global _agent_prometheus_metrics
    if _agent_prometheus_metrics is None:
        _agent_prometheus_metrics = AgentPrometheusMetrics()
    return _agent_prometheus_metrics
