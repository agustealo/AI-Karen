"""Legacy source verification must be scoped and content-free."""
from pathlib import Path


def test_source_verification_reads_no_personal_content():
    source = Path("src/ai_karen_engine/platform/memory/postgres/legacy_persona_source.py").read_text()
    assert "WHERE id = :source_id AND tenant_id = :tenant_id " in source
    assert "AND user_id = :user_id" in source
    assert "length(btrim(content)) > 0" in source
    assert "SELECT EXISTS (" in source
    assert "SELECT content" not in source
    assert "INSERT INTO" not in source
    assert "DELETE FROM" not in source
