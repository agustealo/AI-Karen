"""Compatibility shim for the canonical Redis STM adapter.

Episode continuity is STM semantics. New code must import ``RedisSTMAdapter``
from ``ai_karen_engine.platform.memory.redis``. This alias preserves temporary
compatibility while callers and tests migrate.
"""

from __future__ import annotations

import warnings

from .stm_adapter import RedisSTMAdapter

warnings.warn(
    "RedisEpisodeStateStore is deprecated; use RedisSTMAdapter",
    DeprecationWarning,
    stacklevel=2,
)

RedisEpisodeStateStore = RedisSTMAdapter

__all__ = ["RedisEpisodeStateStore"]
