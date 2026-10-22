import pytest
"""Legacy memory reference scanner finds production callers without DB access."""
from pathlib import Path

from scripts.audit.persona_memory_references import audit, classify


def _complete_checkout(root: Path) -> None:
    for directory in ("src/ai_karen_engine", "supabase/migrations", "tests"):
        (root / directory).mkdir(parents=True, exist_ok=True)



def test_audit_detects_symbol_with_location(tmp_path: Path):
    target = tmp_path / "src" / "caller.py"
    target.parent.mkdir()
    target.write_text("service.store_persona_memory('x')\n", encoding="utf-8")
    _complete_checkout(tmp_path)
    result = audit(tmp_path)
    assert result == [
        {"path": "src/caller.py", "line": 1, "symbol": "store_persona_memory", "classification": "requires_review"}
    ]


def test_audit_skips_build_outputs(tmp_path: Path):
    build = tmp_path / "node_modules"
    build.mkdir()
    (build / "caller.py").write_text("_retrieve_memories()", encoding="utf-8")
    _complete_checkout(tmp_path)
    assert audit(tmp_path) == []


def test_declaration_is_not_mistaken_for_live_invocation():
    assert classify("src/ai_karen_engine/services/persona/persona_service.py",
                    "store_persona_memory", "    async def store_persona_memory(") == "compatibility_declaration"
    assert classify("src/ai_karen_engine/core/runtime/consumer.py",
                    "store_persona_memory", "await service.store_persona_memory(") == "requires_review"
    assert classify("supabase/migrations/legacy.sql",
                    "persona_memory_entries", "CREATE TABLE persona_memory_entries (") == "historical_schema"


def test_audit_does_not_silently_accept_missing_checkout(tmp_path: Path):
    with pytest.raises(ValueError, match="existing directory"):
        audit(tmp_path / "missing")


def test_audit_ignores_symlinks_that_escape_repository(tmp_path: Path):
    outside = tmp_path.parent / "legacy_reference_outside.py"
    outside.write_text("store_persona_memory()\n", encoding="utf-8")
    (tmp_path / "outside.py").symlink_to(outside)
    assert audit(tmp_path) == []


def test_audit_refuses_partial_checkout(tmp_path: Path):
    with pytest.raises(ValueError, match="full AI-Karen checkout"):
        audit(tmp_path)
