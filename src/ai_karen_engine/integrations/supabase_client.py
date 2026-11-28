"""Supabase platform client bootstrap.

This module owns Supabase Storage and Realtime lifecycle only. Durable work
queues are PostgreSQL runtime infrastructure and are intentionally not
advertised as a Supabase capability.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from ai_karen_engine.config.artifact_storage import StorageTLSPolicy

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
        self._credential_source: Optional[str] = None
        self._initialized = False
        self._storage_tls_policy: StorageTLSPolicy | None = None
        self._storage_http_client: httpx.Client | None = None

    @property
    def storage_tls_policy(self) -> StorageTLSPolicy | None:
        return self._storage_tls_policy

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
        self.reset()
        # New API-key contract has precedence. Legacy keys remain a compatibility
        # path for existing installations until their deployment env is migrated.
        self._url = url or os.getenv("SUPABASE_PROJECT_URL") or os.getenv("SUPABASE_URL")
        self._key = None
        self._credential_source = None
        if key:
            self._key = key
            self._credential_source = "explicit"
        else:
            # Privileged credentials must never be silently overridden by a
            # public key. Compatibility follows the documented migration order.
            for source in (
                "SUPABASE_SECRET_KEY",
                "SUPABASE_SERVICE_ROLE_KEY",
                "SUPABASE_PUBLISHABLE_KEY",
                "SUPABASE_ANON_KEY",
            ):
                candidate = os.getenv(source)
                if candidate:
                    self._key = candidate
                    self._credential_source = source
                    break
        if self._credential_source in {"SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY"}:
            logger.warning(
                "Supabase platform is using a legacy key source: %s; migrate to a "
                "scoped modern key before retiring the legacy configuration",
                self._credential_source,
            )

        if not self._url or not self._key:
            logger.info(
                "Supabase platform not configured; storage/realtime capabilities disabled"
            )
            self._initialized = True
            return True

        try:
            from supabase import create_client

            policy = StorageTLSPolicy.from_environment(self._url)
            if policy is None:
                client = create_client(self._url, self._key)
            else:
                from supabase import ClientOptions

                def enforce_origin(request: httpx.Request) -> None:
                    policy.require_destination(str(request.url))

                self._storage_http_client = httpx.Client(
                    verify=policy.verify_for_origin(self._url),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=20.0,
                    event_hooks={"request": [enforce_origin]},
                )
                client = create_client(
                    self._url, self._key,
                    options=ClientOptions(httpx_client=self._storage_http_client),
                )
            self._storage = client.storage
            self._storage_tls_policy = policy
            self._realtime_client = client
            logger.info("Supabase Storage capability initialized")
        except Exception as exc:
            logger.warning("Supabase Storage initialization failed (%s)", type(exc).__name__)
            self._close_storage_transport()
            self._storage_tls_policy = None
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
            "credential_source": self._credential_source,
        }

    def _close_storage_transport(self) -> None:
        transport, self._storage_http_client = self._storage_http_client, None
        if transport is not None:
            try:
                transport.close()
            except Exception as exc:
                logger.warning("Supabase Storage transport close failed (%s)", type(exc).__name__)

    def reset(self) -> None:
        self._close_storage_transport()
        self._storage_tls_policy = None
        self._storage = None
        self._realtime_client = None
        self._publisher = None
        self._url = None
        self._key = None
        self._credential_source = None
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
