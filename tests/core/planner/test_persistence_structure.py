"""Structural safety checks for planner persistence ownership."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "src/ai_karen_engine/persistence/repositories/personal_planner_repository.py"
MIGRATION = ROOT / "supabase/migrations/20261020010000_38_personal_planner_commitments.sql"


def test_planner_repository_uses_existing_tenant_transaction_scope():
    source = REPO.read_text()
    assert "async_transaction_scope(str(tenant_id))" in source
    assert "AND owner_id=:owner" in source
    assert "AND revision=:expected" in source
    assert "PlannerConflictError" in source
    assert "INSERT INTO public.personal_planner_mutation_receipts" in source
    assert "get_chat_runtime" not in source


def test_planner_migration_is_distinct_from_automation_execution():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE public.personal_planner_commitments" in sql
    assert "CREATE TABLE public.personal_planner_mutation_receipts" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app.current_tenant_id" in sql
    assert "ALTER TABLE public.automation_tasks" not in sql
