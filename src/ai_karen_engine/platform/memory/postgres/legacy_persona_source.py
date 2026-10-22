"""Read-only legacy source-record verification scoped to a trusted principal.

Returns no user content. A matching row is not proof of canonical identity,
consent, retention, or authorization to migrate.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


def _validated_source_id(value: object) -> str | None:
    """Validate a canonical source key without coercing caller objects."""
    if not isinstance(value, str):
        return None
    source_id = value.strip()
    if not source_id or len(source_id) > 64:
        return None
    return source_id


async def verify_legacy_persona_source(
    *, tenant_id: str, user_id: str, source_record_id: str,
) -> bool:
    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    source_id = _validated_source_id(source_record_id)
    if source_id is None:
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
    source_id = _validated_source_id(source_record_id)
    if source_id is None:
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
    if (
        row is None
        or not isinstance(row.created_at, datetime)
        or not isinstance(row.memory_type, str)
        or not row.memory_type.strip()
        or row.memory_type != row.memory_type.strip()
    ):
        return None
    return row.created_at, row.memory_type


async def lock_legacy_migration_evidence(
    *, tenant_id: str, user_id: str, source_record_id: str,
) -> tuple[datetime, str] | None:
    """Lock canonical source, active identity, consent and retention in one transaction.

    Read-only verification primitive for a future governed executor. Locks are
    released on return; this function does NOT authorize a later write. A future
    writer must perform its final policy gate and ledger insertion before the
    same transaction commits.
    """
    from sqlalchemy import select
    from ai_karen_engine.platform.memory.postgres.ledger_models import (
        ConsentScope, RetentionPolicy,
    )
    from datetime import timedelta, timezone

    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    source_id = _validated_source_id(source_record_id)
    if source_id is None:
        return None
    async with async_transaction_scope(tenant_id=tenant) as session:
        return await verify_locked_legacy_migration_evidence(
            session=session, tenant_id=tenant, user_id=user,
            source_record_id=source_id,
        )


async def verify_locked_legacy_migration_evidence(
    *, session: "AsyncSession", tenant_id: str, user_id: str,
    source_record_id: str,
) -> tuple[datetime, str] | None:
    """Check canonical evidence using a caller-owned active transaction.

    No commit or rollback occurs here. Caller must hold this transaction
    through any future governed write; this function never grants one.
    """
    from datetime import timedelta, timezone
    from sqlalchemy import select
    from ai_karen_engine.platform.memory.postgres.ledger_models import (
        ConsentScope, RetentionPolicy,
    )

    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    source_id = _validated_source_id(source_record_id)
    if source_id is None:
        return None
        principal = await session.execute(text(
            "SELECT user_id FROM public.auth_users WHERE user_id=:user "
            "AND tenant_id=:tenant AND is_active IS TRUE "
            "AND is_verified IS TRUE FOR UPDATE"
        ), {"user": user, "tenant": tenant})
        if principal.scalar_one_or_none() is None:
            return None
        source = await session.execute(text(
            "SELECT created_at, memory_type FROM public.persona_memory_entries "
            "WHERE id=:source AND tenant_id=:tenant AND user_id=:user "
            "AND length(btrim(content)) > 0 FOR UPDATE"
        ), {"source": source_id, "tenant": tenant, "user": user})
        row = source.one_or_none()
        if (
            row is None or not isinstance(row.created_at, datetime)
            or not isinstance(row.memory_type, str)
            or not row.memory_type.strip()
            or row.memory_type != row.memory_type.strip()
        ):
            return None
        created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if created > now:
            return None
        grant = await session.execute(
            select(ConsentScope).where(
                ConsentScope.tenant_id == uuid.UUID(tenant),
                ConsentScope.user_id == uuid.UUID(user),
                ConsentScope.scope_name == "persona-memory-migration",
            ).order_by(
                ConsentScope.granted_at.desc(), ConsentScope.scope_id.desc()
            ).limit(1).with_for_update()
        )
        consent = grant.scalar_one_or_none()
        if consent is None or consent.is_granted is not True:
            return None
        policy_query = select(RetentionPolicy).where(
            RetentionPolicy.tenant_id == uuid.UUID(tenant),
            RetentionPolicy.memory_class == row.memory_type,
        ).order_by(RetentionPolicy.updated_at.desc()).limit(1).with_for_update()
        policy = (await session.execute(policy_query)).scalar_one_or_none()
        if policy is None:
            policy = (await session.execute(
                select(RetentionPolicy).where(
                    RetentionPolicy.tenant_id.is_(None),
                    RetentionPolicy.memory_class == row.memory_type,
                ).order_by(RetentionPolicy.updated_at.desc())
                .limit(1).with_for_update()
            )).scalar_one_or_none()
        if (
            policy is None or policy.ttl_days is None
            or policy.ttl_days <= 0
            or created + timedelta(days=int(policy.ttl_days)) <= now
        ):
            return None
        return row.created_at, row.memory_type
