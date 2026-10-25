"""Read-only historical memory retention assessment using canonical policy.

Absence of an applicable retention policy does not authorize replay. The
source timestamp is evaluated against canonical tenant/global TTL policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import RetentionPolicy


async def verify_legacy_migration_retention(
    *, tenant_id: str, created_at: datetime, memory_class: str,
) -> bool:
    tenant = uuid.UUID(tenant_id)
    if (
        not isinstance(created_at, datetime)
        or not isinstance(memory_class, str)
        or not memory_class.strip()
        or memory_class != memory_class.strip()
    ):
        return False
    created = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if created > now:
        return False
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
        result = await session.execute(
            select(RetentionPolicy)
            .where(
                RetentionPolicy.memory_class == memory_class,
                RetentionPolicy.tenant_id == tenant,
            )
            .order_by(RetentionPolicy.updated_at.desc())
            .limit(1)
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            result = await session.execute(
                select(RetentionPolicy)
                .where(
                    RetentionPolicy.memory_class == memory_class,
                    RetentionPolicy.tenant_id.is_(None),
                )
                .order_by(RetentionPolicy.updated_at.desc())
                .limit(1)
            )
            policy = result.scalar_one_or_none()
    if policy is None or policy.ttl_days is None or policy.ttl_days <= 0:
        return False
    return created + timedelta(days=int(policy.ttl_days)) > now
