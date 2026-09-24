"""Canonical durable queue accessor.

Production queue authority is PostgreSQL. Supabase platform bootstrap must not
advertise a no-op queue as an available capability.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from ai_karen_engine.persistence.repositories.postgres_queue_client import (
    PostgresQueueClient,
)
from ai_karen_engine.services.database.repositories.queue_client import QueueItem

logger = logging.getLogger(__name__)

_queue_client: PostgresQueueClient | None = None


def get_queue_client() -> PostgresQueueClient:
    """Return the canonical durable PostgreSQL queue client."""
    global _queue_client
    if _queue_client is None:
        _queue_client = PostgresQueueClient()
    return _queue_client


def is_queue_available() -> bool:
    """Return whether a production queue implementation is configured.

    This reports implementation availability, not database/schema health.
    Call ``health_check`` for readiness.
    """
    return True


async def enqueue(queue: str, payload: Dict[str, Any], **kwargs: Any) -> str | None:
    """Persist a durable work item and return its ID only on real success."""
    item_id = kwargs.pop("id", None) or str(uuid.uuid4())
    item = QueueItem(id=item_id, queue=queue, payload=payload, **kwargs)
    result = await get_queue_client().enqueue(item)
    if not result.success:
        logger.error(
            "queue.enqueue.failed",
            extra={"queue": queue, "item_id": item_id, "error": result.error},
        )
        return None
    return result.data


__all__ = ["get_queue_client", "is_queue_available", "enqueue"]
