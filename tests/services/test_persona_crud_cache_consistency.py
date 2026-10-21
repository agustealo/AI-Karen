"""Persona definition writes must not duplicate preference persistence."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.persona.contracts import Persona, UserPersonaPreferences
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_create_persona_invalidates_cache_without_writing_preferences() -> None:
    service = PersonaService.__new__(PersonaService)
    preferences = UserPersonaPreferences(user_id="alice", tenant_id="tenant-a")
    service._user_preferences_cache = {"alice:tenant-a": preferences}
    writes = []

    async def get_preferences(user_id, tenant_id):
        return preferences

    async def insert(user_id, tenant_id, persona):
        writes.append(("insert", persona.name))

    async def forbidden_preferences_write(*args):
        raise AssertionError("Persona definition must not rewrite user preferences")

    service.get_user_preferences = get_preferences
    service._insert_persona = insert
    service._save_user_preferences = forbidden_preferences_write

    created = await service.create_persona(
        "alice", "tenant-a", {"name": "Troy", "system_prompt": "Design collaborator"}
    )

    assert created.name == "Troy"
    assert writes == [("insert", "Troy")]
    assert preferences.custom_personas == []
    assert "alice:tenant-a" not in service._user_preferences_cache


@pytest.mark.asyncio
async def test_update_persona_invalidates_cache_without_rewriting_preferences() -> None:
    service = PersonaService.__new__(PersonaService)
    original = Persona(name="Troy", system_prompt="Design collaborator")
    preferences = UserPersonaPreferences(
        user_id="alice", tenant_id="tenant-a", custom_personas=[original]
    )
    service._user_preferences_cache = {"alice:tenant-a": preferences}
    writes = []

    async def get_preferences(user_id, tenant_id):
        return preferences

    async def update(user_id, tenant_id, persona):
        writes.append(("update", persona.name))

    async def forbidden_preferences_write(*args):
        raise AssertionError("Persona definition must not rewrite user preferences")

    service.get_user_preferences = get_preferences
    service._update_persona_record = update
    service._save_user_preferences = forbidden_preferences_write

    result = await service.update_persona(
        "alice", "tenant-a", original.id, {"name": "Troy Design"}
    )

    assert result.name == "Troy Design"
    assert writes == [("update", "Troy Design")]
    assert preferences.custom_personas[0].name == "Troy"
    assert "alice:tenant-a" not in service._user_preferences_cache
