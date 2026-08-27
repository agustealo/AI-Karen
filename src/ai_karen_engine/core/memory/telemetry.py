"""Memory runtime telemetry counters.

Keeps compatibility metrics observable without making the runtime inherit from
legacy bookkeeping. The counters are intentionally process-local compatibility
state; production metrics export remains owned by the runtime observability
stack.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from ai_karen_engine.core.runtime.resilience import (
    get_feature_flags,
    get_resilience_health_monitor,
)


class MemoryRuntimeMetrics:
    """Small thread-safe counter registry for memory runtime compatibility metrics."""

    _DEFAULTS = {
        "interactions_processed": 0,
        "signals_extracted": 0,
        "signals_admitted": 0,
        "ledger_writes": 0,
        "projection_failures": 0,
        "recall_requests": 0,
        "recall_hits": 0,
        "shadow_mode_runs": 0,
    }

    def __init__(self) -> None:
        self._lock = Lock()
        self._values = dict(self._DEFAULTS)

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._values:
            raise KeyError(f"unknown memory metric: {name}")
        with self._lock:
            self._values[name] += int(amount)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)


memory_metrics = MemoryRuntimeMetrics()


def get_memory_metrics() -> dict[str, Any]:
    """Return compatibility counters plus canonical resilience state."""
    return {
        "memory_runtime": memory_metrics.snapshot(),
        "memory_learning_enabled": get_feature_flags().is_enabled(
            "memory_learning_enabled"
        ),
        "resilience_health": get_resilience_health_monitor().get_health_status(),
    }


__all__ = ["MemoryRuntimeMetrics", "get_memory_metrics", "memory_metrics"]
