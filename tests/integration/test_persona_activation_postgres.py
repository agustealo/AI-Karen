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
from sqlalchemy.exc import IntegrityError

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

        # The database must reject a bypass of PersonaService's authorization
        # checks, not merely rely on the application-side guard.
        with pytest.raises(IntegrityError):
            async with db.get_async_session() as session:
                await session.execute(
                    text(
                        "UPDATE user_persona_preferences "
                        "SET active_persona_id=:candidate "
                        "WHERE tenant_id=:tenant AND user_id=:user"
                    ),
                    {"candidate": str(uuid4()), "tenant": tenant_id, "user": user_id},
                )

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


        # A failed transaction must roll back the preference mutation.
        await service.switch_persona(user_id, tenant_id, "assistant")
        with pytest.raises(RuntimeError, match="force rollback"):
            async with db.get_async_session() as session:
                await session.execute(
                    text(
                        "UPDATE user_persona_preferences "
                        "SET active_persona_id = NULL "
                        "WHERE tenant_id = :tenant AND user_id = :user"
                    ),
                    {"tenant": tenant_id, "user": user_id},
                )
                raise RuntimeError("force rollback")
        async with db.get_async_session() as session:
            persisted = await session.scalar(
                text(
                    "SELECT active_persona_id FROM user_persona_preferences "
                    "WHERE tenant_id = :tenant AND user_id = :user"
                ),
                {"tenant": tenant_id, "user": user_id},
            )
        assert persisted == "assistant"

        # A fresh service instance must observe the committed database value,
        # rather than a process-local cache entry.
        reopened = PersonaService(db_client=MultiTenantPostgresClient())
        fresh = await reopened.get_user_preferences(user_id, tenant_id)
        assert fresh.active_persona_id == "assistant"

        # Overlapping writes to independent settings must both survive.
        await asyncio.gather(
            service.update_user_preferences(
                user_id, tenant_id, {"default_language": "french"}
            ),
            reopened.update_user_preferences(
                user_id, tenant_id, {"show_style_controls": False}
            ),
        )
        async with db.get_async_session() as session:
            persisted_style = await session.execute(
                text(
                    "SELECT active_persona_id, default_language, show_style_controls "
                    "FROM user_persona_preferences "
                    "WHERE tenant_id=:tenant AND user_id=:user"
                ),
                {"tenant": tenant_id, "user": user_id},
            )
            active_id, language, controls = persisted_style.one()
        assert active_id == "assistant"
        assert language == "french"
        assert controls is False

        # Same-setting edits with a shared expected revision cannot both win.
        async with db.get_async_session() as session:
            revision = await session.scalar(
                text(
                    "SELECT revision FROM user_persona_preferences "
                    "WHERE tenant_id=:tenant AND user_id=:user"
                ),
                {"tenant": tenant_id, "user": user_id},
            )
        competing = await asyncio.gather(
            service.update_user_preferences(
                user_id, tenant_id, {"default_language": "english"},
                expected_revision=revision,
            ),
            reopened.update_user_preferences(
                user_id, tenant_id, {"default_language": "german"},
                expected_revision=revision,
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in competing) == 1
        assert sum(
            isinstance(item, ValueError) and "revision conflict" in str(item)
            for item in competing
        ) == 1

    finally:
        await service._delete_persona_record(user_id, tenant_id, persona_id)
        service._user_preferences_cache.pop(service._cache_key(user_id, tenant_id), None)
