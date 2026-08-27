"""Redis-backed active episodic-frame state.

Redis owns only the bounded active frame. Durable episode/event history remains
PostgreSQL authority.
"""

from __future__ import annotations

from ai_karen_engine.core.memory.episodic import EpisodeFrame

from .redis_connection_manager import RedisConnectionManager, get_redis_manager


class RedisEpisodeStateStore:
    """Store one active episode frame inside the canonical Redis session record."""

    FIELD = "_memory_episode_frame"

    def __init__(
        self,
        redis_manager: RedisConnectionManager | None = None,
        *,
        ttl_seconds: int = 21600,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self.redis = redis_manager or get_redis_manager()
        self.ttl_seconds = int(ttl_seconds)

    async def load(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
    ) -> EpisodeFrame | None:
        if not session_id:
            return None
        session = await self.redis.get_session(tenant_id, user_id, session_id)
        if not isinstance(session, dict):
            return None
        raw = session.get(self.FIELD)
        if not isinstance(raw, dict):
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
        session = await self.redis.get_session(
            frame.tenant_id,
            frame.user_id,
            frame.session_id,
        )
        merged = dict(session or {})
        merged[self.FIELD] = frame.to_dict()
        return await self.redis.set_session(
            frame.tenant_id,
            frame.user_id,
            merged,
            frame.session_id,
            ttl_seconds=self.ttl_seconds,
        )

    async def clear(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
    ) -> bool:
        session = await self.redis.get_session(tenant_id, user_id, session_id)
        if not isinstance(session, dict) or self.FIELD not in session:
            return True
        merged = dict(session)
        merged.pop(self.FIELD, None)
        return await self.redis.set_session(
            tenant_id,
            user_id,
            merged,
            session_id,
            ttl_seconds=self.ttl_seconds,
        )


__all__ = ["RedisEpisodeStateStore"]
