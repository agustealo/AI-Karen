"""Realtime observability metrics.

Instrumentation for realtime behavior using canonical KAREN observability utilities.
No console.log as architecture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.realtime.connection_state import ConnectionState
from ai_karen_engine.core.realtime.events import EventType


@dataclass
class RealtimeMetrics:
    connection_attempts: int = 0
    connection_failures: int = 0
    reconnect_count: int = 0
    subscription_count: int = 0
    subscription_failure_count: int = 0
    events_received: int = 0
    events_rejected: int = 0
    duplicate_events: int = 0
    presence_join: int = 0
    presence_leave: int = 0
    channel_join_latency_ms: float = 0.0
    last_event_at: Optional[datetime] = None
    metadata: List[Dict[str, Any]] = field(default_factory=list)

    def record_connection_attempt(self, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.connection_attempts += 1
        self.metadata.append(self._meta("connection_attempt", tenant_id))

    def record_connection_failure(self, reason: str, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.connection_failures += 1
        self.metadata.append(self._meta("connection_failure", tenant_id, reason=reason))

    def record_reconnect(self, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.reconnect_count += 1

    def record_subscription(self, topic_class: str, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.subscription_count += 1
        self.metadata.append(self._meta("subscription", tenant_id, topic_class=topic_class))

    def record_subscription_failure(self, topic_class: str, error_code: str, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.subscription_failure_count += 1
        self.metadata.append(self._meta("subscription_failure", tenant_id, topic_class=topic_class, error_code=error_code))

    def record_event_received(self, event_type: EventType, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.events_received += 1
        self.last_event_at = datetime.now(timezone.utc)
        self.metadata.append(self._meta("event_received", tenant_id, event_type=event_type.value))

    def record_event_rejected(self, reason: str, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.events_rejected += 1
        self.metadata.append(self._meta("event_rejected", tenant_id, reason=reason))

    def record_duplicate_event(self, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.duplicate_events += 1
        self.metadata.append(self._meta("duplicate_event", tenant_id))

    def record_presence_join(self, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.presence_join += 1
        self.metadata.append(self._meta("presence_join", tenant_id))

    def record_presence_leave(self, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.presence_leave += 1
        self.metadata.append(self._meta("presence_leave", tenant_id))

    def record_channel_join_latency(self, latency_ms: float, topic_class: str, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.channel_join_latency_ms = latency_ms
        self.metadata.append(self._meta("channel_join_latency", tenant_id, topic_class=topic_class, latency_ms=latency_ms))

    def _meta(
        self,
        status: str,
        tenant_id: Optional[uuid.UUID],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "status": status,
        }
        entry.update(kwargs)
        return entry
