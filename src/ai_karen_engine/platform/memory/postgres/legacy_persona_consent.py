"""Read-only explicit consent evidence for historical memory migration.

Unlike ordinary chat writes, historical import requires a current, affirmative
grant. Absence is denial. NeuroVault still independently enforces consent.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import ConsentScope


async def verify_legacy_migration_consent(
    *, tenant_id: str, user_id: str, consent_scope: str,
) -> bool:
    tenant = uuid.UUID(tenant_id)
    user = uuid.UUID(user_id)
    scope = str(consent_scope or "").strip()
    if not scope or scope != "persona-memory-migration":
        return False
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
        result = await session.execute(
            select(ConsentScope.is_granted)
            .where(
                ConsentScope.tenant_id == tenant,
                ConsentScope.user_id == user,
                ConsentScope.scope_name == scope,
            )
            .order_by(ConsentScope.granted_at.desc(), ConsentScope.scope_id.desc())
            .limit(1)
        )
        grant = result.scalar_one_or_none()
    return grant is True
