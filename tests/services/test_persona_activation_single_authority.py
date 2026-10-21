"""Preference activation must use the single transactional authority."""
import pytest

from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_preferences_activation_uses_atomic_owner():
    service = PersonaService.__new__(PersonaService)
    called = []

    async def atomic(user_id, tenant_id, persona_id, expected_revision=None):
        called.append((user_id, tenant_id, persona_id))
        return {"active_persona_id": persona_id}

    service._switch_persona_atomically = atomic
    result = await service.update_user_preferences(
        "user-a", "tenant-a", {"active_persona_id": "expert"}
    )
    assert result == {"active_persona_id": "expert"}
    assert called == [("user-a", "tenant-a", "expert")]


@pytest.mark.asyncio
async def test_preferences_reject_mixed_activation_and_style_mutation():
    service = PersonaService.__new__(PersonaService)
    with pytest.raises(ValueError, match="separately"):
        await service.update_user_preferences(
            "user-a", "tenant-a",
            {"active_persona_id": "expert", "default_language": "en_US"},
        )
