"""Supabase platform client bootstrap.

This module owns Supabase Storage and Realtime lifecycle only. Durable work
queues are PostgreSQL runtime infrastructure and are intentionally not
advertised as a Supabase capability.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class SupabasePlatformClient:
    """Canonical Supabase platform capability holder."""

    def __init__(self) -> None:
        self._storage: Optional[Any] = None
        self._realtime_client: Optional[Any] = None
        self._publisher: Optional[Any] = None
        self._url: Optional[str] = None
        self._key: Optional[str] = None
        self._initialized = False

    @property
    def storage(self) -> Optional[Any]:
        return self._storage

    @property
    def realtime_client(self) -> Optional[Any]:
        return self._realtime_client

    @property
    def publisher(self) -> Optional[Any]:
        return self._publisher

    @property
    def queue(self) -> None:
        """Compatibility property: Supabase does not own KAREN's durable queue."""
        return None

    @property
    def url(self) -> Optional[str]:
        return self._url

    @property
    def key(self) -> Optional[str]:
        return self._key

    def initialize(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
    ) -> bool:
        self._url = url or os.getenv("SUPABASE_URL")
        self._key = key or os.getenv("SUPABASE_ANON_KEY")

        if not self._url or not self._key:
            logger.info(
                "Supabase platform not configured; storage/realtime capabilities disabled"
            )
            self._initialized = True
            return True

        try:
            from supabase import create_client

            client = create_client(self._url, self._key)
            self._storage = client.storage
            self._realtime_client = client
            logger.info("Supabase Storage capability initialized")
        except Exception as exc:
            logger.warning("Supabase Storage initialization failed: %s", exc)
            self._storage = None
            self._realtime_client = None

        try:
            if self._realtime_client is not None:
                from ai_karen_engine.services.database.repositories.supabase_realtime_publisher import (
                    SupabaseRealtimePublisher,
                )

                self._publisher = SupabaseRealtimePublisher(self._realtime_client)
                logger.info("Supabase Realtime publisher initialized")
            else:
                self._publisher = None
                logger.info("Supabase Realtime publisher skipped: client not available")
        except Exception as exc:
            logger.warning("Supabase Realtime publisher initialization failed: %s", exc)
            self._publisher = None

        self._initialized = True
        return True

    def health_metadata(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "storage": self._storage is not None,
            "realtime_client": self._realtime_client is not None,
            "publisher": self._publisher is not None,
            "queue": False,
            "url": self._url,
        }

    def reset(self) -> None:
        self._storage = None
        self._realtime_client = None
        self._publisher = None
        self._url = None
        self._key = None
        self._initialized = False


_supabase_platform: Optional[SupabasePlatformClient] = None


def get_supabase_platform() -> SupabasePlatformClient:
    global _supabase_platform
    if _supabase_platform is None:
        _supabase_platform = SupabasePlatformClient()
        _supabase_platform.initialize()
    return _supabase_platform


def reset_supabase_platform() -> None:
    global _supabase_platform
    if _supabase_platform is not None:
        _supabase_platform.reset()
    _supabase_platform = None
