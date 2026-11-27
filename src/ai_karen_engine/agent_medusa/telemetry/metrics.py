import time
import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from ai_karen_engine.platform.observability.metrics import get_metrics_collector

logger = logging.getLogger(__name__)

_RETENTION_OUTCOMES = {
    "acknowledgement": frozenset({
        "acknowledged", "not_confirmed", "unavailable", "timeout",
        "invalid", "cancelled",
    }),
    "repair_batch": frozenset({
        "empty", "cycle", "batch_limit", "unavailable", "timeout", "cancelled",
    }),
    "repair_candidate": frozenset({
        "durable_missing", "scope_skipped", "not_terminal",
    }),
}


def record_retention_event(operation: str, outcome: str) -> None:
    """Record bounded attempt outcomes, never tenant IDs or unique backlog."""
    if outcome not in _RETENTION_OUTCOMES.get(operation, ()):
        return
    try:
        get_metrics_collector().counter(
            "kari_medusa_terminal_retention_events_total",
            "Medusa terminal retention operation outcomes, not unique receipts or backlog",
            ["operation", "outcome"],
        ).labels(operation=operation, outcome=outcome).inc()
    except Exception:
        # Observability must never interrupt receipt recovery or cancellation.
        logger.debug("Medusa retention metric unavailable")


class MedusaMetrics:
    """Telemetry and metrics collection for AgentMedusa."""
    
    def __init__(self):
        self._execution_times: Dict[str, List[float]] = defaultdict(list)
        self._success_counts: Dict[str, int] = defaultdict(int)
        self._failure_counts: Dict[str, int] = defaultdict(int)
        self._tool_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._memory_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._start_time = datetime.now(timezone.utc)

    def record_execution(self, agent_id: str, duration_ms: float, success: bool = True):
        """Record execution metrics for an agent."""
        self._execution_times[agent_id].append(duration_ms)
        if len(self._execution_times[agent_id]) > 1000:
            self._execution_times[agent_id].pop(0)
        
        if success:
            self._success_counts[agent_id] += 1
        else:
            self._failure_counts[agent_id] += 1

    def record_tool_use(self, agent_id: str, tool_name: str):
        """Record tool usage metrics."""
        self._tool_usage[agent_id][tool_name] += 1

    def record_memory_op(self, agent_id: str, op_type: str):
        """Record memory operation metrics."""
        self._memory_usage[agent_id][op_type] += 1

    def get_agent_metrics(self, agent_id: str) -> Dict[str, Any]:
        """Get metrics for a specific agent."""
        times = self._execution_times.get(agent_id, [])
        success = self._success_counts.get(agent_id, 0)
        failure = self._failure_counts.get(agent_id, 0)
        total = success + failure
        
        return {
            "execution_count": total,
            "success_rate": success / total if total > 0 else 0.0,
            "avg_latency_ms": sum(times) / len(times) if times else 0.0,
            "tool_usage": dict(self._tool_usage.get(agent_id, {})),
            "memory_usage": dict(self._memory_usage.get(agent_id, {}))
        }

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get overall system metrics."""
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        total_success = sum(self._success_counts.values())
        total_failure = sum(self._failure_counts.values())
        total = total_success + total_failure
        
        return {
            "uptime_seconds": uptime,
            "total_executions": total,
            "overall_success_rate": total_success / total if total > 0 else 0.0,
            "active_agents": list(self._execution_times.keys())
        }

_metrics: Optional[MedusaMetrics] = None

def get_medusa_metrics() -> MedusaMetrics:
    global _metrics
    if _metrics is None:
        _metrics = MedusaMetrics()
    return _metrics
