"""Persona provenance must originate from scoped backend preferences, never client metadata."""
from pathlib import Path


def test_chat_runtime_persona_provenance_boundary():
    source = Path("src/ai_karen_engine/core/runtime/chat_runtime.py").read_text()
    start = source.index("    async def _persist_memory(")
    stop = source.index("    async def ", start + 10)
    implementation = source[start:stop]
    assert "get_persona_service().get_user_preferences(" in implementation
    assert "user_id=ctx.user_id, tenant_id=ctx.tenant_id" in implementation
    assert 'persona_provenance["persona_id"] = selected_persona_id' in implementation
    assert '"memory_actor": "user",\n                    **persona_provenance,' in implementation
    assert 'request.metadata.get("persona_id")' not in implementation
    assert '"memory_write_authorized": True' in implementation
    assert "ActionExecutionGate.authorize(plan, \"memory.write\")" in implementation
