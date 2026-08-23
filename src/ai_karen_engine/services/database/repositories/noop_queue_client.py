"""
No-op QueueClient implementation.

Used when no durable queue backend is configured. All operations
succeed silently without side effects so runtime code does not
need to branch on configuration.
"""

from __future__ import annotations

import logging
from typing import Optional

from ai_karen_engine.services.database.repositories.queue_client import QueueClient, QueueItem
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.observability import instrument_repository

logger = logging.getLogger(__name__)


class NoopQueueClient(QueueClient):
    """No-op queue client."""

    @instrument_repository(operation="enqueue", repository="NoopQueueClient")
    async def enqueue(self, item: QueueItem) -> RepositoryResult[str]:
        logger.debug("NoopQueueClient.enqueue id=%s queue=%s", item.id, item.queue)
        return RepositoryResult(success=True, data=item.id)

    @instrument_repository(operation="dequeue", repository="NoopQueueClient")
    async def dequeue(self, queue: str, worker_id: str) -> RepositoryResult[Optional[QueueItem]]:
        logger.debug("NoopQueueClient.dequeue queue=%s worker=%s", queue, worker_id)
        return RepositoryResult(success=True, data=None)

    @instrument_repository(operation="ack", repository="NoopQueueClient")
    async def ack(self, queue: str, item_id: str) -> RepositoryResult[bool]:
        logger.debug("NoopQueueClient.ack queue=%s id=%s", queue, item_id)
        return RepositoryResult(success=True, data=True)

    @instrument_repository(operation="nack", repository="NoopQueueClient")
    async def nack(self, queue: str, item_id: str, error: str) -> RepositoryResult[bool]:
        logger.debug("NoopQueueClient.nack queue=%s id=%s error=%s", queue, item_id, error)
        return RepositoryResult(success=True, data=True)

    @instrument_repository(operation="health_check", repository="NoopQueueClient")
    async def health_check(self) -> RepositoryResult:
        return RepositoryResult(success=True, data={"status": "noop"})
