"""Persona-aware recall is decided by persisted scope, never client metadata."""
from pathlib import Path


def test_evidence_resolver_uses_backend_persona_preferences():
    source = Path("src/ai_karen_engine/core/runtime/evidence_resolver.py").read_text()
    start = source.index("    async def _resolve_memory(")
    stop = source.find("    async def ", start + 10)
    implementation = source[start:] if stop == -1 else source[start:stop]
    assert "get_persona_service().get_user_preferences(" in implementation
    assert "user_id=ctx.user_id, tenant_id=ctx.tenant_id" in implementation
    assert "preferences.enable_persona_memory_filtering" in implementation
    assert "not preferences.cross_persona_memory_sharing" in implementation
    assert "persona_filter=persona_filter" in implementation
    assert "persona_scope_unavailable" in implementation
    assert 'request.metadata.get("persona_filter")' not in implementation
