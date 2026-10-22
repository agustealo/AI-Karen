"""Persona preferences must reflect committed persistence, never failed writes."""
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.persona.contracts import UserPersonaPreferences
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_failed_persona_preference_write_preserves_cached_selection():
    service = PersonaService.__new__(PersonaService)
    service._user_preferences_cache = {}
    previous = UserPersonaPreferences(user_id="user-a", tenant_id="tenant-a")
    service._user_preferences_cache[service._cache_key("user-a", "tenant-a")] = previous
    service._save_user_preferences = AsyncMock(side_effect=RuntimeError("write rejected"))

    with pytest.raises(RuntimeError, match="write rejected"):
        await service.update_user_preferences(
            "user-a", "tenant-a", {"show_persona_selector": False},
        )

    cached = await service.get_user_preferences("user-a", "tenant-a")
    assert cached.show_persona_selector == previous.show_persona_selector
    assert cached is previous
    service._save_user_preferences.assert_awaited_once()
