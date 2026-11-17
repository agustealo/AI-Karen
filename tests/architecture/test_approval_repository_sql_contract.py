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



def test_approval_decision_uses_one_explicit_sql_parameter_type() -> None:
    """PostgreSQL asyncpg cannot infer both varchar and text for one bind."""
    repository = REPOSITORY.read_text(encoding="utf-8")
    decision_sql = repository.split("async def decide", 1)[1].split(
        "async def consume_approved", 1
    )[0]
    assert "SET status = CAST(:decision AS varchar(16))" in decision_sql
    assert "WHEN CAST(:decision AS varchar(16)) = 'rejected'" in decision_sql
    assert "WHEN :decision = 'rejected'" not in decision_sql
    assert "decided_by = CAST(:decided_by AS uuid)" in decision_sql
    assert "status = 'pending'" in decision_sql
    assert "expires_at > now()" in decision_sql
