"""Explicit no-op QueueClient implementation for isolated tests.

This class is never installed by production bootstrap. It exists only for
callers that deliberately inject a non-durable queue in tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.observability import instrument_repository
from ai_karen_engine.services.database.repositories.queue_client import QueueClient, QueueItem

logger = logging.getLogger(__name__)


class NoopQueueClient(QueueClient):
    """Test-only no-op queue client."""

    @instrument_repository(operation="enqueue", repository="NoopQueueClient")
    async def enqueue(self, item: QueueItem) -> RepositoryResult[str]:
        logger.debug("NoopQueueClient.enqueue id=%s queue=%s", item.id, item.queue)
        return RepositoryResult(success=True, data=item.id)

    @instrument_repository(operation="dequeue", repository="NoopQueueClient")
    async def dequeue(
        self, queue: str, worker_id: str
    ) -> RepositoryResult[Optional[QueueItem]]:
        logger.debug("NoopQueueClient.dequeue queue=%s worker=%s", queue, worker_id)
        return RepositoryResult(success=True, data=None)

    @instrument_repository(operation="renew_claim", repository="NoopQueueClient")
    async def renew_claim(
        self,
        queue: str,
        item_id: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        logger.debug(
            "NoopQueueClient.renew_claim queue=%s id=%s claim=%s",
            queue,
            item_id,
            claim_token,
        )
        return RepositoryResult(success=True, data=True)

    @instrument_repository(operation="ack", repository="NoopQueueClient")
    async def ack(
        self,
        queue: str,
        item_id: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        logger.debug(
            "NoopQueueClient.ack queue=%s id=%s claim=%s",
            queue,
            item_id,
            claim_token,
        )
        return RepositoryResult(success=True, data=True)

    @instrument_repository(operation="nack", repository="NoopQueueClient")
    async def nack(
        self,
        queue: str,
        item_id: str,
        error: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        logger.debug(
            "NoopQueueClient.nack queue=%s id=%s claim=%s error=%s",
            queue,
            item_id,
            claim_token,
            error,
        )
        return RepositoryResult(success=True, data=True)

    @instrument_repository(operation="health_check", repository="NoopQueueClient")
    async def health_check(self) -> RepositoryResult:
        return RepositoryResult(success=True, data={"status": "noop"})
