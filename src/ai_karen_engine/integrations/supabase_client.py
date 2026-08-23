"""
Supabase platform client bootstrap.

This module owns the canonical Supabase platform client lifecycle.
It does not contain business logic; it exposes initialized capabilities
to the data layer.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class SupabasePlatformClient:
    """Canonical Supabase platform capability holder."""

    def __init__(self):
        self._storage: Optional[Any] = None
        self._realtime: Optional[Any] = None
        self._queue: Optional[Any] = None
        self._url: Optional[str] = None
        self._key: Optional[str] = None
        self._initialized = False

    @property
    def storage(self) -> Optional[Any]:
        """Return initialized Supabase Storage capability."""
        return self._storage

    @property
    def realtime(self) -> Optional[Any]:
        """Return initialized Supabase Realtime capability."""
        return self._realtime

    @property
    def queue(self) -> Optional[Any]:
        """Return initialized Supabase Queue capability."""
        return self._queue

    @property
    def url(self) -> Optional[str]:
        """Return Supabase project URL."""
        return self._url

    @property
    def key(self) -> Optional[str]:
        """Return Supabase publishable/anon key."""
        return self._key

    def initialize(self, url: Optional[str] = None, key: Optional[str] = None) -> bool:
        """Initialize platform clients from canonical settings or environment.

        Args:
            url: Supabase project URL. Falls back to SUPABASE_URL env var.
            key: Supabase publishable/anon key. Falls back to SUPABASE_ANON_KEY env var.

        Returns:
            True if initialization succeeded or was intentionally skipped.
        """
        self._url = url or os.getenv("SUPABASE_URL")
        self._key = key or os.getenv("SUPABASE_ANON_KEY")

        if not self._url or not self._key:
            logger.info("Supabase platform not configured; platform capabilities disabled")
            self._initialized = True
            return True

        try:
            from supabase import create_client

            client = create_client(self._url, self._key)
            self._storage = client.storage
            logger.info("Supabase Storage capability initialized")
        except Exception as exc:
            logger.warning("Supabase Storage initialization failed: %s", exc)
            self._storage = None

        try:
            self._realtime = None
            logger.info("Supabase Realtime capability deferred to publisher adapter")
        except Exception as exc:
            logger.warning("Supabase Realtime initialization failed: %s", exc)
            self._realtime = None

        try:
            self._queue = None
            logger.info("Supabase Queue capability deferred to durable queue adapter")
        except Exception as exc:
            logger.warning("Supabase Queue initialization failed: %s", exc)
            self._queue = None

        self._initialized = True
        return True

    def health_metadata(self) -> Dict[str, Any]:
        """Return platform health metadata."""
        return {
            "initialized": self._initialized,
            "storage": self._storage is not None,
            "realtime": self._realtime is not None,
            "queue": self._queue is not None,
            "url": self._url,
        }

    def reset(self) -> None:
        """Reset platform state for tests or shutdown."""
        self._storage = None
        self._realtime = None
        self._queue = None
        self._url = None
        self._key = None
        self._initialized = False


_supabase_platform: Optional[SupabasePlatformClient] = None


def get_supabase_platform() -> SupabasePlatformClient:
    """Return the global Supabase platform client."""
    global _supabase_platform
    if _supabase_platform is None:
        _supabase_platform = SupabasePlatformClient()
        _supabase_platform.initialize()
    return _supabase_platform


def reset_supabase_platform() -> None:
    """Reset the global Supabase platform client (tests only)."""
    global _supabase_platform
    if _supabase_platform is not None:
        _supabase_platform.reset()
    _supabase_platform = None
