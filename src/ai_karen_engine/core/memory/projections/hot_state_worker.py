"""Backend-neutral hot-state projection for governed memory events.

Core owns the decision to expose a committed event as bounded current-session
context. Physical storage, key layout, TTLs, and degraded behavior belong to the
injected ``STMPort`` implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.stm import STMScope, STMSlot, STMPort

from .base import ProjectionWorker

logger = get_logger(__name__)


class HotStateWorker(ProjectionWorker):
    """Project the latest committed memory event into bounded session STM."""

    def __init__(self, stm: STMPort) -> None:
        super().__init__("stm")
        self._stm = stm

    async def project(
        self,
        event_data: dict[str, Any],
        assertion_data: dict[str, Any] | None = None,
    ) -> bool:
        tenant_id = str(event_data.get("tenant_id") or "").strip()
        user_id = str(event_data.get("user_id") or "").strip()
        session_id = str(event_data.get("session_id") or "").strip()

        # STM is intentionally session-scoped. A durable event without a session
        # remains durable in Postgres and is not promoted into synthetic global STM.
        if not session_id:
            logger.debug(
                "memory.stm_projection.skipped",
                extra={
                    "event_id": event_data.get("event_id"),
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "reason": "missing_session_id",
                },
            )
            return True

        try:
            scope = STMScope(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            scope.validate()
        except ValueError:
            logger.warning(
                "memory.stm_projection.rejected",
                extra={
                    "event_id": event_data.get("event_id"),
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "reason": "invalid_scope",
                },
            )
            return False

        record = self._build_hot_record(event_data, assertion_data)
        try:
            ok = await self._stm.put_slot(
                scope=scope,
                slot=STMSlot.RECENT_CONTEXT,
                value={
                    "latest": record,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.exception(
                "memory.stm_projection.failed",
                extra={
                    "event_id": event_data.get("event_id"),
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                },
            )
            return False

        if self._stm.degraded():
            logger.warning(
                "memory.stm_projection.degraded",
                extra={
                    "event_id": event_data.get("event_id"),
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_id": session_id,
                },
            )
        return bool(ok)

    @classmethod
    def _build_hot_record(
        cls,
        event_data: dict[str, Any],
        assertion_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = event_data.get("payload") or {}
        record: dict[str, Any] = {
            "event_id": str(event_data.get("event_id") or ""),
            "source_type": event_data.get("source_type"),
            "source_ref": event_data.get("source_ref"),
            "scope": event_data.get("scope"),
            "confidence": event_data.get("confidence"),
            "timestamp": event_data.get("created_at"),
        }
        if assertion_data:
            record.update(
                {
                    "artifact_type": "assertion",
                    "assertion_id": str(assertion_data.get("assertion_id") or ""),
                    "content": assertion_data.get("text")
                    or assertion_data.get("content"),
                }
            )
        else:
            record.update(
                {
                    "artifact_type": "event",
                    "content": payload.get("summary") or payload.get("text"),
                    "signal_type": payload.get("signal_type") or payload.get("type"),
                }
            )
        return cls._json_safe(record)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return value


__all__ = ["HotStateWorker"]
