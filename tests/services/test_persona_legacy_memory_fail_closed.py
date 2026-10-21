"""Legacy persona memory operations must not bypass canonical governance."""
import pytest

from ai_karen_engine.core.persona.contracts import ChatStyleContext
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_legacy_persona_memory_write_is_denied_without_runtime_policy():
    service = PersonaService.__new__(PersonaService)
    with pytest.raises(RuntimeError, match="authorized memory runtime"):
        await service.store_persona_memory(
            user_id="u", tenant_id="t", content="User statement",
            context=ChatStyleContext(),
        )


@pytest.mark.asyncio
async def test_legacy_persona_recall_is_denied_without_neurorecall():
    service = PersonaService.__new__(PersonaService)
    with pytest.raises(RuntimeError, match="canonical NeuroRecall"):
        await service.recall_persona_memories(
            user_id="u", tenant_id="t", query="my statement",
            context=ChatStyleContext(),
        )


def test_persona_service_has_no_direct_memory_sql_helpers():
    assert not hasattr(PersonaService, "_store_memory_entry")
    assert not hasattr(PersonaService, "_retrieve_memories")
