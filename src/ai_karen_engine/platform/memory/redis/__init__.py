"""Canonical Redis platform adapter surface for bounded memory state.

Redis is infrastructure for STM/session continuity. It is not a durable memory
source of truth and does not expose a fake general-purpose recall backend.
"""

from .redis_connection_manager import (
    RedisConnectionManager,
    get_redis_manager,
    initialize_redis_manager,
    shutdown_redis_manager,
)
from .stm_adapter import RedisSTMAdapter

__all__ = [
    "RedisConnectionManager",
    "RedisSTMAdapter",
    "get_redis_manager",
    "initialize_redis_manager",
    "shutdown_redis_manager",
]
