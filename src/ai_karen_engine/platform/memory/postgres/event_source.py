"""Canonical PostgreSQL source expansion for memory-event references."""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import MemoryEvent


class PostgresEventSourceScopeError(ValueError):
    """Raised when event expansion lacks valid tenant/user scope."""


class PostgresEventSource:
    """Expand governed memory-event IDs back to canonical ledger rows."""

    async def fetch_many(
        self,
        *,
        tenant_id: str,
        user_id: str,
        event_ids: Iterable[str],
    ) -> dict[str, dict]:
        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
            user_uuid = uuid.UUID(str(user_id))
        except ValueError as exc:
            raise PostgresEventSourceScopeError("tenant_id and user_id must be valid UUIDs") from exc

        ids: list[uuid.UUID] = []
        for value in event_ids:
            try:
                parsed = uuid.UUID(str(value))
            except ValueError:
                continue
            if parsed not in ids:
                ids.append(parsed)
        if not ids:
            return {}

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            stmt = select(MemoryEvent).where(
                MemoryEvent.tenant_id == tenant_uuid,
                MemoryEvent.user_id == user_uuid,
                MemoryEvent.event_id.in_(ids),
                MemoryEvent.consent_state == "granted",
            )
            rows = (await session.execute(stmt)).scalars().all()

        return {
            str(row.event_id): {
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "payload": row.payload,
                "confidence": float(row.confidence or 0.0),
                "valid_from": row.valid_from,
                "valid_to": row.valid_to,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "source_type": row.source_type,
                "source_ref": row.source_ref,
            }
            for row in rows
        }


__all__ = ["PostgresEventSource", "PostgresEventSourceScopeError"]
