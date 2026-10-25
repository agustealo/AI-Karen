"""Read-only reconciliation of legacy principal with canonical auth_users.

Never resolves legacy identifiers by name/email and never silently remaps a
historical record to a different tenant or user.
"""
from __future__ import annotations

import uuid
from sqlalchemy import text
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


async def verify_legacy_persona_identity(*, tenant_id: str, user_id: str) -> bool:
    tenant = str(uuid.UUID(tenant_id))
    user = str(uuid.UUID(user_id))
    async with async_transaction_scope(tenant_id=tenant) as session:
        result = await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM public.auth_users "
                "WHERE user_id = :user_id AND tenant_id = :tenant_id "
                "AND is_active IS TRUE AND is_verified IS TRUE)"
            ),
            {"user_id": user, "tenant_id": tenant},
        )
        return result.scalar_one() is True
