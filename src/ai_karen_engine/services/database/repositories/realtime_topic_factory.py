"""Compatibility entrypoint for the canonical realtime topic registry.

Preserves legacy static method signatures. Topic syntax is not authorization;
the authenticated runtime must still authorize the resource and principal.
"""

from __future__ import annotations

from ai_karen_engine.core.realtime.topics import (
    RealtimeTopicFactory as CanonicalRealtimeTopicFactory,
    is_private_topic,
)


class RealtimeTopicFactory:
    """Legacy static API delegating all topic rules to the core registry."""

    @staticmethod
    def user_topic(tenant_id: str, user_id: str) -> str:
        return CanonicalRealtimeTopicFactory(tenant_id).user_topic(user_id)

    @staticmethod
    def conversation_topic(tenant_id: str, conversation_id: str) -> str:
        return CanonicalRealtimeTopicFactory(tenant_id).conversation_topic(conversation_id)

    @staticmethod
    def execution_topic(tenant_id: str, execution_id: str) -> str:
        return CanonicalRealtimeTopicFactory(tenant_id).execution_topic(execution_id)

    @staticmethod
    def admin_topic(tenant_id: str) -> str:
        return CanonicalRealtimeTopicFactory(tenant_id).admin_topic()

    @staticmethod
    def is_private(topic: str) -> bool:
        return is_private_topic(topic)


__all__ = ["RealtimeTopicFactory"]
