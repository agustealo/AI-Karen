"""Persona deletion consistency checks."""
from types import SimpleNamespace

import pytest

from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_delete_invalidates_preference_cache_without_second_write():
    service = PersonaService.__new__(PersonaService)
    previous = SimpleNamespace(active_persona_id="troy", custom_personas=[])
    service._user_preferences_cache = {"alice:tenant-a": previous}

    async def delete_record(user_id, tenant_id, persona_id):
        assert (user_id, tenant_id, persona_id) == ("alice", "tenant-a", "troy")
        return 1

    async def forbidden_write(*args, **kwargs):
        raise AssertionError("Preference writes must remain in deletion transaction")

    service._delete_persona_record = delete_record
    service._save_user_preferences = forbidden_write
    assert await service.delete_persona("alice", "tenant-a", "troy")
    assert "alice:tenant-a" not in service._user_preferences_cache


@pytest.mark.asyncio
async def test_missing_delete_preserves_cached_state():
    service = PersonaService.__new__(PersonaService)
    previous = SimpleNamespace(active_persona_id="troy")
    service._user_preferences_cache = {"alice:tenant-a": previous}

    async def missing(*args):
        return 0

    service._delete_persona_record = missing
    assert not await service.delete_persona("alice", "tenant-a", "troy")
    assert service._user_preferences_cache["alice:tenant-a"] is previous
