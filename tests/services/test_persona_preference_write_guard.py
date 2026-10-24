"""Fail-closed persona preference persistence contract."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.persona import persona_service as module


@pytest.mark.asyncio
async def test_failed_preference_write_never_acknowledges_or_updates_cache(monkeypatch):
    class Preferences:
        def __init__(self, **values):
            self.__dict__.update(values)

        def dict(self):
            return vars(self).copy()

    monkeypatch.setattr(module, "UserPersonaPreferences", Preferences)
    service = module.PersonaService.__new__(module.PersonaService)
    original = Preferences(
        user_id="alice",
        tenant_id="tenant-a",
        active_persona_id=None,
        updated_at=None,
    )
    service._user_preferences_cache = {"alice:tenant-a": original}

    async def get_preferences(user_id, tenant_id):
        return original

    async def get_persona(persona_id, user_id, tenant_id):
        return SimpleNamespace(id=persona_id)

    async def failing_save(user_id, tenant_id, preferences):
        return False

    service.get_user_preferences = get_preferences
    service.get_persona = get_persona
    service._save_user_preferences = failing_save

    with pytest.raises(RuntimeError, match="not persisted"):
        await service.update_user_preferences(
            "alice", "tenant-a", {"active_persona_id": "troy"}
        )

    assert original.active_persona_id is None
    assert service._user_preferences_cache["alice:tenant-a"] is original

    with pytest.raises(ValueError, match="Unsupported"):
        await service.update_user_preferences(
            "alice", "tenant-a", {"is_admin": True}
        )
