from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import EventType


@dataclass(slots=True)
class BetaScorecard:
    """Beta flight instrument panel.

    Canonical operational summary. Not an analytics product; a coarse view of
    request health for beta operation.
    """

    requests: int = 0
    successes: int = 0
    failures: int = 0
    degraded_requests: int = 0

    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None

    provider_failure_rate: float | None = None
    fallback_rate: float | None = None
    persistence_failure_rate: float | None = None
    extension_failure_rate: float | None = None

    memory_recall_latency_p50_ms: float | None = None

    success_rate: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.requests > 0:
            self.success_rate = self.successes / self.requests

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "success_rate": self.success_rate,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "provider_failure_rate": self.provider_failure_rate,
            "fallback_rate": self.fallback_rate,
            "persistence_failure_rate": self.persistence_failure_rate,
            "extension_failure_rate": self.extension_failure_rate,
            "memory_recall_latency_p50_ms": self.memory_recall_latency_p50_ms,
            "degraded_request_rate": (
                (self.degraded_requests / self.requests) if self.requests else None
            ),
        }


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def build_scorecard(events: list[Any]) -> BetaScorecard:
    """Derive a scorecard from a sequence of ExecutionEvent or event dicts."""
    request_latencies: list[float] = []
    recall_latencies: list[float] = []
    provider_failures = 0
    provider_total = 0
    fallback_events = 0
    persistence_failures = 0
    persistence_total = 0
    extension_failures = 0
    extension_total = 0

    for item in events:
        event_type = item.event_type if hasattr(item, "event_type") else item.get("event_type")
        event_type = getattr(event_type, "value", event_type)
        duration = item.duration_ms if hasattr(item, "duration_ms") else item.get("duration_ms")

        if event_type in (EventType.REQUEST_COMPLETED.value, EventType.REQUEST_FAILED.value):
            if isinstance(duration, (int, float)):
                request_latencies.append(float(duration))
            if event_type == EventType.REQUEST_FAILED.value:
                continue

        if event_type == EventType.MEMORY_RECALL_COMPLETED.value and isinstance(duration, (int, float)):
            recall_latencies.append(float(duration))

        if event_type in (
            EventType.PROVIDER_EXECUTION_COMPLETED.value,
            EventType.PROVIDER_EXECUTION_FAILED.value,
        ):
            provider_total += 1
            if event_type == EventType.PROVIDER_EXECUTION_FAILED.value:
                provider_failures += 1

        if event_type == EventType.PROVIDER_FALLBACK.value:
            fallback_events += 1

        if event_type in (
            EventType.PERSISTENCE_COMPLETED.value,
            EventType.PERSISTENCE_FAILED.value,
        ):
            persistence_total += 1
            if event_type == EventType.PERSISTENCE_FAILED.value:
                persistence_failures += 1

        if event_type in (
            EventType.EXTENSION_EXECUTION_COMPLETED.value,
            EventType.EXTENSION_EXECUTION_FAILED.value,
        ):
            extension_total += 1
            if event_type == EventType.EXTENSION_EXECUTION_FAILED.value:
                extension_failures += 1

    request_latencies.sort()
    recall_latencies.sort()

    return BetaScorecard(
        requests=len(request_latencies),
        p50_latency_ms=_percentile(request_latencies, 50),
        p95_latency_ms=_percentile(request_latencies, 95),
        provider_failure_rate=(provider_failures / provider_total) if provider_total else None,
        fallback_rate=(fallback_events / provider_total) if provider_total else None,
        persistence_failure_rate=(persistence_failures / persistence_total) if persistence_total else None,
        extension_failure_rate=(extension_failures / extension_total) if extension_total else None,
        memory_recall_latency_p50_ms=_percentile(recall_latencies, 50),
    )
