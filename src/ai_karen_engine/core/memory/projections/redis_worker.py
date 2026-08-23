"""
Redis Projection Worker for AI Karen Memory System.

Projects memory ledger events into Redis for fast hot-state retrieval.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional
from ai_karen_engine.core.logging import get_logger

from .base import ProjectionWorker
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager, RedisConnectionManager

logger = logging.getLogger(__name__)

class RedisWorker(ProjectionWorker):
    """Worker responsible for Redis hot-state projections."""

    def __init__(self, client: Optional[RedisConnectionManager] = None, recent_limit: int = 20):
        super().__init__("redis")
        self.client = client or get_redis_manager()
        self.recent_limit = recent_limit

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): RedisWorker._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [RedisWorker._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [RedisWorker._json_safe(item) for item in value]
        if isinstance(value, (datetime,)):
            return value.isoformat()
        return value

    def _build_hot_record(
        self,
        event_data: Dict[str, Any],
        assertion_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = event_data.get("payload", {}) or {}
        record = {
            "event_id": str(event_data.get("event_id")),
            "tenant_id": str(event_data.get("tenant_id")),
            "user_id": str(event_data.get("user_id")),
            "source_type": event_data.get("source_type"),
            "source_ref": event_data.get("source_ref"),
            "scope": event_data.get("scope"),
            "confidence": event_data.get("confidence"),
            "sensitivity_class": event_data.get("sensitivity_class"),
            "consent_state": event_data.get("consent_state"),
            "timestamp": event_data.get("created_at"),
        }

        if assertion_data:
            record.update(
                {
                    "artifact_type": "assertion",
                    "assertion_id": str(assertion_data.get("assertion_id")),
                    "content": assertion_data.get("content"),
                    "assertion": self._json_safe(assertion_data),
                }
            )
        else:
            record.update(
                {
                    "artifact_type": "event",
                    "content": payload.get("text"),
                    "signal_type": payload.get("type"),
                    "payload": self._json_safe(payload),
                }
            )

        return self._json_safe(record)

    async def project(self, event_data: Dict[str, Any], assertion_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Store the latest memory snapshot in Redis hot cache.
        """
        try:
            if not self.client.health():
                logger.warning("Redis client not connected. Skipping projection.")
                return False

            tenant_id = str(event_data.get("tenant_id"))
            user_id = str(event_data.get("user_id"))
            session_id = event_data.get("session_id") or event_data.get("source_ref")

            hot_record = self._build_hot_record(event_data, assertion_data)
            recent_key = f"{self.client.prefix}:hot_memory:{tenant_id}:{user_id}"

            await self.client.set_short_term(
                tenant_id,
                user_id,
                {
                    "latest": hot_record,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )

            if session_id:
                await self.client.set_session(
                    tenant_id,
                    user_id,
                    {
                        "latest": hot_record,
                        "recent": [hot_record],
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                    session_id=str(session_id),
                    ttl_seconds=24 * 60 * 60,
                )

            await self.client.lpush(recent_key, json.dumps(hot_record, default=str))
            await self.client.ltrim(recent_key, 0, self.recent_limit - 1)
            return True

        except Exception as e:
            logger.error(f"Error projecting to Redis for event {event_data.get('event_id')}: {e}")
            return False
