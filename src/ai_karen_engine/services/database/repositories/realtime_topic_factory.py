"""
Realtime topic registry.

Centralizes channel naming and tenant scoping so callers never
compose raw topic strings. All production topics are private and
tenant-aware.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RealtimeTopicFactory:
    """Factory for canonical private Realtime topics."""

    @staticmethod
    def user_topic(tenant_id: str, user_id: str) -> str:
        return f"tenant:{tenant_id}:user:{user_id}"

    @staticmethod
    def conversation_topic(tenant_id: str, conversation_id: str) -> str:
        return f"tenant:{tenant_id}:conversation:{conversation_id}"

    @staticmethod
    def execution_topic(tenant_id: str, execution_id: str) -> str:
        return f"tenant:{tenant_id}:execution:{execution_id}"

    @staticmethod
    def admin_topic(tenant_id: str) -> str:
        return f"tenant:{tenant_id}:admin"

    @staticmethod
    def is_private(topic: str) -> bool:
        return topic.startswith("tenant:")


__all__ = [
    "RealtimeTopicFactory",
]
