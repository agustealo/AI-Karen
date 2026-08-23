"""
Production Cache Service

Provides comprehensive caching optimizations for production deployment,
including response formatting result caching, model library caching,
intelligent query caching, and cache invalidation strategies.
"""

import json
import logging
import hashlib
import time
from typing import Any, Dict, List, Optional, Union, Callable, Literal
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from threading import RLock
import asyncio
from functools import wraps

from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager, RedisConnectionManager

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached entry with metadata."""

    key: str
    value: Any
    created_at: datetime
    expires_at: Optional[datetime]
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    tags: Optional[List[str]] = None
    size_bytes: int = 0

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.last_accessed is None:
            self.last_accessed = self.created_at


@dataclass
class CacheStats:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size: int = 0
    entry_count: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class CacheService:
    """
    Production-grade caching service with intelligent invalidation strategies.

    Features:
    - Response formatting result caching
    - Model library caching with TTL
    - Database query result caching
    - Tag-based cache invalidation
    - Performance metrics and monitoring
    - Memory-aware cache eviction
    """

    def __init__(
        self, redis_client: Optional[RedisConnectionManager] = None, prefix: str = "prod_cache"
    ):
        self.redis = redis_client or get_redis_manager()
        self.prefix = prefix
        self._local_cache: Dict[str, CacheEntry] = {}
        self._cache_lock = RLock()
        self._stats = CacheStats()

        # Cache configuration
        self.default_ttl = 3600  # 1 hour
        self.max_local_entries = 1000
        self.max_local_size_mb = 50

        # Cache namespaces for different types of data
        self.namespaces = {
            "response_formatting": "rf",
            "model_library": "ml",
            "database_queries": "dq",
            "user_sessions": "us",
            "api_responses": "ar",
        }

        logger.info(f"Production cache service initialized with prefix: {prefix}")

    def _make_key(self, namespace: str, key: str) -> str:
        """Create a namespaced cache key."""
        ns_prefix = self.namespaces.get(namespace, namespace)
        return f"{self.prefix}:{ns_prefix}:{key}"

    def _hash_key(self, data: Union[str, Dict, List]) -> str:
        """Create a hash key from data."""
        if isinstance(data, str):
            content = data
        else:
            content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _serialize_value(self, value: Any) -> str:
        """Serialize a value for storage."""
        return json.dumps(value, default=str, ensure_ascii=False)

    def _deserialize_value(self, value: str) -> Any:
        """Deserialize a value from storage."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def _calculate_size(self, value: Any) -> int:
        """Calculate approximate size of a value in bytes."""
        try:
            return len(self._serialize_value(value).encode("utf-8"))
        except Exception:
            return 0

    def _should_cache_locally(self, size_bytes: int) -> bool:
        """Determine if an entry should be cached locally."""
        # Don't cache very large entries locally
        if size_bytes > 1024 * 1024:  # 1MB
            return False

        # Check if we have space
        current_size_mb = sum(
            entry.size_bytes for entry in self._local_cache.values()
        ) / (1024 * 1024)
        if current_size_mb >= self.max_local_size_mb:
            return False

        if len(self._local_cache) >= self.max_local_entries:
            return False

        return True

    def _evict_local_entries(self, count: int = 1) -> None:
        """Evict least recently used entries from local cache."""
        if not self._local_cache:
            return

        # Sort by last accessed time
        sorted_entries = sorted(
            self._local_cache.items(), key=lambda x: x[1].last_accessed or datetime.min
        )

        for i in range(min(count, len(sorted_entries))):
            key, _ = sorted_entries[i]
            del self._local_cache[key]
            self._stats.evictions += 1

    async def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """
        Get a value from cache.

        Args:
            namespace: Cache namespace
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        cache_key = self._make_key(namespace, key)

        # Check local cache first
        with self._cache_lock:
            if cache_key in self._local_cache:
                entry = self._local_cache[cache_key]

                # Check expiration
                if entry.expires_at and datetime.now() > entry.expires_at:
                    del self._local_cache[cache_key]
                else:
                    entry.access_count += 1
                    entry.last_accessed = datetime.now()
                    self._stats.hits += 1
                    return entry.value

        # Check Redis cache
        try:
            if self.redis and self.redis.health():
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    try:
                        # Handle both string and bytes data
                        if isinstance(cached_data, bytes):
                            cached_data = cached_data.decode("utf-8")
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)

                        # Check expiration
                        if entry.expires_at:
                            expires_at = (
                                datetime.fromisoformat(entry.expires_at)
                                if isinstance(entry.expires_at, str)
                                else entry.expires_at
                            )
                            if datetime.now() > expires_at:
                                await self.redis.delete(cache_key)
                                self._stats.misses += 1
                                return default

                        # Update local cache if appropriate
                        if self._should_cache_locally(entry.size_bytes):
                            with self._cache_lock:
                                if len(self._local_cache) >= self.max_local_entries:
                                    self._evict_local_entries(1)
                                self._local_cache[cache_key] = entry

                        self._stats.hits += 1
                        return entry.value
                    except Exception as e:
                        logger.warning(
                            f"Failed to deserialize cache entry {cache_key}: {e}"
                        )
                        await self.redis.delete(cache_key)
        except Exception as e:
            logger.warning(f"Redis cache get failed for {cache_key}: {e}")

        self._stats.misses += 1
        return default

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Set a value in cache.

        Args:
            namespace: Cache namespace
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
            tags: Tags for cache invalidation

        Returns:
            True if successful
        """
        cache_key = self._make_key(namespace, key)
        ttl = ttl or self.default_ttl
        tags = tags or []

        now = datetime.now()
        expires_at = now + timedelta(seconds=ttl) if ttl > 0 else None
        size_bytes = self._calculate_size(value)

        entry = CacheEntry(
            key=cache_key,
            value=value,
            created_at=now,
            expires_at=expires_at,
            tags=tags,
            size_bytes=size_bytes,
        )

        try:
            # Store in Redis
            if self.redis and self.redis.health():
                entry_data = asdict(entry)
                # Convert datetime objects to ISO strings for JSON serialization
                if entry_data["created_at"]:
                    entry_data["created_at"] = entry_data["created_at"].isoformat()
                if entry_data["expires_at"]:
                    entry_data["expires_at"] = entry_data["expires_at"].isoformat()
                if entry_data["last_accessed"]:
                    entry_data["last_accessed"] = entry_data[
                        "last_accessed"
                    ].isoformat()

                serialized = json.dumps(entry_data, default=str)

                if ttl > 0:
                    await self.redis.set(cache_key, serialized, ex=ttl)
                else:
                    await self.redis.set(cache_key, serialized)

                # Store tags for invalidation
                for tag in tags:
                    tag_key = f"{self.prefix}:tags:{tag}"
                    await self.redis.sadd(tag_key, cache_key)
                    if ttl > 0:
                        await self.redis.expire(
                            tag_key, ttl + 3600
                        )  # Keep tags a bit longer

            # Store in local cache if appropriate
            if self._should_cache_locally(size_bytes):
                with self._cache_lock:
                    if len(self._local_cache) >= self.max_local_entries:
                        self._evict_local_entries(1)
                    self._local_cache[cache_key] = entry

            return True

        except Exception as e:
            logger.error(f"Failed to set cache entry {cache_key}: {e}")
            return False

    async def delete(self, namespace: str, key: str) -> bool:
        """Delete a cache entry."""
        cache_key = self._make_key(namespace, key)

        # Remove from local cache
        with self._cache_lock:
            self._local_cache.pop(cache_key, None)

        # Remove from Redis
        try:
            if self.redis and self.redis.health():
                return bool(await self.redis.delete(cache_key))
        except Exception as e:
            logger.warning(f"Failed to delete cache entry {cache_key}: {e}")

        return False

    async def invalidate_by_tags(self, tags: List[str]) -> int:
        """
        Invalidate cache entries by tags.

        Args:
            tags: List of tags to invalidate

        Returns:
            Number of entries invalidated
        """
        if not tags:
            return 0

        invalidated = 0

        try:
            if self.redis and self.redis.health():
                for tag in tags:
                    tag_key = f"{self.prefix}:tags:{tag}"
                    cache_keys = await self.redis.smembers(tag_key)

                    if cache_keys:
                        # Delete cache entries
                        deleted = await self.redis.delete(*cache_keys)
                        invalidated += int(deleted)

                        # Remove from local cache
                        with self._cache_lock:
                            for cache_key in cache_keys:
                                if isinstance(cache_key, bytes):
                                    cache_key = cache_key.decode("utf-8")
                                self._local_cache.pop(cache_key, None)

                    # Delete tag set
                    await self.redis.delete(tag_key)

        except Exception as e:
            logger.error(f"Failed to invalidate cache by tags {tags}: {e}")

        logger.info(f"Invalidated {invalidated} cache entries for tags: {tags}")
        return invalidated

    async def clear_namespace(self, namespace: str) -> int:
        """Clear all entries in a namespace."""
        pattern = self._make_key(namespace, "*")
        cleared = 0

        try:
            if self.redis and self.redis.health():
                keys = await self.redis.keys(pattern)
                if keys:
                    cleared = int(await self.redis.delete(*keys))

                # Clear from local cache
                with self._cache_lock:
                    to_remove = [
                        k
                        for k in self._local_cache.keys()
                        if k.startswith(self._make_key(namespace, ""))
                    ]
                    for key in to_remove:
                        del self._local_cache[key]

        except Exception as e:
            logger.error(f"Failed to clear namespace {namespace}: {e}")

        logger.info(f"Cleared {cleared} entries from namespace: {namespace}")
        return cleared

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        with self._cache_lock:
            local_size_mb = sum(
                entry.size_bytes for entry in self._local_cache.values()
            ) / (1024 * 1024)

            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "hit_rate": self._stats.hit_rate,
                "evictions": self._stats.evictions,
                "local_entries": len(self._local_cache),
                "local_size_mb": round(local_size_mb, 2),
                "redis_connected": self.redis.health() if self.redis else False,
            }

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._stats = CacheStats()

    # Decorator for caching function results
    def cached(
        self,
        namespace: str,
        ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
        key_func: Optional[Callable] = None,
    ):
        """
        Decorator for caching function results.

        Args:
            namespace: Cache namespace
            ttl: Time to live in seconds
            tags: Tags for cache invalidation
            key_func: Function to generate cache key from args
        """

        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    key_data = {"args": args, "kwargs": kwargs}
                    cache_key = self._hash_key(key_data)

                # Try to get from cache
                result = await self.get(namespace, cache_key)
                if result is not None:
                    return result

                # Execute function and cache result
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                await self.set(namespace, cache_key, result, ttl, tags)
                return result

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    key_data = {"args": args, "kwargs": kwargs}
                    cache_key = self._hash_key(key_data)

                # Try to get from cache (sync version)
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                result = loop.run_until_complete(self.get(namespace, cache_key))
                if result is not None:
                    return result

                # Execute function and cache result
                result = func(*args, **kwargs)
                loop.run_until_complete(
                    self.set(namespace, cache_key, result, ttl, tags)
                )
                return result

            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

        return decorator


# Global cache service instance
_cache_service: Optional[CacheService] = None
_cache_lock = RLock()


def get_cache_service() -> CacheService:
    """Get the global cache service instance."""
    global _cache_service

    if _cache_service is None:
        with _cache_lock:
            if _cache_service is None:
                _cache_service = CacheService()

    return _cache_service


def reset_cache_service() -> None:
    """Reset the global cache service (for testing)."""
    global _cache_service

    with _cache_lock:
        _cache_service = None
