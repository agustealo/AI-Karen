"""Compatibility shim for core.memory.redis_connection_manager.

Canonical implementation lives under ai_karen_engine.platform.memory.redis.redis_connection_manager.
"""

from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
    RedisConnectionManager,
    get_redis_manager,
    initialize_redis_manager,
    shutdown_redis_manager,
    REDIS_AVAILABLE,
)

__all__ = [
    "RedisConnectionManager",
    "get_redis_manager",
    "initialize_redis_manager",
    "shutdown_redis_manager",
    "REDIS_AVAILABLE",
]
