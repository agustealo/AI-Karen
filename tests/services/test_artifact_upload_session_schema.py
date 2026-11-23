"""KFILE-UPLOAD-01C durable upload ledger schema guardrails.

These static checks supplement, but do not replace, a PostgreSQL migration
and RLS acceptance run against the real production role topology.
"""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase/migrations/20261123010000_67_artifact_upload_sessions.sql"
)


def test_upload_ledger_is_private_and_owner_scoped():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "tenant_id uuid not null" in sql
    assert "owner_user_id uuid not null" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on public.artifact_upload_sessions from public" in sql
    assert "unique (tenant_id, owner_user_id, idempotency_key_hash)" in sql
    assert "create policy" not in sql


def test_upload_ledger_tracks_recovery_without_false_success():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for state in (
        "created", "receiving", "staged", "committing",
        "committed", "failed", "cancelled", "reconcile_required",
    ):
        assert f"'{state}'" in sql
    assert "artifact_id text references public.files(file_id)" in sql
    assert "check ((state <> 'committed') or artifact_id is not null)" in sql
    assert "lease_expires_at timestamp" in sql
    assert "manifest_sha256 text not null" in sql
    assert "received_bytes <= expected_bytes" in sql
