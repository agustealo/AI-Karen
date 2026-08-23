"""
Supabase Realtime Broadcast publisher.

Owns the Supabase Realtime client lifecycle and translates
RealtimePublisher contract calls into Broadcast operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ai_karen_engine.services.database.repositories.realtime_publisher import (
    RealtimePublisher,
)
from ai_karen_engine.services.database.repositories.observability import instrument_repository
from ai_karen_engine.services.database.repositories.base import RepositoryResult

logger = logging.getLogger(__name__)


class SupabaseRealtimePublisher(RealtimePublisher):
    """Supabase Realtime Broadcast publisher."""

    def __init__(self, supabase_client: Any):
        self._client = supabase_client

    @instrument_repository(operation="publish", repository="SupabaseRealtimePublisher")
    async def publish(self, topic: str, event: str, payload: Dict[str, Any]) -> None:
        try:
            if self._client is None:
                logger.debug("Realtime publish skipped: client not configured")
                return

            channel = self._client.channel(topic)
            channel.send(event, payload)
            logger.debug("Realtime published topic=%s event=%s", topic, event)
        except Exception as exc:
            logger.warning("Realtime publish failed: topic=%s event=%s error=%s", topic, event, exc)

    @instrument_repository(operation="publish_many", repository="SupabaseRealtimePublisher")
    async def publish_many(self, events: List[Tuple[str, str, Dict[str, Any]]]) -> None:
        for topic, event, payload in events:
            await self.publish(topic, event, payload)

    @instrument_repository(operation="health_check", repository="SupabaseRealtimePublisher")
    async def health_check(self) -> RepositoryResult:
        try:
            if self._client is None:
                return RepositoryResult(success=True, data={"status": "disabled"})
            return RepositoryResult(success=True, data={"status": "configured"})
        except Exception as exc:
            logger.error("Realtime health check failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))
