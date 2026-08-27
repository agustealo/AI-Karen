"""Redis backing adapter for canonical bounded STM.

Core owns STM semantics through ``STMPort``. This adapter owns Redis key layout,
TTL application, serialization, and degraded fallback behavior through the
canonical Redis connection manager.
"""

from __future__ import annotations

import json
from typing import Any

from ai_karen_engine.config.memory import get_memory_runtime_settings
from ai_karen_engine.core.memory.episodic import EpisodeFrame
from ai_karen_engine.core.memory.stm import STMScope, STMSlot, STMPort

from .redis_connection_manager import RedisConnectionManager, get_redis_manager


class RedisSTMAdapter(STMPort):
    """Store bounded STM slots as independent atomic Redis keys."""

    def __init__(
        self,
        redis_manager: RedisConnectionManager | None = None,
        *,
        default_ttl_seconds: int | None = None,
        max_slot_bytes: int | None = None,
    ) -> None:
        settings = get_memory_runtime_settings()
        self.redis = redis_manager or get_redis_manager()
        self.default_ttl_seconds = int(
            default_ttl_seconds or settings.stm_session_ttl_seconds
        )
        self.max_slot_bytes = int(max_slot_bytes or settings.stm_max_slot_bytes)
        if self.default_ttl_seconds < 60:
            raise ValueError("STM default TTL must be at least 60 seconds")
        if self.max_slot_bytes < 1024:
            raise ValueError("STM slot size limit must be at least 1024 bytes")

    def _key(self, scope: STMScope, slot: STMSlot) -> str:
        scope.validate()
        return (
            f"{self.redis.prefix}:{scope.tenant_id}:{scope.user_id}:"
            f"session:{scope.session_id}:stm:{slot.value}"
        )

    async def get_slot(
        self,
        *,
        scope: STMScope,
        slot: STMSlot,
    ) -> dict[str, Any] | None:
        raw = await self.redis.get(self._key(scope, slot))
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    async def put_slot(
        self,
        *,
        scope: STMScope,
        slot: STMSlot,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        if not isinstance(value, dict):
            raise TypeError("STM slot value must be a dictionary")
        payload = json.dumps(value, default=str, separators=(",", ":"))
        payload_size = len(payload.encode("utf-8"))
        if payload_size > self.max_slot_bytes:
            raise ValueError(
                f"STM slot payload exceeds configured limit: "
                f"{payload_size}>{self.max_slot_bytes} bytes"
            )
        ttl = int(ttl_seconds or self.default_ttl_seconds)
        if ttl < 1:
            raise ValueError("STM TTL must be positive")
        return await self.redis.set(self._key(scope, slot), payload, ex=ttl)

    async def delete_slot(self, *, scope: STMScope, slot: STMSlot) -> bool:
        return bool(await self.redis.delete(self._key(scope, slot)))

    def degraded(self) -> bool:
        return self.redis.is_degraded()

    # Narrow compatibility surface for MemoryFormationService's current
    # EpisodeStateStore protocol. The episode remains a Core semantic object;
    # Redis only stores it through the canonical STM slot.
    async def load(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
    ) -> EpisodeFrame | None:
        scope = STMScope(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        raw = await self.get_slot(scope=scope, slot=STMSlot.ACTIVE_EPISODE)
        if raw is None:
            return None
        try:
            frame = EpisodeFrame.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None
        if (
            frame.tenant_id != tenant_id
            or frame.user_id != user_id
            or frame.session_id != session_id
        ):
            return None
        return frame

    async def save(self, frame: EpisodeFrame) -> bool:
        scope = STMScope(
            tenant_id=frame.tenant_id,
            user_id=frame.user_id,
            session_id=frame.session_id,
        )
        return await self.put_slot(
            scope=scope,
            slot=STMSlot.ACTIVE_EPISODE,
            value=frame.to_dict(),
        )

    async def clear(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
    ) -> bool:
        scope = STMScope(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        key = self._key(scope, STMSlot.ACTIVE_EPISODE)
        if not await self.redis.exists(key):
            return True
        return bool(await self.redis.delete(key))


__all__ = ["RedisSTMAdapter"]
