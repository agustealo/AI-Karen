"""
Queue client accessor for runtime code.

Provides a single importable entrypoint for enqueueing and
processing durable work items without importing queue
implementations directly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.integrations.supabase_client import get_supabase_platform
from ai_karen_engine.services.database.repositories.queue_client import QueueItem

logger = logging.getLogger(__name__)


def get_queue_client() -> Optional[Any]:
    """Return the configured QueueClient, or None if unavailable."""
    platform = get_supabase_platform()
    return platform.queue


def is_queue_available() -> bool:
    """Return True if a queue client is configured."""
    return get_queue_client() is not None


async def enqueue(queue: str, payload: Dict[str, Any], **kwargs: Any) -> Optional[str]:
    """Enqueue a work item if a queue client is configured."""
    client = get_queue_client()
    if client is None:
        logger.debug("Queue enqueue skipped: client not configured")
        return None
    item_id = kwargs.pop("id", None) or str(__import__("uuid").uuid4())
    item = QueueItem(id=item_id, queue=queue, payload=payload, **kwargs)
    result = await client.enqueue(item)
    return result.data if result.success else None


__all__ = [
    "get_queue_client",
    "is_queue_available",
    "enqueue",
]
