from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
EXPECTED_BASELINE = [
    "20260827005000_00_required_extensions.sql",
    "20260827010000_01_core_persona_runtime.sql",
    "20260827020000_02_auth_profile_finalization.sql",
    "20260827030000_03_memory.sql",
    "20260827040000_04_tenant_security.sql",
    "20260827050000_05_schema_security_finalization.sql",
    "20260827060000_06_auth_refresh_history.sql",
    "20260827070000_07_identity_vault.sql",
]
MIGRATION_NAME = re.compile(r"^(?P<timestamp>\d{14})_(?P<domain>[a-z0-9_]+)\.sql$")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_canonical_baseline_is_immutable_prefix_with_ordered_forward_migrations() -> None:
    names = [path.name for path in sorted(MIGRATIONS.glob("*.sql"))]

    assert names[: len(EXPECTED_BASELINE)] == EXPECTED_BASELINE
    assert len(names) == len(set(names))

    timestamps: list[str] = []
    for name in names:
        match = MIGRATION_NAME.fullmatch(name)
        assert match is not None, f"Invalid canonical migration name: {name}"
        timestamps.append(match.group("timestamp"))

    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))

    baseline_cutover = MIGRATION_NAME.fullmatch(EXPECTED_BASELINE[-1])
    assert baseline_cutover is not None
    for name in names[len(EXPECTED_BASELINE) :]:
        forward = MIGRATION_NAME.fullmatch(name)
        assert forward is not None
        assert forward.group("timestamp") > baseline_cutover.group("timestamp")


def test_fresh_install_declares_pgvector_before_vector_columns() -> None:
    extensions = _read("supabase/migrations/20260827005000_00_required_extensions.sql")
    core = _read("supabase/migrations/20260827010000_01_core_persona_runtime.sql")

    assert "CREATE EXTENSION IF NOT EXISTS vector;" in extensions
    assert "VECTOR(" in core
    assert EXPECTED_BASELINE.index(
        "20260827005000_00_required_extensions.sql"
    ) < EXPECTED_BASELINE.index("20260827010000_01_core_persona_runtime.sql")


def test_competing_primary_postgres_migration_authorities_are_absent() -> None:
    forbidden = [
        "src/ai_karen_engine/database/migration_manager.py",
        "src/ai_karen_engine/database/migrations",
        "src/ai_karen_engine/database/migration",
        "docker/database/migrations/postgres",
        "docker/database/scripts/migration-manager.py",
        "server/chat/migrations",
        "server/migrations",
    ]
    for relative in forbidden:
        assert not (ROOT / relative).exists(), relative


def test_runtime_database_code_cannot_create_or_drop_primary_schema() -> None:
    roots = [
        ROOT / "src/ai_karen_engine/database",
        ROOT / "src/ai_karen_engine/services/auth",
        ROOT / "src/ai_karen_engine/services/identity_vault",
        ROOT / "src/ai_karen_engine/extensions/platform/core/integration",
    ]
    for source_root in roots:
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "metadata.create_all" not in text, path
            assert "metadata.drop_all" not in text, path


def test_extension_models_do_not_export_schema_mutation_helpers() -> None:
    models = _read("src/ai_karen_engine/extensions/platform/core/integration/models.py")
    assert "def create_extension_tables" not in models
    assert "def drop_extension_tables" not in models
    assert '"create_extension_tables"' not in models
    assert '"drop_extension_tables"' not in models


def test_auth_and_identity_vault_preflight_are_read_only() -> None:
    auth = _read("src/ai_karen_engine/services/auth/auth_service.py")
    vault = _read(
        "src/ai_karen_engine/services/identity_vault/credential_vault_service.py"
    )
    for text in (auth, vault):
        assert "information_schema.tables" in text
        assert "create_tables_async()" not in text


def test_application_factory_does_not_run_migrations() -> None:
    factory = _read("src/ai_karen_engine/database/factory.py")
    assert "MigrationManager" not in factory
    assert "create_migration_manager" not in factory
    assert "run_migrations" not in factory


def test_migration_status_is_read_only_supabase_history() -> None:
    validator = _read("src/ai_karen_engine/services/database/migration_validator.py")
    assert "supabase_migrations.schema_migrations" in validator
    assert "Path.cwd()" not in validator
    assert "CREATE TABLE" not in validator.upper()
    assert "ALTER TABLE" not in validator.upper()
    assert "DROP TABLE" not in validator.upper()
    assert "run_migrations" not in validator


def test_deployment_uses_guarded_canonical_migration_command() -> None:
    deploy = _read("server/deployment/deploy_auth_system.py")
    operator = _read("scripts/deploy/migrate-production-database.sh")
    assert "migrate-production-database.sh" in deploy
    assert "get_migration_validator" in deploy
    assert "validation_status" in deploy
    assert "pending_count" in deploy
    assert "'migrations': await self._get_migration_status()" in deploy
    assert "database-backup.sh" in operator
    assert "supabase db push" in operator


def test_identity_vault_schema_is_migration_owned() -> None:
    migration = _read("supabase/migrations/20260827070000_07_identity_vault.sql")
    schema = _read("src/ai_karen_engine/database/identity_vault_schema.py")
    for table in (
        "identity_providers",
        "credentials",
        "credential_secrets",
        "external_accounts",
        "credential_bindings",
        "account_sessions",
        "auth_grants",
        "token_leases",
        "login_attempts",
        "credential_audit_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "def create_schema" not in schema
    assert "def validate_schema" in schema


def test_baseline_cutover_is_documented() -> None:
    baseline = _read("docs/database/BASELINE_2026_08.md")
    supabase_readme = _read("supabase/README.md")
    assert "only primary PostgreSQL schema-evolution authority" in baseline
    assert (
        "Every subsequent schema change is a new forward-only Supabase migration"
        in baseline
    )
    assert "Production Baseline 2026-08" in supabase_readme
