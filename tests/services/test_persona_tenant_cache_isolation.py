"""Regression tests for tenant-scoped custom persona lookup.

Custom persona IDs must never resolve from a process-global cache, even when
another tenant has previously loaded the same identifier.
"""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_custom_persona_does_not_cross_user_or_tenant() -> None:
    service = PersonaService.__new__(PersonaService)
    service._persona_cache = {persona.id: persona for persona in __import__(
        "ai_karen_engine.core.persona.contracts",
        fromlist=["SYSTEM_PERSONAS"],
    ).SYSTEM_PERSONAS}

    seen = []
    async def preferences(user_id: str, tenant_id: str):
        seen.append((user_id, tenant_id))
        if (user_id, tenant_id) == ("alice", "tenant-a"):
            return SimpleNamespace(custom_personas=[SimpleNamespace(id="shared-id", name="Alice")])
        if (user_id, tenant_id) == ("bob", "tenant-b"):
            return SimpleNamespace(custom_personas=[SimpleNamespace(id="shared-id", name="Bob")])
        return SimpleNamespace(custom_personas=[])

    service.get_user_preferences = preferences

    alice = await service.get_persona("shared-id", "alice", "tenant-a")
    bob = await service.get_persona("shared-id", "bob", "tenant-b")

    assert alice.name == "Alice"
    assert bob.name == "Bob"
    assert await service.get_persona("shared-id", "alice", "tenant-b") is None
    assert await service.get_persona("shared-id") is None
    assert "shared-id" not in service._persona_cache
    assert seen == [
        ("alice", "tenant-a"),
        ("bob", "tenant-b"),
        ("alice", "tenant-b"),
    ]
