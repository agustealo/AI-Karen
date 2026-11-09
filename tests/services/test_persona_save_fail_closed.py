"""Regression tests for canonical persona preference persistence failures."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.persona.contracts import UserPersonaPreferences
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_missing_preference_storage_is_a_failure():
    service = object.__new__(PersonaService)
    service.db_client = None
    preferences = UserPersonaPreferences(user_id="owner", tenant_id="tenant")

    with pytest.raises(RuntimeError, match="persona_preferences_storage_unavailable"):
        await service._save_user_preferences("owner", "tenant", preferences)



@pytest.mark.asyncio
async def test_persistence_failure_is_visible():
    """KCON-770/08: failed persona write cannot create a saved-state receipt."""
    service = object.__new__(PersonaService)
    service.db_client = object()
    user_id = "11111111-1111-1111-1111-111111111111"
    tenant_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    preferences = UserPersonaPreferences(user_id=user_id, tenant_id=tenant_id)
    service._user_preferences_cache = {}
    service.get_user_preferences = AsyncMock(return_value=preferences)

    @asynccontextmanager
    async def failed_session(scoped_tenant):
        assert scoped_tenant == tenant_id
        session = AsyncMock()
        session.execute.side_effect = OSError("canonical preferences database offline")
        yield session

    service._tenant_session = failed_session
    with pytest.raises(OSError, match="canonical preferences database offline"):
        await service.update_user_preferences(
            user_id, tenant_id, {"show_persona_selector": False},
        )

    # No optimistic cache, revision, or alternate tenant/user recovery receipt.
    assert service._user_preferences_cache == {}
    assert preferences.show_persona_selector is True
    service.get_user_preferences.assert_awaited_once_with(user_id, tenant_id)


@pytest.mark.asyncio
async def test_preference_write_exception_is_not_reported_as_success():
    service = object.__new__(PersonaService)
    service.db_client = object()
    preferences = UserPersonaPreferences(user_id="owner", tenant_id="tenant")

    @asynccontextmanager
    async def failed_session(tenant_id):
        session = AsyncMock()
        session.execute.side_effect = OSError("database disconnected")
        yield session

    service._tenant_session = failed_session

    with pytest.raises(RuntimeError, match="persona_preferences_write_failed"):
        await service._save_user_preferences("owner", "tenant", preferences)
