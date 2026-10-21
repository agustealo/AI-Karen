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
    assert "UNIQUE (id, tenant_id, owner_id)" in sql
    assert "FOREIGN KEY (commitment_id, tenant_id, owner_id)" in sql
    assert "REFERENCES public.personal_planner_commitments (id, tenant_id, owner_id)" in sql
    assert "app.current_tenant_id" in sql
    assert "ALTER TABLE public.automation_tasks" not in sql


def test_idempotent_create_retries_are_serialized_and_fingerprint_checked():
    source = REPO.read_text()
    sql = MIGRATION.read_text()
    assert "pg_advisory_xact_lock" in source
    assert 'existing["request_fingerprint"] != fingerprint' in source
    assert 'existing["correlation_id"]' in source
    assert "request_fingerprint varchar(64) NOT NULL" in sql
    assert "PRIMARY KEY (tenant_id, owner_id, idempotency_key)" in sql


def test_retry_snapshots_preserve_original_revision_and_result():
    source = REPO.read_text()
    sql = MIGRATION.read_text()
    assert "result_snapshot jsonb NOT NULL" in sql
    assert "return PersonalCommitment.model_validate(already[\"result_snapshot\"])" in source
    assert 'saved = PersonalCommitment.model_validate(existing["result_snapshot"])' in source
    assert 'CAST(:snapshot AS jsonb)' in source
    assert "pg_advisory_xact_lock" in source


def test_migration_has_one_atomic_transaction_and_complete_constraints():
    sql = MIGRATION.read_text()
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert "CHECK (request_fingerprint ~ '^[0-9a-f]{64}$')" in sql
    assert "commitment_id uuid NOT NULL" in sql
    assert sql.rstrip().endswith("COMMIT;")


def test_created_receipt_timestamp_is_identical_to_database_row():
    source = REPO.read_text()
    assert "revision, correlation_id, persisted_at)" in source
    assert ":correlation, :persisted_at)" in source
    assert '"persisted_at": now' in source
    assert 'persisted_at=existing["persisted_at"]' in source


def test_mutation_receipts_carry_atomic_operation_provenance():
    source = REPO.read_text()
    sql = MIGRATION.read_text()
    assert "operation varchar(16) NOT NULL" in sql
    assert "operation IN ('create', 'update')" in sql
    assert "'create', :fingerprint" in source
    assert "'update', :fingerprint" in source
