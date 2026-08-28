from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260828100000_12_medusa_execution_ledger.sql"
RUN_MANAGER = ROOT / "src/ai_karen_engine/agent_medusa/execution/run_manager.py"
LEDGER = ROOT / "src/ai_karen_engine/agent_medusa/execution/run_ledger.py"
DATABASE_README = ROOT / "src/ai_karen_engine/database/README.md"


def test_medusa_ledger_uses_canonical_schema_authority_and_rls() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE medusa_execution_runs" in sql
    assert "CREATE TABLE medusa_execution_events" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.current_tenant_id')::uuid" in sql
    assert "cancellation_requested" in sql
    assert "orphaned" in sql

    database_contract = DATABASE_README.read_text(encoding="utf-8")
    assert "`supabase/migrations/` is the only primary PostgreSQL schema-evolution authority" in database_contract


def test_runtime_does_not_create_or_mutate_postgres_schema() -> None:
    runtime_text = "\n".join(
        [
            RUN_MANAGER.read_text(encoding="utf-8"),
            LEDGER.read_text(encoding="utf-8"),
        ]
    ).lower()
    forbidden = (
        "metadata.create_all",
        "metadata.drop_all",
        "create table medusa_execution",
        "alter table medusa_execution",
        "drop table medusa_execution",
    )
    for marker in forbidden:
        assert marker not in runtime_text


def test_authority_split_is_explicit_in_runtime_modules() -> None:
    run_manager = RUN_MANAGER.read_text(encoding="utf-8")
    ledger = LEDGER.read_text(encoding="utf-8")
    assert "Redis owns transient cluster coordination" in run_manager
    assert "PostgreSQL owns durable execution" in run_manager
    assert "async_transaction_scope" in ledger
    assert "Redis" in ledger
    assert "transient" in ledger
