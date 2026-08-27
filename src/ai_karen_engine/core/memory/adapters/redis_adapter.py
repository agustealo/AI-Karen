"""Deprecated compatibility wrapper for Redis-backed STM.

Redis is bounded/session infrastructure, not a general memory retrieval authority.
Production recall belongs to NeuroRecall. New code must use ``RedisSTMAdapter``
through the canonical STM contract.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

from ai_karen_engine.core.memory.types import MemoryEntry
from ai_karen_engine.platform.memory.redis import RedisSTMAdapter


class RedisMemoryAdapter(RedisSTMAdapter):
    """Compatibility name for Redis STM; general recall methods are retired."""

    def __init__(self, redis_client=None, redis_connection_manager=None, **kwargs):
        del redis_client
        warnings.warn(
            "RedisMemoryAdapter is deprecated; use RedisSTMAdapter",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(redis_manager=redis_connection_manager, **kwargs)

    async def retrieve(self, *args, **kwargs) -> list[MemoryEntry]:
        del args, kwargs
        raise RuntimeError("Redis does not own general recall; use NeuroRecall")

    async def retrieve_by_id(self, *args, **kwargs) -> MemoryEntry | None:
        del args, kwargs
        raise RuntimeError("Redis does not own general recall; use NeuroRecall")

    async def retrieve_batch(
        self,
        entry_ids: Sequence[str],
        *args,
        **kwargs,
    ) -> list[MemoryEntry]:
        del entry_ids, args, kwargs
        raise RuntimeError("Redis does not own general recall; use NeuroRecall")


__all__ = ["RedisMemoryAdapter"]
