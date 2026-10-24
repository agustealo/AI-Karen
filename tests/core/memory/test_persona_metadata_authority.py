"""Persona provenance must not grant memory execution authority."""
import pytest

from ai_karen_engine.core.memory.memory_runtime_manager import MemoryRuntimeManager


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [
    {"persona_id": ""},
    {"persona_id": 77},
    {"persona_tenant_id": "other-tenant"},
    {"persona_user_id": "other-user"},
    {"persona_policy_context": {"memory.write": True}},
    {"persona_memory_write": True},
    {"persona_consent_granted": True},
])
async def test_persona_metadata_cannot_override_memory_authority(metadata):
    manager = MemoryRuntimeManager.__new__(MemoryRuntimeManager)

    class Flags:
        def is_enabled(self, name, tenant_id, user_id):
            return False

    manager.flags = Flags()
    class Shadow:
        async def evaluate(self, **kwargs):
            return {"extracted": 0, "admitted": 0}
    manager._shadow_evaluator = Shadow()
    with pytest.raises(ValueError):
        await manager.process_interaction(
            text="Message", tenant_id="tenant-a", user_id="user-a",
            metadata=metadata,
        )
