"""Best-effort internal inbox invalidation, never notification or delivery truth.

Only committed repository changes may call this function. Redis is a wake-up
hint; the authenticated PostgreSQL projection remains the sole data authority.
This is not a browser event envelope or a durable queue.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from threading import Lock
from uuid import UUID

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


class InboxInvalidationUnavailable(RuntimeError):
    """No authorized, verified broker wait could complete."""


# Per-process admission only, not delivery state or a distributed lock.
# Never queue waiters or consume all shared Redis connections.
_waiters: set[str] = set()
_waiters_lock = Lock()


async def wait_for_inbox_invalidation(
    *, tenant_id: str, user_id: str,
    disconnected: Callable[[], Awaitable[bool]],
    correlation_id: str | None = None,
) -> bool:
    """One bounded owner wait. True is a hint, False a verified idle window.

    The service owns principal authorization before and after this call.
    No subscriptions, broker payloads or user-selected channels leave it.
    """
    channel = None
    reserved = False
    reason = "configuration"
    # Correlation is diagnostic only, never part of admission or authorization.
    # Do not copy arbitrary caller-supplied header values into broker logs.
    try:
        trace_id = str(UUID(correlation_id)) if correlation_id else None
    except (TypeError, ValueError, AttributeError):
        trace_id = None
    trace = {"correlation_id": trace_id} if trace_id else {}
    try:
        settings = get_runtime_settings()
        if (
            settings.features.enable_communications_invalidation is not True
            or settings.features.enable_communications_invalidation_wait is not True
        ):
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")
        wait = settings.timeouts.communications_invalidation_wait_seconds
        limit = settings.timeouts.communications_invalidation_max_waiters
        budget = settings.timeouts.communications_invalidation_timeout_ms
        if (
            type(wait) is not int or not 1 <= wait <= 15
            or type(limit) is not int or not 1 <= limit <= 4
            or type(budget) is not int or not 1 <= budget <= 1000
        ):
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")

        from ai_karen_engine.platform.memory.redis import get_redis_manager

        reason = "manager_unavailable"
        manager = get_redis_manager()
        client = manager.client
        if client is None or manager.is_degraded():
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")
        reason = "owner_scope"
        channel = inbox_invalidation_channel(
            prefix=manager.prefix, tenant_id=tenant_id, user_id=user_id,
        )
        capacity = min(limit, manager.max_connections - 2)
        with _waiters_lock:
            if channel in _waiters:
                reason = "duplicate_owner"
                raise InboxInvalidationUnavailable("Communications invalidation unavailable")
            if len(_waiters) >= capacity:
                reason = "capacity"
                raise InboxInvalidationUnavailable("Communications invalidation unavailable")
            _waiters.add(channel)
            reserved = True

        reason = "disconnect_check"
        if await disconnected():
            reason = "client_disconnected"
            raise InboxInvalidationUnavailable("Communications invalidation unavailable")
        # A subscription command alone is not evidence that Redis admitted it.
        # Await the exact acknowledgment, and reject reconnect/foreign frames.
        loop = asyncio.get_running_loop()
        reason = "subscribe"
        async with client.pubsub(ignore_subscribe_messages=False) as subscription:
            async with asyncio.timeout(budget / 1000):
                await subscription.subscribe(channel)
                reason = "subscribe_ack"
                ack = await subscription.get_message(timeout=budget / 1000)
                if not (
                    isinstance(ack, dict) and ack.get("type") == "subscribe"
                    and ack.get("channel") == channel and type(ack.get("data")) is int
                    and ack["data"] == 1
                ):
                    raise InboxInvalidationUnavailable("Communications invalidation unavailable")
            logger.info("communications.invalidation.wait_admitted", extra=trace)
            deadline = loop.time() + wait
            async with asyncio.timeout(wait + budget / 1000):
                while True:
                    reason = "disconnect_check"
                    if await disconnected():
                        reason = "client_disconnected"
                        raise InboxInvalidationUnavailable("Communications invalidation unavailable")
                    reason = "manager_unavailable"
                    if manager.is_degraded():
                        raise InboxInvalidationUnavailable("Communications invalidation unavailable")
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        reason = "subscription_cleanup"
                        logger.info("communications.invalidation.wait_idle", extra=trace)
                        return False
                    reason = "broker_receive"
                    message = await subscription.get_message(timeout=min(remaining, 0.25))
                    if message is None:
                        continue
                    if (
                        isinstance(message, dict) and message.get("type") == "message"
                        and message.get("channel") == channel
                        and message.get("data") == INBOX_INVALIDATION_SIGNAL
                    ):
                        reason = "subscription_cleanup"
                        logger.info("communications.invalidation.wait_signal_observed", extra=trace)
                        return True
                    reason = "unexpected_frame"
                    raise InboxInvalidationUnavailable("Communications invalidation unavailable")
    except asyncio.CancelledError:
        logger.info("communications.invalidation.wait_cancelled", extra=trace)
        raise
    except Exception as exc:
        logger.warning("communications.invalidation.wait_unavailable reason=%s", reason, extra={
            **trace, "reason": reason, "error_type": type(exc).__name__,
        })
        raise InboxInvalidationUnavailable("Communications invalidation unavailable") from None
    finally:
        if reserved:
            with _waiters_lock:
                _waiters.discard(channel)
