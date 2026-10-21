"""Legacy persona memory must expose failures rather than invent success.

This is a fail-closed transition guard, not an alternative memory runtime.
The eventual durable memory owner remains canonical NeuroVault.
"""
import pytest

from ai_karen_engine.core.persona.contracts import ChatStyleContext
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_legacy_memory_store_failure_is_not_reported_as_success():
    service = PersonaService.__new__(PersonaService)
    async def failed_store(entry):
        return False
    service._store_memory_entry = failed_store
    context = ChatStyleContext()
    with pytest.raises(RuntimeError, match="not persisted"):
        await service.store_persona_memory(
            user_id="u", tenant_id="t", content="Relevant user statement",
            context=context,
        )


@pytest.mark.asyncio
async def test_legacy_recall_unavailable_is_not_reported_as_empty_memory():
    service = PersonaService.__new__(PersonaService)
    service.db_client = None
    with pytest.raises(RuntimeError, match="unavailable"):
        await service._retrieve_memories("what did I say", {"user_id": "u", "tenant_id": "t"}, 5)
