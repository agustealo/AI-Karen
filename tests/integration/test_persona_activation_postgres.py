"""Disposable PostgreSQL proof for persona activation and deletion races.

Requires existing migrated schema and a seeded user/tenant. This test does not
create schema or run against production. Run with:
KAREN_TEST_DISPOSABLE_DATABASE=1 KAREN_TEST_PERSONA_POSTGRES=1
KAREN_TEST_PERSONA_USER_ID=... KAREN_TEST_PERSONA_TENANT_ID=... pytest -q
tests/integration/test_persona_activation_postgres.py
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.services.persona.persona_service import PersonaService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
        or os.getenv("KAREN_TEST_PERSONA_POSTGRES") != "1",
        reason="Requires opted-in, migrated, disposable PostgreSQL",
    ),
]


async def test_concurrent_switch_delete_and_scoped_denial() -> None:
    user_id = os.getenv("KAREN_TEST_PERSONA_USER_ID")
    tenant_id = os.getenv("KAREN_TEST_PERSONA_TENANT_ID")
    if not user_id or not tenant_id:
        pytest.skip("Seed an authorized disposable user and tenant")

    db = MultiTenantPostgresClient()
    service = PersonaService(db_client=db)
    persona_id = str(uuid4())
    try:
        # Use actual database-backed service methods, not mocked locks.
        await service.create_persona(
            user_id, tenant_id,
            {
                "id": persona_id,
                "name": "Race-proof " + persona_id[:8],
                "system_prompt": "Present design guidance concisely.",
            },
        )
        await service.switch_persona(user_id, tenant_id, persona_id)
        # Deny cross-user/tenant use while the custom persona still exists.
        # The fixture user/tenant values are isolated to disposable CI.
        for other_user, other_tenant in (
            ("persona-ci-other-user", tenant_id),
            (user_id, "persona-ci-other-tenant"),
        ):
            with pytest.raises(ValueError, match="unavailable"):
                await service.switch_persona(other_user, other_tenant, persona_id)
        async with db.get_async_session() as session:
            selected = await session.scalar(
                text(
                    "SELECT active_persona_id FROM user_persona_preferences "
                    "WHERE tenant_id=:tenant AND user_id=:user"
                ),
                {"tenant": tenant_id, "user": user_id},
            )
        assert selected == persona_id

        outcomes = await asyncio.gather(
            service.switch_persona(user_id, tenant_id, persona_id),
            service.delete_persona(user_id, tenant_id, persona_id),
            return_exceptions=True,
        )
        # Either activation precedes deletion, or activation fails after
        # deletion; no committed preference can reference the deleted persona.
        assert outcomes[1] is True
        assert not isinstance(outcomes[0], Exception) or isinstance(outcomes[0], ValueError)
        async with db.get_async_session() as session:
            row = await session.execute(
                text(
                    "SELECT p.active_persona_id, c.id "
                    "FROM user_persona_preferences p "
                    "LEFT JOIN custom_personas c ON c.id=p.active_persona_id "
                    "AND c.tenant_id=p.tenant_id AND c.user_id=p.user_id "
                    "WHERE p.tenant_id=:tenant AND p.user_id=:user"
                ),
                {"tenant": tenant_id, "user": user_id},
            )
            active, existing = row.one()
        assert active is None
        assert existing is None

        with pytest.raises(ValueError, match="unavailable"):
            await service.switch_persona(user_id, tenant_id, persona_id)


    finally:
        await service._delete_persona_record(user_id, tenant_id, persona_id)
        service._user_preferences_cache.pop(service._cache_key(user_id, tenant_id), None)
