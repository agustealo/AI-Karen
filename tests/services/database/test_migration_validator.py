"""Read-only migration validation must not certify unexpected database histories."""

from pathlib import Path

import pytest

from ai_karen_engine.services.database import migration_validator as module


@pytest.fixture
def validator():
    # Avoid constructing database clients. Every test exercises the canonical
    # read-only validator contract against deterministic history observations.
    return object.__new__(module.MigrationValidator)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observed", "status", "pending_count", "error_count"),
    [
        (["20261025020000", "20261025030000"], module.MigrationStatus.UP_TO_DATE, 0, 0),
        (["20261025020000"], module.MigrationStatus.PENDING, 1, 0),
        (["20261025020000", "20261025030000", "20990101000000"], module.MigrationStatus.FAILED, 0, 1),
        (["20261025020000", "20261025020000"], module.MigrationStatus.FAILED, 1, 1),
    ],
)
async def test_migration_history_fails_closed(
    validator, monkeypatch, observed, status, pending_count, error_count
):
    monkeypatch.setattr(
        module,
        "_available_migrations",
        lambda: [
            Path("20261025020000_43_runtime_chat_run_ledger.sql"),
            Path("20261025030000_44_runtime_chat_replay_identity.sql"),
        ],
    )

    async def fake_applied():
        return observed

    monkeypatch.setattr(validator, "_applied_versions", fake_applied)
    report = await validator.validate_migrations()
    assert report.overall_status is status
    assert len(report.pending_versions) == pending_count
    assert len(report.errors) == error_count


@pytest.mark.asyncio
async def test_migration_history_failures_do_not_echo_database_credentials(
    validator, monkeypatch
):
    monkeypatch.setattr(
        module,
        "_available_migrations",
        lambda: [Path("20261025020000_43_runtime_chat_run_ledger.sql")],
    )

    async def fake_applied():
        raise RuntimeError("postgresql://secret-user:password@private-database/schema")

    monkeypatch.setattr(validator, "_applied_versions", fake_applied)
    report = await validator.validate_migrations()
    assert report.overall_status is module.MigrationStatus.UNKNOWN
    assert report.errors == ["Supabase migration history unavailable"]
    assert "password" not in repr(report)
