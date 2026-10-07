from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = (
    ROOT
    / "src/ai_karen_engine/persistence/repositories/approval_repository.py"
)


def test_actionable_approval_filter_types_nullable_conversation_id() -> None:
    repository = REPOSITORY.read_text(encoding="utf-8")

    assert "CAST(:conversation_id AS uuid) IS NULL" in repository
    assert "conversation_id = CAST(:conversation_id AS uuid)" in repository
    assert ":conversation_id IS NULL" not in repository


def test_actionable_approval_filter_remains_tenant_and_user_scoped() -> None:
    repository = REPOSITORY.read_text(encoding="utf-8")

    list_actionable = repository.split("async def list_actionable", 1)[1].split(
        "async def decide", 1
    )[0]

    assert "tenant_id = CAST(:tenant_id AS uuid)" in list_actionable
    assert "user_id = CAST(:user_id AS uuid)" in list_actionable
    assert "status IN ('pending', 'approved')" in list_actionable
