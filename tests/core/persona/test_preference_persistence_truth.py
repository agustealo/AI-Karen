"""Persona preference writes must not report success when persistence fails."""

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.persona.contracts import UserPersonaPreferences
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_missing_storage_fails_instead_of_reporting_success():
    service = object.__new__(PersonaService)
    service.db_client = None
    preferences = UserPersonaPreferences(user_id="owner", tenant_id="tenant")
    with pytest.raises(RuntimeError, match="persona_preferences_storage_unavailable"):
        await service._save_user_preferences("owner", "tenant", preferences)


@pytest.mark.asyncio
async def test_update_does_not_replace_cached_preferences_on_failed_write():
    service = object.__new__(PersonaService)
    original = UserPersonaPreferences(user_id="owner", tenant_id="tenant")
    service._user_preferences_cache = {"owner:tenant": original}
    service.get_user_preferences = AsyncMock(return_value=original)
    service.get_persona = AsyncMock()
    service._save_user_preferences = AsyncMock(side_effect=RuntimeError("persona_preferences_write_failed"))

    with pytest.raises(RuntimeError, match="persona_preferences_write_failed"):
        await service.update_user_preferences("owner", "tenant", {"show_style_controls": False})

    assert service._user_preferences_cache["owner:tenant"] is original
    assert original.show_style_controls is True
