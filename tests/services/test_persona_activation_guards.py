"""Persona activation and first-write failure regression tests."""
from types import SimpleNamespace
import pytest
from ai_karen_engine.services.persona import persona_service as module

@pytest.mark.asyncio
async def test_initial_preferences_failure_does_not_cache_or_confirm():
    service = module.PersonaService.__new__(module.PersonaService)
    service._user_preferences_cache = {}
    async def load(*args):
        return None
    async def save(*args):
        return False
    service._load_user_preferences = load
    service._save_user_preferences = save
    with pytest.raises(RuntimeError, match="not persisted"):
        await service.get_user_preferences("alice", "tenant-a")
    assert service._user_preferences_cache == {}

@pytest.mark.asyncio
async def test_cannot_activate_inactive_persona():
    service = module.PersonaService.__new__(module.PersonaService)
    async def get_persona(*args):
        return SimpleNamespace(id="troy", is_active=False)
    async def update(*args):
        raise AssertionError("Denied activation must not persist")
    service.get_persona = get_persona
    service.update_user_preferences = update
    with pytest.raises(ValueError, match="unavailable"):
        await service.switch_persona("alice", "tenant-a", "troy")
