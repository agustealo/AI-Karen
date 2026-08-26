from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import EventType
from .diagnostics_buffer import BoundedDiagnosticsBuffer, get_diagnostics_buffer
from .scorecard import build_scorecard


@dataclass(slots=True)
class RequestTrace:
    """A reconstructed request trace built from buffered stage events."""

    request_id: str | None
    correlation_id: str | None
    stages: list[dict[str, Any]] = field(default_factory=list)
    total_duration_ms: float | None = None
    status: str | None = None


def _group_by_request(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        key = event.get("request_id") or event.get("correlation_id") or "unknown"
        groups.setdefault(key, []).append(event)
    return groups


class DiagnosticsService:
    """Thin read-only service backing the admin diagnostics API.

    It holds no metric logic of its own; it reads the bounded diagnostics
    buffer and the metrics collector, and reconstructs request traces.
    """

    def __init__(self, buffer: BoundedDiagnosticsBuffer | None = None) -> None:
        self._buffer = buffer or get_diagnostics_buffer()

    def recent_events(
        self,
        *,
        correlation_id: str | None = None,
        event_type: str | None = None,
        status: str | None = None,
        provider: str | None = None,
        plugin: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        events = self._buffer.recent(limit * 4 if any([correlation_id, event_type, status, provider, plugin]) else limit)
        filtered: list[dict[str, Any]] = []
        for event in events:
            if correlation_id and event.get("correlation_id") != correlation_id:
                continue
            if event_type and event.get("event_type") != event_type:
                continue
            if status and event.get("status") != status:
                continue
            if provider and event.get("provider") != provider:
                continue
            if plugin and event.get("plugin_id") != plugin:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        return filtered

    def summary(self) -> dict[str, Any]:
        events = self._buffer.recent()
        scorecard = build_scorecard(events)
        return {
            "scorecard": scorecard.to_dict(),
            "buffered_events": len(events),
        }

    def request_traces(self, *, limit: int = 50) -> list[RequestTrace]:
        events = self._buffer.recent()
        grouped = _group_by_request(events)
        traces: list[RequestTrace] = []
        for _key, group in list(grouped.items())[-limit:]:
            duration_events = [
                e for e in group
                if isinstance(e.get("duration_ms"), (int, float))
                and e.get("event_type") in (
                    EventType.REQUEST_COMPLETED.value,
                    EventType.REQUEST_FAILED.value,
                )
            ]
            total_duration = (
                float(duration_events[-1]["duration_ms"])
                if duration_events
                else None
            )
            statuses = [e.get("status") for e in group if e.get("status")]
            traces.append(
                RequestTrace(
                    request_id=group[0].get("request_id"),
                    correlation_id=group[0].get("correlation_id"),
                    stages=group,
                    total_duration_ms=total_duration,
                    status=statuses[-1] if statuses else None,
                )
            )
        return traces

    def provider_breakdown(self) -> list[dict[str, Any]]:
        events = self._buffer.recent()
        providers: dict[str, dict[str, Any]] = {}
        for event in events:
            provider = event.get("provider")
            if not provider:
                continue
            bucket = providers.setdefault(
                provider, {"provider": provider, "requests": 0, "failures": 0, "fallbacks": 0}
            )
            et = event.get("event_type")
            if et in (
                EventType.PROVIDER_EXECUTION_COMPLETED.value,
                EventType.PROVIDER_EXECUTION_FAILED.value,
            ):
                bucket["requests"] += 1
            if et == EventType.PROVIDER_EXECUTION_FAILED.value:
                bucket["failures"] += 1
            if et == EventType.PROVIDER_FALLBACK.value:
                bucket["fallbacks"] += 1
        return list(providers.values())


def get_diagnostics_service() -> DiagnosticsService:
    return DiagnosticsService()
