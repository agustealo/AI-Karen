"""Read-only legacy source-record verification scoped to a trusted principal.

Returns no user content. A matching row is not proof of canonical identity,
consent, retention, or authorization to migrate.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


async def verify_legacy_persona_source(
    *, tenant_id: str, user_id: str, source_record_id: str,
) -> bool:
    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    source_id = str(source_record_id or "").strip()
    if not source_id or len(source_id) > 64:
        return False
    async with async_transaction_scope(tenant_id=tenant) as session:
        result = await session.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM public.persona_memory_entries "
                "WHERE id = :source_id AND tenant_id = :tenant_id "
                "AND user_id = :user_id AND length(btrim(content)) > 0"
                ")"
            ),
            {"source_id": source_id, "tenant_id": tenant, "user_id": user},
        )
        return result.scalar_one() is True


async def read_legacy_persona_source_retention_metadata(
    *, tenant_id: str, user_id: str, source_record_id: str,
) -> tuple[datetime, str] | None:
    """Read only trusted source timestamp and class under tenant/user scope."""
    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    source_id = str(source_record_id or "").strip()
    if not source_id or len(source_id) > 64:
        return None
    async with async_transaction_scope(tenant_id=tenant) as session:
        result = await session.execute(
            text(
                "SELECT created_at, memory_type FROM public.persona_memory_entries "
                "WHERE id = :source_id AND tenant_id = :tenant_id "
                "AND user_id = :user_id AND length(btrim(content)) > 0"
            ),
            {"source_id": source_id, "tenant_id": tenant, "user_id": user},
        )
        row = result.one_or_none()
    if row is None or not isinstance(row.created_at, datetime):
        return None
    return row.created_at, str(row.memory_type)
