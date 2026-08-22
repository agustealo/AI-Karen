"""Canonical model cache and preload authority.

This module supersedes ``integrations/model_availability_cache.py``.
It provides a minimal cache-state and preload-hint surface for the
canonical ``core/model_runtime`` domain. Provider routing, fallback,
and policy decisions live elsewhere and are not duplicated here.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AvailabilityStatus(str, Enum):
    """Model availability status levels."""
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    CACHED = "cached"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    CORRUPTED = "corrupted"
    EXPIRED = "expired"


class PreloadPriority(Enum):
    """Preloading priority levels."""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    LAZY = 4


@dataclass
class ModelMetadata:
    """Metadata for cached models."""
    name: str
    provider: str
    model_type: str
    capabilities: set = field(default_factory=set)
    size_bytes: int = 0
    version: str = ""
    checksum: str = ""
    download_url: Optional[str] = None
    local_path: Optional[str] = None


@dataclass
class CacheEntry:
    """Cache entry for a model."""
    metadata: ModelMetadata
    status: AvailabilityStatus
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl: float = 0.0
    size_bytes: int = 0
    download_progress: float = 0.0
    error_message: Optional[str] = None
    preload_priority: PreloadPriority = PreloadPriority.MEDIUM

    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return time.time() - self.created_at > self.ttl

    def update_access(self) -> None:
        self.last_accessed = time.time()
        self.access_count += 1


class ModelCacheService:
    """Canonical model cache service for core/model_runtime.

    Provides lightweight cache-state tracking and preload hints.
    Routing, fallback, and policy decisions are handled by other
    canonical services (``ProviderRegistryService``, ``ModelManager``,
    ``ProviderHealthMonitor``).
    """

    def __init__(self) -> None:
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._preload_successes = 0
        self._preload_failures = 0

    def get_model_status(self, provider: str, model_name: str) -> AvailabilityStatus:
        cache_key = self._get_cache_key(provider, model_name)
        with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                entry.update_access()
                self._cache_hits += 1
                if entry.is_expired():
                    entry.status = AvailabilityStatus.EXPIRED
                    return AvailabilityStatus.EXPIRED
                return entry.status
            self._cache_misses += 1
            return AvailabilityStatus.UNAVAILABLE

    def get_model_metadata(self, provider: str, model_name: str) -> Optional[ModelMetadata]:
        cache_key = self._get_cache_key(provider, model_name)
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key].metadata
            return None

    def is_model_cached(self, provider: str, model_name: str) -> bool:
        status = self.get_model_status(provider, model_name)
        return status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.CACHED)

    def get_cache_statistics(self) -> Dict[str, Any]:
        with self._lock:
            total_size = sum(entry.size_bytes for entry in self._cache.values())
            status_counts: Dict[str, int] = {}
            for entry in self._cache.values():
                status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1
            return {
                "total_entries": len(self._cache),
                "total_size_bytes": total_size,
                "cache_hit_rate": self._cache_hits / max(self._cache_hits + self._cache_misses, 1),
                "preload_success_rate": self._preload_successes / max(
                    self._preload_successes + self._preload_failures, 1
                ),
                "active_downloads": sum(
                    1 for e in self._cache.values() if e.status == AvailabilityStatus.DOWNLOADING
                ),
                "status_distribution": status_counts,
            }

    def update_cache_entry(
        self,
        provider: str,
        model_name: str,
        status: AvailabilityStatus,
        metadata: Optional[ModelMetadata] = None,
        size_bytes: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        cache_key = self._get_cache_key(provider, model_name)
        with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                entry.status = status
                entry.last_accessed = time.time()
                entry.access_count += 1
                if metadata:
                    entry.metadata = metadata
                if size_bytes:
                    entry.size_bytes = size_bytes
                if error_message:
                    entry.error_message = error_message
            else:
                if metadata is None:
                    metadata = ModelMetadata(
                        name=model_name,
                        provider=provider,
                        model_type="unknown",
                    )
                self._cache[cache_key] = CacheEntry(
                    metadata=metadata,
                    status=status,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    size_bytes=size_bytes,
                    error_message=error_message,
                )

    async def preload_model(
        self,
        provider: str,
        model_name: str,
        priority: PreloadPriority = PreloadPriority.MEDIUM,
    ) -> bool:
        cache_key = self._get_cache_key(provider, model_name)
        with self._lock:
            if cache_key in self._cache and self._cache[cache_key].status == AvailabilityStatus.AVAILABLE:
                logger.debug("Model %s already available", cache_key)
                return True
            if cache_key not in self._cache:
                metadata = ModelMetadata(
                    name=model_name,
                    provider=provider,
                    model_type="unknown",
                )
                self._cache[cache_key] = CacheEntry(
                    metadata=metadata,
                    status=AvailabilityStatus.UNAVAILABLE,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    preload_priority=priority,
                )
        logger.debug("Preload queued for %s", cache_key)
        return True

    def clear_cache(self, provider: Optional[str] = None, model_name: Optional[str] = None) -> int:
        cleared = 0
        with self._lock:
            keys_to_remove = []
            for cache_key, entry in self._cache.items():
                if provider and entry.metadata.provider != provider:
                    continue
                if model_name and entry.metadata.name != model_name:
                    continue
                keys_to_remove.append(cache_key)
            for cache_key in keys_to_remove:
                del self._cache[cache_key]
                cleared += 1
        return cleared

    def _get_cache_key(self, provider: str, model_name: str) -> str:
        return f"{provider}:{model_name}"


_model_cache_service: Optional[ModelCacheService] = None
_cache_lock = threading.RLock()


def get_model_cache_service() -> ModelCacheService:
    """Get or create the canonical model cache service instance."""
    global _model_cache_service
    if _model_cache_service is None:
        with _cache_lock:
            if _model_cache_service is None:
                _model_cache_service = ModelCacheService()
    return _model_cache_service


__all__ = [
    "AvailabilityStatus",
    "PreloadPriority",
    "ModelMetadata",
    "CacheEntry",
    "ModelCacheService",
    "get_model_cache_service",
]
