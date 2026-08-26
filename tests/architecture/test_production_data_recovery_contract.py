from __future__ import annotations

from pathlib import Path


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
    assert 'sha256sum "${BACKUP_FILE}"' in script
    assert 'sha256sum --check "${CHECKSUM_FILE}"' in script
    assert "DATABASE_URL is required" in script


def test_restore_is_explicitly_destructive_and_checksum_guarded() -> None:
    script = _read("scripts/deploy/database-restore.sh")

    assert "RESTORE_DATABASE_URL is required" in script
    assert "I_UNDERSTAND_THIS_IS_DESTRUCTIVE" in script
    assert 'sha256sum --check "${CHECKSUM_FILE}"' in script
    assert "--clean" in script
    assert "--exit-on-error" in script


def test_postgres_backup_does_not_claim_other_recovery_domains() -> None:
    readme = _read("supabase/README.md")

    assert "primary PostgreSQL store only" in readme
    assert "Redis, Milvus, Elasticsearch" in readme
