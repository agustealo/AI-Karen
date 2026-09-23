"""Durable queue contract for KAREN's background job execution."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from .base import Repository, RepositoryResult


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
    claim_token: Optional[str] = None


class QueueClient(Repository):
    """Canonical contract for durable queues."""

    @abstractmethod
    async def enqueue(self, item: QueueItem) -> RepositoryResult[str]:
        """Persist a work item."""

    @abstractmethod
    async def dequeue(
        self, queue: str, worker_id: str
    ) -> RepositoryResult[Optional[QueueItem]]:
        """Atomically claim the next available item for processing."""

    @abstractmethod
    async def ack(
        self,
        queue: str,
        item_id: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        """Complete an item only when the caller still owns its claim."""

    @abstractmethod
    async def nack(
        self,
        queue: str,
        item_id: str,
        error: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        """Retry or dead-letter an item only when the claim is still owned."""

    @abstractmethod
    async def health_check(self) -> RepositoryResult:
        """Return durable queue health status."""


__all__ = ["QueueItem", "QueueClient"]
