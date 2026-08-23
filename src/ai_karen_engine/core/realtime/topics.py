"""Realtime topic registry.

Centralizes Realtime topic names with deterministic formatting.
No arbitrary browser-supplied prefixes allowed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional


_TOPIC_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _validate_uuid(value: str, name: str) -> uuid.UUID:
    if not _TOPIC_ID_PATTERN.match(value):
        raise ValueError(f"{name} must be a valid UUID, got {value!r}")
    return uuid.UUID(value)


@dataclass(frozen=True)
class RealtimeTopicFactory:
    """Canonical topic name factory.

    Canonical topic format:
        tenant:{tenant_id}:user:{user_id}
        tenant:{tenant_id}:conversation:{conversation_id}
        tenant:{tenant_id}:execution:{execution_id}
        tenant:{tenant_id}:notifications
    """

    tenant_id: str
    _validated_tenant: uuid.UUID = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_validated_tenant", _validate_uuid(self.tenant_id, "tenant_id"))

    def user_topic(self, user_id: str) -> str:
        uid = _validate_uuid(user_id, "user_id")
        return f"tenant:{self._validated_tenant}:user:{uid}"

    def conversation_topic(self, conversation_id: str) -> str:
        cid = _validate_uuid(conversation_id, "conversation_id")
        return f"tenant:{self._validated_tenant}:conversation:{cid}"

    def execution_topic(self, execution_id: str) -> str:
        eid = _validate_uuid(execution_id, "execution_id")
        return f"tenant:{self._validated_tenant}:execution:{eid}"

    def tenant_notifications_topic(self) -> str:
        return f"tenant:{self._validated_tenant}:notifications"

    def admin_topic(self) -> str:
        return f"tenant:{self._validated_tenant}:admin"

    def resolve_topic(self, topic: str) -> Optional[str]:
        """Validate and normalize a topic string.

        Returns the normalized topic if valid, None if invalid.
        """
        if not isinstance(topic, str):
            return None
        parts = topic.split(":")
        if len(parts) not in (3, 4):
            return None
        prefix = parts[0]
        if prefix != "tenant":
            return None
        if not _TOPIC_ID_PATTERN.match(parts[1]):
            return None
        kind = parts[2]
        valid_kinds = {"user", "conversation", "execution", "notifications", "admin"}
        if kind not in valid_kinds:
            return None
        if kind in {"user", "conversation", "execution"}:
            if len(parts) != 4 or not _TOPIC_ID_PATTERN.match(parts[3]):
                return None
        return topic
