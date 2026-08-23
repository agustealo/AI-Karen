"""Durable queue contracts.

Platform-agnostic durable job abstraction.
No Supabase-specific imports here; backend implementation can wire to pgmq.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class QueueType(str, Enum):
    MEMORY_CONSOLIDATION = "memory.consolidation"
    MEMORY_EMBEDDING = "memory.embedding"
    MEMORY_REEMBEDDING = "memory.reembedding"
    ARTIFACT_RECONCILE = "artifact.reconcile"
    ARTIFACT_CLEANUP = "artifact.cleanup"
    RUNTIME_POST_EXECUTION = "runtime.post_execution"
    NOTIFICATION_DELIVERY = "notification.delivery"
    ANALYTICS_ROLLUP = "analytics.rollup"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class QueueMessage:
    message_id: uuid.UUID = field(default_factory=uuid.uuid4)
    queue: str = ""
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    attempt: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    available_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.queue:
            raise ValueError("queue is required")
        if not self.type:
            raise ValueError("type is required")


@dataclass(frozen=True)
class QueueDelivery:
    message: QueueMessage
    status: DeliveryStatus = DeliveryStatus.PENDING
    received_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class DurableQueue:
    """Abstract durable queue interface.

    Backend implementation may use pgmq, Redis Streams, or another store.
    """

    def enqueue(self, message: QueueMessage) -> uuid.UUID:
        raise NotImplementedError

    def receive(self, queue: str, limit: int = 1) -> List[QueueDelivery]:
        raise NotImplementedError

    def ack(self, message_id: uuid.UUID) -> bool:
        raise NotImplementedError

    def retry(self, message_id: uuid.UUID, delay_seconds: float = 0) -> bool:
        raise NotImplementedError

    def archive(self, message_id: uuid.UUID) -> bool:
        raise NotImplementedError

    def health(self) -> Dict[str, Any]:
        raise NotImplementedError
