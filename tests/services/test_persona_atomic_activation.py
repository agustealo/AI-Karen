"""Persona activation delegates to the canonical transactional path."""
import pytest

from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_switch_calls_transactional_selection() -> None:
    service = PersonaService.__new__(PersonaService)
    observed = []

    async def transactional(user_id, tenant_id, persona_id):
        observed.append((user_id, tenant_id, persona_id))
        return {"active_persona_id": persona_id}

    service._switch_persona_atomically = transactional

    result = await service.switch_persona("alice", "tenant-a", "troy")
    assert result == {"active_persona_id": "troy"}
    assert observed == [("alice", "tenant-a", "troy")]


@pytest.mark.asyncio
async def test_switch_clear_uses_same_transactional_path() -> None:
    service = PersonaService.__new__(PersonaService)
    observed = []

    async def transactional(user_id, tenant_id, persona_id):
        observed.append(persona_id)
        return {"active_persona_id": persona_id}

    service._switch_persona_atomically = transactional

    assert (await service.switch_persona("alice", "tenant-a", None))["active_persona_id"] is None
    assert observed == [None]
