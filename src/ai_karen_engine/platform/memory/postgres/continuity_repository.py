"""PostgreSQL read model for predictive continuity state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from ai_karen_engine.core.cortex.continuity import ContinuityStateItem
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import (
    MemoryEvent,
    MemoryOpenLoop,
    MemoryProspectiveItem,
    MemoryUserGoal,
)


class PostgresContinuityStateRepository:
    """Read current governed continuity state without becoming a memory owner."""

    @staticmethod
    def _scope(tenant_id: str, user_id: str) -> tuple[uuid.UUID, uuid.UUID]:
        tenant = str(tenant_id or "").strip()
        user = str(user_id or "").strip()
        if not tenant or tenant == "default":
            raise ValueError("continuity tenant_id must be explicit and non-default")
        if not user:
            raise ValueError("continuity user_id must be explicit")
        return uuid.UUID(tenant), uuid.UUID(user)

    async def list_current_state(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[ContinuityStateItem]:
        tenant_uuid, user_uuid = self._scope(tenant_id, user_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        bounded = max(1, min(int(limit), 100))

        async with async_transaction_scope(tenant_id=tenant_id) as session:
            goals = (
                await session.execute(
                    select(MemoryUserGoal, MemoryEvent.event_id)
                    .join(MemoryEvent, MemoryEvent.event_id == MemoryUserGoal.event_id)
                    .where(
                        MemoryUserGoal.tenant_id == tenant_uuid,
                        MemoryUserGoal.user_id == user_uuid,
                        MemoryUserGoal.lifecycle_state.in_(
                            ("proposed", "active", "blocked", "paused", "at_risk", "satisfied")
                        ),
                        or_(MemoryUserGoal.valid_to.is_(None), MemoryUserGoal.valid_to > now),
                        MemoryEvent.tenant_id == tenant_uuid,
                        MemoryEvent.user_id == user_uuid,
                        MemoryEvent.consent_state == "granted",
                        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
                    )
                    .order_by(
                        MemoryUserGoal.target_at.asc().nullslast(),
                        MemoryUserGoal.updated_at.desc(),
                    )
                    .limit(bounded)
                )
            ).all()

            loops = (
                await session.execute(
                    select(MemoryOpenLoop, MemoryEvent.event_id)
                    .join(MemoryEvent, MemoryEvent.event_id == MemoryOpenLoop.event_id)
                    .where(
                        MemoryOpenLoop.tenant_id == tenant_uuid,
                        MemoryOpenLoop.user_id == user_uuid,
                        MemoryOpenLoop.lifecycle_state == "open",
                        or_(MemoryOpenLoop.valid_to.is_(None), MemoryOpenLoop.valid_to > now),
                        MemoryEvent.tenant_id == tenant_uuid,
                        MemoryEvent.user_id == user_uuid,
                        MemoryEvent.consent_state == "granted",
                        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
                    )
                    .order_by(
                        MemoryOpenLoop.target_at.asc().nullslast(),
                        MemoryOpenLoop.updated_at.desc(),
                    )
                    .limit(bounded)
                )
            ).all()

            prospective = (
                await session.execute(
                    select(MemoryProspectiveItem, MemoryEvent.event_id)
                    .join(
                        MemoryEvent,
                        MemoryEvent.event_id == MemoryProspectiveItem.event_id,
                    )
                    .where(
                        MemoryProspectiveItem.tenant_id == tenant_uuid,
                        MemoryProspectiveItem.user_id == user_uuid,
                        MemoryProspectiveItem.lifecycle_state.in_(
                            ("dormant", "ready", "triggered")
                        ),
                        or_(
                            MemoryProspectiveItem.valid_to.is_(None),
                            MemoryProspectiveItem.valid_to > now,
                        ),
                        MemoryEvent.tenant_id == tenant_uuid,
                        MemoryEvent.user_id == user_uuid,
                        MemoryEvent.consent_state == "granted",
                        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
                    )
                    .order_by(
                        MemoryProspectiveItem.target_at.asc().nullslast(),
                        MemoryProspectiveItem.updated_at.desc(),
                    )
                    .limit(bounded)
                )
            ).all()

        items: list[ContinuityStateItem] = []
        for row, event_id in goals:
            payload = dict(row.metadata_payload or {})
            items.append(
                ContinuityStateItem(
                    item_id=str(row.goal_id),
                    source_type="goal",
                    description=str(row.description),
                    confidence=float(row.confidence or 0.0),
                    lifecycle_state=str(row.lifecycle_state),
                    source_event_id=str(event_id),
                    target_at=self._aware(row.target_at),
                    domain=self._domain(payload),
                    metadata=payload,
                )
            )
        for row, event_id in loops:
            payload = dict(row.metadata_payload or {})
            items.append(
                ContinuityStateItem(
                    item_id=str(row.open_loop_id),
                    source_type="open_loop",
                    description=str(row.description),
                    confidence=float(row.confidence or 0.0),
                    lifecycle_state=str(row.lifecycle_state),
                    source_event_id=str(event_id),
                    target_at=self._aware(row.target_at),
                    domain=row.domain or self._domain(payload),
                    metadata=payload,
                )
            )
        for row, event_id in prospective:
            payload = dict(row.metadata_payload or {})
            items.append(
                ContinuityStateItem(
                    item_id=str(row.prospective_id),
                    source_type="prospective",
                    description=str(row.description),
                    confidence=float(row.confidence or 0.0),
                    lifecycle_state=str(row.lifecycle_state),
                    source_event_id=str(event_id),
                    target_at=self._aware(row.target_at),
                    domain=self._domain(payload),
                    metadata={
                        **payload,
                        "event_type": row.event_type,
                        "temporal_text": row.temporal_text,
                    },
                )
            )
        return items[:bounded]

    @staticmethod
    def _domain(payload: dict[str, object]) -> str | None:
        value = str(payload.get("domain") or "").strip()
        return value or None

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = ["PostgresContinuityStateRepository"]
