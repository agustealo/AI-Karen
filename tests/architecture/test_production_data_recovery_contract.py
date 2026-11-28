from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_supabase_migrations_are_documented_as_schema_authority() -> None:
    readme = _read("supabase/README.md")

    assert "supabase/migrations/" in readme
    assert "canonical schema migration authority" in readme
    assert "Application startup must not silently mutate production schema" in readme


def test_production_migration_requires_verified_backup_first() -> None:
    script = _read("scripts/deploy/migrate-production-database.sh")

    backup_call = 'bash "${SCRIPT_DIR}/database-backup.sh"'
    migration_call = 'supabase db push --db-url "${DATABASE_URL}" --include-all'

    assert backup_call in script
    assert 'sha256sum --check "${BACKUP_FILE}.sha256"' in script
    assert migration_call in script
    assert script.index(backup_call) < script.index(migration_call)


def test_backup_produces_checksum_and_uses_custom_format() -> None:
    script = _read("scripts/deploy/database-backup.sh")

    assert "--format=custom" in script
    assert ' > "${BACKUP_FILE}"' in script
    assert 'sha256sum "${BACKUP_FILE}"' in script
    assert 'sha256sum --check "${CHECKSUM_FILE}"' in script
    assert "DATABASE_URL is required" in script


def test_backup_metadata_binds_dump_to_release_and_schema_revision() -> None:
    script = _read("scripts/deploy/database-backup.sh")

    assert "KAREN_RELEASE_REVISION" in script
    assert "GITHUB_SHA" in script
    assert 'git -C "${REPO_ROOT}" rev-parse HEAD' in script
    assert "supabase/migrations" in script
    assert "migration_revision=" in script
    assert "release_revision=${release_revision}" in script
    assert "migration_revision=${migration_revision}" in script


def test_restore_is_explicitly_destructive_and_checksum_guarded() -> None:
    script = _read("scripts/deploy/database-restore.sh")

    assert "RESTORE_DATABASE_URL is required" in script
    assert "I_UNDERSTAND_THIS_IS_DESTRUCTIVE" in script
    assert 'sha256sum < "${BACKUP_FILE}"' in script
    assert "selected backup checksum mismatch" in script
    assert "restore target contains existing relations" in script
    assert script.index("restore target contains existing relations") < script.index("\npg_restore ")
    assert "--clean" not in script
    assert "--if-exists" not in script
    assert "--single-transaction" in script
    assert ' < "${BACKUP_FILE}"' in script
    assert "--exit-on-error" in script
    assert "recovery admission is not verified" in script


def test_postgres_backup_does_not_claim_other_recovery_domains() -> None:
    readme = _read("supabase/README.md")

    assert "primary PostgreSQL store only" in readme
    assert "Redis, Milvus, Elasticsearch" in readme


def test_recovery_commands_share_server_major_selection() -> None:
    for path, tool in (
        ("scripts/deploy/database-backup.sh", "pg_dump"),
        ("scripts/deploy/database-restore.sh", "pg_restore"),
    ):
        script = _read(path)
        assert 'source "${SCRIPT_DIR}/postgres-recovery-client.sh"' in script
        assert "select_postgres_recovery_client" in script
        assert "/usr/lib/postgresql/17/bin" not in script
        assert script.index("select_postgres_recovery_client") < script.index(f"\n{tool} ")


@pytest.mark.parametrize(("tool", "major", "expected"), [
    ("pg_dump", 16, 0), ("pg_restore", 16, 0),
    ("pg_dump", 17, 1), ("pg_restore", 17, 1),
])
def test_recovery_client_rejects_cross_major_binary(tmp_path, tool, major, expected):
    psql = tmp_path / "psql"
    psql.write_text(
        '#!/bin/bash\n'
        'if [[ "$1" == "--version" ]]; then echo "psql (PostgreSQL) 16.9"; '
        'else echo 160009; fi\n',
        encoding="utf-8",
    )
    binary = tmp_path / tool
    binary.write_text(
        f'#!/bin/bash\necho "{tool} (PostgreSQL) {major}.9"\n',
        encoding="utf-8",
    )
    for executable in (psql, binary):
        executable.chmod(0o700)
    helper = REPO_ROOT / "scripts/deploy/postgres-recovery-client.sh"
    result = subprocess.run(
        ["bash", "-eu", "-c", 'source "$1"; select_postgres_recovery_client example "$2"',
         "bash", str(helper), tool],
        env={**os.environ, "KAREN_POSTGRES_BIN_DIR": str(tmp_path)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == expected, result.stderr
    if expected:
        assert "does not match PostgreSQL server major 16" in result.stderr


def test_recovery_cutoff_requires_explicit_source_fence_before_database_access():
    script = REPO_ROOT / "scripts/deploy/database-recovery-cutoff.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "CONFIRM_SOURCE_FENCED": "", "DATABASE_URL": ""},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 2
    assert "I_HAVE_FENCED_SOURCE_WRITERS" in result.stderr
    assert result.stdout == ""


def test_recovery_cutoff_is_physical_evidence_not_admission():
    script = _read("scripts/deploy/database-recovery-cutoff.sh")
    assert "select_postgres_recovery_client" in script
    assert "pg_current_wal_insert_lsn()" in script
    assert "pg_current_wal_flush_lsn()" in script
    assert "flushed_lsn >= required_lsn" in script
    assert "NOT pg_is_in_recovery()" in script
    assert "pg_control_system()" in script
    assert "database_oid" in script
    assert "timeline_hex" in script
    assert "postgres_physical_wal_cutoff" in script
    assert "recovery hold remains" in script
