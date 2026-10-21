"""Legacy memory reference scanner finds production callers without DB access."""
from pathlib import Path

from scripts.audit.persona_memory_references import audit


def test_audit_detects_symbol_with_location(tmp_path: Path):
    target = tmp_path / "src" / "caller.py"
    target.parent.mkdir()
    target.write_text("service.store_persona_memory('x')\n", encoding="utf-8")
    result = audit(tmp_path)
    assert result == [
        {"path": "src/caller.py", "line": 1, "symbol": "store_persona_memory"}
    ]


def test_audit_skips_build_outputs(tmp_path: Path):
    build = tmp_path / "node_modules"
    build.mkdir()
    (build / "caller.py").write_text("_retrieve_memories()", encoding="utf-8")
    assert audit(tmp_path) == []
