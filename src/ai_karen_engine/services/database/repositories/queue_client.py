"""
Durable queue contract for KAREN's background job execution.

QueueClient is the canonical abstraction for enqueueing and
processing durable work items. The default implementation is
no-op; concrete backends (PostgreSQL, Redis, Supabase Storage,
etc.) implement this interface.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from .base import Repository, RepositoryResult

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """Canonical durable queue item."""

    id: str
    queue: str
    payload: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    available_at: datetime = field(default_factory=datetime.utcnow)
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None


class QueueClient(Repository):
    """Canonical contract for durable queues."""

    @abstractmethod
    async def enqueue(self, item: QueueItem) -> RepositoryResult[str]:
        """Enqueue a durable work item."""

    @abstractmethod
    async def dequeue(self, queue: str, worker_id: str) -> RepositoryResult[Optional[QueueItem]]:
        """Claim the next available item for processing."""

    @abstractmethod
    async def ack(self, queue: str, item_id: str) -> RepositoryResult[bool]:
        """Mark a dequeued item as completed."""

    @abstractmethod
    async def nack(self, queue: str, item_id: str, error: str) -> RepositoryResult[bool]:
        """Return an item to the queue or move it to the dead-letter queue."""

    @abstractmethod
    async def health_check(self) -> RepositoryResult:
        """Return queue health status."""


__all__ = [
    "QueueItem",
    "QueueClient",
]
