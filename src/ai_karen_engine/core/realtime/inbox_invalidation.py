"""Best-effort internal inbox invalidation, never notification or delivery truth.

Only committed repository changes may call this function. Redis is a wake-up
hint; the authenticated PostgreSQL projection remains the sole data authority.
This is not a browser event envelope or a durable queue.
"""
from __future__ import annotations

import asyncio
import logging
import re

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.realtime.topics import RealtimeTopicFactory

logger = logging.getLogger(__name__)

# Versioned internal wire signal. No record, content, count, revision or secret.
INBOX_INVALIDATION_SIGNAL = "communications.inbox.changed.v1"
_PREFIX = re.compile(r"[A-Za-z0-9_-]{1,64}")


def inbox_invalidation_channel(*, prefix: str, tenant_id: str, user_id: str) -> str:
    """Exact owner channel; never authorize a browser-provided topic."""
    if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
        raise ValueError("Invalid Redis namespace")
    topic = RealtimeTopicFactory(tenant_id).user_topic(user_id)
    return f"{prefix}:communications:inbox:{topic}"


async def publish_inbox_invalidation(*, tenant_id: str, user_id: str) -> None:
    """Publish after commit; an outage cannot reverse a durable receipt.

    No initialization, retry, destructive queue or process-local fallback.
    A broker acknowledgment does not establish any consumer delivery.
    """
    try:
        settings = get_runtime_settings()
        if settings.features.enable_communications_invalidation is not True:
            return
        budget = settings.timeouts.communications_invalidation_timeout_ms
        if type(budget) is not int or not 1 <= budget <= 1000:
            raise ValueError("Invalid Communications invalidation timeout")

        # Reuse the one application-owned Redis connection manager. The
        # memory-cache fallback is deliberately not used for invalidations.
        from ai_karen_engine.platform.memory.redis import get_redis_manager

        manager = get_redis_manager()
        channel = inbox_invalidation_channel(
            prefix=manager.prefix, tenant_id=tenant_id, user_id=user_id,
        )
        client = manager.client
        if client is None or manager.is_degraded():
            logger.warning("communications.invalidation.unavailable")
            return
        count = await asyncio.wait_for(
            client.publish(channel, INBOX_INVALIDATION_SIGNAL),
            timeout=budget / 1000,
        )
        if type(count) is not int or count < 0:
            raise RuntimeError("Unverified broker acknowledgment")
        logger.info("communications.invalidation.broker_acknowledged", extra={
            "tenant_id": tenant_id, "user_id": user_id,
            "broker_subscriber_count": count,
        })
    except asyncio.CancelledError:
        # Never swallow task cancellation. The database commit already happened.
        raise
    except Exception as exc:
        logger.warning("communications.invalidation.unavailable", extra={
            "error_type": type(exc).__name__,
        })
