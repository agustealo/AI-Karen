"""In-memory fake queue implementation for tests only.

Provides a deterministic fake for unit and integration tests.
Not for production use.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.queues.contracts import (
    DeliveryStatus,
    DurableQueue,
    QueueDelivery,
    QueueMessage,
)
from ai_karen_engine.core.queues.retry import RetryPolicy, compute_retry


@dataclass
class FakeQueueEntry:
    message: QueueMessage
    delivery: QueueDelivery
    retry_policy: RetryPolicy


class FakeDurableQueue(DurableQueue):
    """Deterministic in-memory queue for tests."""

    def __init__(self, default_retry_policy: Optional[RetryPolicy] = None) -> None:
        self._store: Dict[uuid.UUID, FakeQueueEntry] = {}
        self._queue_index: Dict[str, List[uuid.UUID]] = {}
        self._default_retry_policy = default_retry_policy or RetryPolicy()
        self._lock = asyncio.Lock()

    async def enqueue(self, message: QueueMessage) -> uuid.UUID:
        async with self._lock:
            delivery = QueueDelivery(message=message, status=DeliveryStatus.PENDING)
            entry = FakeQueueEntry(
                message=message,
                delivery=delivery,
                retry_policy=self._default_retry_policy,
            )
            self._store[message.message_id] = entry
            self._queue_index.setdefault(message.queue, []).append(message.message_id)
            return message.message_id

    async def receive(self, queue: str, limit: int = 1) -> List[QueueDelivery]:
        async with self._lock:
            ids = self._queue_index.get(queue, [])
            results: List[QueueDelivery] = []
            for mid in ids[:limit]:
                entry = self._store.get(mid)
                if entry and entry.delivery.status == DeliveryStatus.PENDING:
                    entry.delivery = QueueDelivery(
                        message=entry.delivery.message,
                        status=DeliveryStatus.IN_PROGRESS,
                        received_at=datetime.now(timezone.utc),
                        completed_at=entry.delivery.completed_at,
                        error=entry.delivery.error,
                    )
                    results.append(entry.delivery)
            return results

    async def ack(self, message_id: uuid.UUID) -> bool:
        async with self._lock:
            entry = self._store.get(message_id)
            if not entry:
                return False
            entry.delivery = QueueDelivery(
                message=entry.delivery.message,
                status=DeliveryStatus.COMPLETED,
                received_at=entry.delivery.received_at,
                completed_at=datetime.now(timezone.utc),
                error=entry.delivery.error,
            )
            return True

    async def retry(self, message_id: uuid.UUID, delay_seconds: float = 0) -> bool:
        async with self._lock:
            entry = self._store.get(message_id)
            if not entry:
                return False
            entry.message = QueueMessage(
                message_id=entry.message.message_id,
                queue=entry.message.queue,
                tenant_id=entry.message.tenant_id,
                type=entry.message.type,
                payload=entry.message.payload,
                correlation_id=entry.message.correlation_id,
                attempt=entry.message.attempt + 1,
                created_at=entry.message.created_at,
                available_at=entry.message.available_at,
            )
            result = compute_retry(entry.retry_policy, entry.message.attempt, entry.delivery.error or "")
            if result.dead_letter:
                entry.delivery = QueueDelivery(
                    message=entry.message,
                    status=DeliveryStatus.DEAD_LETTERED,
                    received_at=entry.delivery.received_at,
                    completed_at=datetime.now(timezone.utc),
                    error=entry.delivery.error,
                )
            else:
                entry.delivery = QueueDelivery(
                    message=entry.message,
                    status=DeliveryStatus.PENDING,
                    received_at=None,
                    completed_at=None,
                    error=entry.delivery.error,
                )
            return True

    async def archive(self, message_id: uuid.UUID) -> bool:
        async with self._lock:
            entry = self._store.get(message_id)
            if not entry:
                return False
            entry.delivery = QueueDelivery(
                message=entry.delivery.message,
                status=DeliveryStatus.ARCHIVED,
                received_at=entry.delivery.received_at,
                completed_at=datetime.now(timezone.utc),
                error=entry.delivery.error,
            )
            return True

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "messages": len(self._store),
            "queues": list(self._queue_index.keys()),
        }
