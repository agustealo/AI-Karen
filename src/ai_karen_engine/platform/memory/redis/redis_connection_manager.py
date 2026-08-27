"""
Redis Connection Manager

Provides graceful Redis connection handling with:
- Connection pooling and health monitoring
- Automatic reconnection with exponential backoff
- Degraded mode operation when Redis is unavailable
- Proper connection cleanup and resource management
"""

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    import redis.asyncio as redis
    from redis.asyncio import ConnectionPool, Redis

    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    ConnectionPool = None
    Redis = None
    REDIS_AVAILABLE = False

    class _RedisExc(Exception):
        pass

    ConnectionError = TimeoutError = RedisError = _RedisExc
else:
    pass

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.resilience.connection_health_manager import (
    ConnectionType,
    get_connection_health_manager,
)

logger = get_logger(__name__)


class RedisConnectionManager:
    """
    Manages Redis connections with health monitoring and graceful degradation.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        max_connections: int = 10,
        retry_on_timeout: bool = True,
        socket_keepalive: bool = True,
        socket_keepalive_options: Optional[Dict[str, int]] = None,
        health_check_interval: int = 30,
        prefix: str = "kari",
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.max_connections = max_connections
        self.retry_on_timeout = retry_on_timeout
        self.socket_keepalive = socket_keepalive
        self.socket_keepalive_options = socket_keepalive_options or {}
        self.health_check_interval = health_check_interval
        self.prefix = prefix

        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._degraded_mode = False
        self._last_connection_attempt: Optional[datetime] = None
        self._connection_failures = 0
        self._health_manager = get_connection_health_manager()

        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: Dict[str, datetime] = {}
        self._max_memory_cache_size = 1000

    async def initialize(self) -> bool:
        """Initialize Redis connection and register with health manager."""
        if not REDIS_AVAILABLE:
            logger.warning("Redis library not available, enabling degraded mode")
            await self._enable_degraded_mode("Redis library not installed")
            return False

        try:
            await self._create_connection_pool()
            await self._create_client()

            if await self._test_connection():
                self._connection_failures = 0
                self._degraded_mode = False

                self._health_manager.register_service(
                    service_name="redis",
                    connection_type=ConnectionType.REDIS,
                    health_check_func=self._health_check,
                    degraded_mode_callback=self._on_degraded_mode,
                    recovery_callback=self._on_recovery,
                )

                logger.info("Redis connection initialized successfully")
                return True

            await self._enable_degraded_mode("Initial connection test failed")
            return False
        except Exception as e:
            logger.error("Failed to initialize Redis connection: %s", e)
            await self._enable_degraded_mode(str(e))
            return False

    async def _create_connection_pool(self) -> None:
        """Create Redis connection pool."""
        if not REDIS_AVAILABLE:
            return

        try:
            self._pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                retry_on_timeout=self.retry_on_timeout,
                socket_keepalive=self.socket_keepalive,
                socket_keepalive_options=self.socket_keepalive_options,
                decode_responses=True,
            )
            logger.debug("Redis connection pool created")
        except Exception as e:
            logger.error("Failed to create Redis connection pool: %s", e)
            raise

    async def _create_client(self) -> None:
        """Create Redis client from connection pool."""
        if not self._pool:
            raise RuntimeError("Connection pool not initialized")

        try:
            self._client = Redis(connection_pool=self._pool)
            logger.debug("Redis client created")
        except Exception as e:
            logger.error("Failed to create Redis client: %s", e)
            raise

    async def _test_connection(self) -> bool:
        """Test Redis connection."""
        if not self._client:
            return False

        try:
            await self._client.ping()
            return True
        except Exception as e:
            logger.warning("Redis connection test failed: %s", e)
            return False

    async def health_check(self) -> Dict[str, Any]:
        """Public health check method."""
        result = await self._health_check()
        result["connection_info"] = self.get_connection_info()
        return result

    async def _health_check(self) -> Dict[str, Any]:
        """Health check function for connection health manager."""
        if not self._client or self._degraded_mode:
            return {
                "healthy": False,
                "degraded_mode": self._degraded_mode,
                "connection_failures": self._connection_failures,
            }

        try:
            start_time = time.time()
            await self._client.ping()
            response_time = (time.time() - start_time) * 1000

            pool_info = {}
            if self._pool:
                pool_info = {
                    "created_connections": getattr(self._pool, "created_connections", 0),
                    "available_connections": len(
                        getattr(self._pool, "_available_connections", [])
                    ),
                    "in_use_connections": len(
                        getattr(self._pool, "_in_use_connections", [])
                    ),
                }

            return {
                "healthy": True,
                "response_time_ms": response_time,
                "degraded_mode": False,
                "connection_failures": 0,
                "pool_info": pool_info,
            }
        except Exception as e:
            self._connection_failures += 1
            return {
                "healthy": False,
                "error": str(e),
                "degraded_mode": self._degraded_mode,
                "connection_failures": self._connection_failures,
            }

    async def _enable_degraded_mode(self, reason: str) -> None:
        """Enable degraded mode operation."""
        self._degraded_mode = True
        logger.warning("Redis degraded mode enabled: %s", reason)
        self._memory_cache.clear()
        self._cache_ttl.clear()

    async def _on_degraded_mode(self, service_name: str) -> None:
        """Callback when service enters degraded mode."""
        await self._enable_degraded_mode("Health check failed")

    async def _on_recovery(self, service_name: str) -> None:
        """Callback when service recovers."""
        self._degraded_mode = False
        self._connection_failures = 0
        logger.info("Redis service recovered, degraded mode disabled")

    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._get_from_memory_cache(key)

        if not self._client:
            return self._get_from_memory_cache(key)

        try:
            result = await self._client.get(key)
            if result is not None:
                self._set_in_memory_cache(key, result)
            return result
        except Exception as e:
            logger.warning("Redis GET failed for key %s: %s", key, e)
            await self._handle_connection_error(e)
            return self._get_from_memory_cache(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """Set value in Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._set_in_memory_cache(key, value, ex)

        if not self._client:
            return self._set_in_memory_cache(key, value, ex)

        try:
            result = await self._client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
            self._set_in_memory_cache(key, value, ex)
            return bool(result)
        except Exception as e:
            logger.warning("Redis SET failed for key %s: %s", key, e)
            await self._handle_connection_error(e)
            return self._set_in_memory_cache(key, value, ex)

    async def delete(self, *keys: str) -> int:
        """Delete keys from Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._delete_from_memory_cache(*keys)

        if not self._client:
            return self._delete_from_memory_cache(*keys)

        try:
            result = await self._client.delete(*keys)
            self._delete_from_memory_cache(*keys)
            return result
        except Exception as e:
            logger.warning("Redis DELETE failed for keys %s: %s", keys, e)
            await self._handle_connection_error(e)
            return self._delete_from_memory_cache(*keys)

    async def exists(self, *keys: str) -> int:
        """Check if keys exist in Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._exists_in_memory_cache(*keys)

        if not self._client:
            return self._exists_in_memory_cache(*keys)

        try:
            result = await self._client.exists(*keys)
            return result
        except Exception as e:
            logger.warning("Redis EXISTS failed for keys %s: %s", keys, e)
            await self._handle_connection_error(e)
            return self._exists_in_memory_cache(*keys)

    async def expire(self, key: str, time: int) -> bool:
        """Set expiration for key in Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._expire_in_memory_cache(key, time)

        if not self._client:
            return self._expire_in_memory_cache(key, time)

        try:
            result = await self._client.expire(key, time)
            self._expire_in_memory_cache(key, time)
            return bool(result)
        except Exception as e:
            logger.warning("Redis EXPIRE failed for key %s: %s", key, e)
            await self._handle_connection_error(e)
            return self._expire_in_memory_cache(key, time)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value from Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._hget_from_memory_cache(name, key)

        if not self._client:
            return self._hget_from_memory_cache(name, key)

        try:
            result = await self._client.hget(name, key)
            if result is not None:
                self._hset_in_memory_cache(name, key, result)
            return result
        except Exception as e:
            logger.warning("Redis HGET failed for %s:%s: %s", name, key, e)
            await self._handle_connection_error(e)
            return self._hget_from_memory_cache(name, key)

    async def hset(self, name: str, key: str, value: str) -> int:
        """Set hash field value in Redis with fallback to memory cache."""
        if self._degraded_mode:
            return self._hset_in_memory_cache(name, key, value)

        if not self._client:
            return self._hset_in_memory_cache(name, key, value)

        try:
            result = await self._client.hset(name, key, value)
            self._hset_in_memory_cache(name, key, value)
            return result
        except Exception as e:
            logger.warning("Redis HSET failed for %s:%s: %s", name, key, e)
            await self._handle_connection_error(e)
            return self._hset_in_memory_cache(name, key, value)

    async def _handle_connection_error(self, error: Exception) -> None:
        """Handle Redis connection errors."""
        self._connection_failures += 1
        self._last_connection_attempt = datetime.utcnow()
        await self._health_manager.handle_connection_failure("redis", error)

    def _get_from_memory_cache(self, key: str) -> Optional[str]:
        """Get value from memory cache."""
        self._cleanup_expired_cache()
        if key in self._memory_cache:
            cache_entry = self._memory_cache[key]
            if isinstance(cache_entry, dict) and "value" in cache_entry:
                return cache_entry["value"]
            return str(cache_entry)
        return None

    def _set_in_memory_cache(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set value in memory cache."""
        self._cleanup_expired_cache()

        if len(self._memory_cache) >= self._max_memory_cache_size:
            oldest_keys = sorted(
                self._cache_ttl.keys(),
                key=lambda k: self._cache_ttl.get(k, datetime.min),
            )[:100]
            for old_key in oldest_keys:
                self._memory_cache.pop(old_key, None)
                self._cache_ttl.pop(old_key, None)

        self._memory_cache[key] = {"value": value}
        if ex:
            self._cache_ttl[key] = datetime.utcnow() + timedelta(seconds=ex)
        else:
            self._cache_ttl[key] = datetime.utcnow() + timedelta(hours=1)
        return True

    def _delete_from_memory_cache(self, *keys: str) -> int:
        """Delete keys from memory cache."""
        deleted = 0
        for key in keys:
            if key in self._memory_cache:
                del self._memory_cache[key]
                self._cache_ttl.pop(key, None)
                deleted += 1
        return deleted

    def _exists_in_memory_cache(self, *keys: str) -> int:
        """Check if keys exist in memory cache."""
        self._cleanup_expired_cache()
        return sum(1 for key in keys if key in self._memory_cache)

    def _expire_in_memory_cache(self, key: str, time: int) -> bool:
        """Set expiration for key in memory cache."""
        if key in self._memory_cache:
            self._cache_ttl[key] = datetime.utcnow() + timedelta(seconds=time)
            return True
        return False

    def _hget_from_memory_cache(self, name: str, key: str) -> Optional[str]:
        """Get hash field from memory cache."""
        self._cleanup_expired_cache()
        hash_key = f"hash:{name}"
        if hash_key in self._memory_cache:
            hash_data = self._memory_cache[hash_key]
            if isinstance(hash_data, dict) and key in hash_data:
                return hash_data[key]
        return None

    def _hset_in_memory_cache(self, name: str, key: str, value: str) -> int:
        """Set hash field in memory cache."""
        self._cleanup_expired_cache()
        hash_key = f"hash:{name}"
        if hash_key not in self._memory_cache:
            self._memory_cache[hash_key] = {}
            self._cache_ttl[hash_key] = datetime.utcnow() + timedelta(hours=1)

        was_new = key not in self._memory_cache[hash_key]
        self._memory_cache[hash_key][key] = value
        return 1 if was_new else 0

    def _cleanup_expired_cache(self) -> None:
        """Clean up expired cache entries."""
        now = datetime.utcnow()
        expired_keys = [
            key for key, expiry in self._cache_ttl.items() if expiry < now
        ]
        for key in expired_keys:
            self._memory_cache.pop(key, None)
            self._cache_ttl.pop(key, None)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        return await self.set(key, value, ex=ttl)

    async def sadd(self, key: str, member: str) -> int:
        if self._degraded_mode or not self._client:
            return 0
        try:
            result = await self._client.sadd(key, member)
            return int(result)
        except Exception as e:
            logger.warning("Redis SADD failed for %s: %s", key, e)
            await self._handle_connection_error(e)
            return 0

    async def keys(self, pattern: str) -> List[str]:
        if self._degraded_mode or not self._client:
            return []
        try:
            result = await self._client.keys(pattern)
            return [str(k) for k in result]
        except Exception as e:
            logger.warning("Redis KEYS failed for %s: %s", pattern, e)
            await self._handle_connection_error(e)
            return []

    async def lpush(self, key: str, value: str) -> int:
        if self._degraded_mode or not self._client:
            return 0
        try:
            result = await self._client.lpush(key, value)
            return int(result)
        except Exception as e:
            logger.warning("Redis LPUSH failed for %s: %s", key, e)
            await self._handle_connection_error(e)
            return 0

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        if self._degraded_mode or not self._client:
            return False
        try:
            await self._client.ltrim(key, start, end)
            return True
        except Exception as e:
            logger.warning("Redis LTRIM failed for %s: %s", key, e)
            await self._handle_connection_error(e)
            return False

    async def smembers(self, key: str) -> List[str]:
        if self._degraded_mode or not self._client:
            return []
        try:
            result = await self._client.smembers(key)
            return [str(m) for m in result]
        except Exception as e:
            logger.warning("Redis SMEMBERS failed for %s: %s", key, e)
            await self._handle_connection_error(e)
            return []

    def health(self) -> bool:
        """Sync health check for compatibility."""
        return not self._degraded_mode and self._client is not None

    @property
    def client(self) -> Optional[Redis]:
        """Expose underlying async Redis client for advanced operations."""
        return self._client

    async def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Error closing Redis client: %s", e)
            finally:
                self._client = None

        if self._pool:
            try:
                await self._pool.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting Redis pool: %s", e)
            finally:
                self._pool = None

        self._memory_cache.clear()
        self._cache_ttl.clear()
        logger.info("Redis connection manager closed")

    def is_degraded(self) -> bool:
        """Check if Redis is in degraded mode."""
        return self._degraded_mode

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information and statistics."""
        info = {
            "redis_url": self.redis_url,
            "degraded_mode": self._degraded_mode,
            "connection_failures": self._connection_failures,
            "last_connection_attempt": (
                self._last_connection_attempt.isoformat()
                if self._last_connection_attempt
                else None
            ),
            "memory_cache_size": len(self._memory_cache),
            "memory_cache_max_size": self._max_memory_cache_size,
        }

        if self._pool:
            info.update(
                {
                    "pool_created_connections": getattr(
                        self._pool, "created_connections", 0
                    ),
                    "pool_available_connections": len(
                        getattr(self._pool, "_available_connections", [])
                    ),
                    "pool_in_use_connections": len(
                        getattr(self._pool, "_in_use_connections", [])
                    ),
                }
            )

        return info


_redis_manager: Optional[RedisConnectionManager] = None


def get_redis_manager() -> RedisConnectionManager:
    """Get global Redis connection manager instance."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisConnectionManager()
    return _redis_manager


async def initialize_redis_manager(
    redis_url: Optional[str] = None,
    max_connections: int = 10,
    **kwargs,
) -> RedisConnectionManager:
    """Initialize and return Redis connection manager."""
    global _redis_manager
    _redis_manager = RedisConnectionManager(
        redis_url=redis_url,
        max_connections=max_connections,
        **kwargs,
    )
    await _redis_manager.initialize()
    return _redis_manager


async def shutdown_redis_manager() -> None:
    """Shutdown global Redis connection manager."""
    global _redis_manager
    if _redis_manager:
        await _redis_manager.close()
        _redis_manager = None
