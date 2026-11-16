"""KCM governance reads must be scoped, non-promoting, and fail closed."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from ai_karen_engine.learning.kcm_governance import (
    KcmGovernanceUnavailable,
    PostgresKcmGovernanceReader,
)


TENANT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
SOURCE = "33333333-3333-4333-8333-333333333333"
DATASET = "44444444-4444-4444-8444-444444444444"
REVISION = "a" * 64


class Result:
    def __init__(
        self,
        scalar: Any = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self.scalar

    def mappings(self) -> Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class Session:
    def __init__(self, results: list[Result]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any]) -> Result:
        self.calls.append((str(stmt), params))
        return self.results[len(self.calls) - 1]


def reader(
    results: list[Result],
) -> tuple[PostgresKcmGovernanceReader, Session, list[dict[str, str]]]:
    session = Session(results)
    scopes: list[dict[str, str]] = []

    @asynccontextmanager
    async def transaction(**scope: str):
        scopes.append(scope)
        yield session

    return (
        PostgresKcmGovernanceReader(transaction_factory=transaction),
        session,
        scopes,
    )


@pytest.mark.asyncio
async def test_epoch_uses_owner_scope_and_database_value() -> None:
    service, session, scopes = reader([Result(scalar=17)])
    assert await service.current_epoch(tenant_id=TENANT, user_id=USER) == 17
    assert scopes == [{"tenant_id": TENANT, "user_id": USER}]
    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "public.kcm_training_scope_state" in sql
    assert "user_id = CAST(:user_id AS uuid)" in sql
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "training_authorized = FALSE" in sql
    assert params == {"tenant_id": TENANT, "user_id": USER}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, True, -1, 1.3, "1"])
async def test_unprovisioned_or_untrusted_epoch_never_becomes_zero(value: Any) -> None:
    service, _, _ = reader([Result(scalar=value)])
    assert await service.current_epoch(tenant_id=TENANT, user_id=USER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tenant,user",
    [
        ("", USER),
        ("tenant-a", USER),
        (TENANT, "anonymous"),
        (str(uuid.UUID(int=0)), USER),
        (TENANT, str(uuid.UUID(int=0))),
    ],
)
async def test_invalid_principal_denied_before_database(
    tenant: str, user: str,
) -> None:
    service, session, scopes = reader([])
    assert await service.current_epoch(tenant_id=tenant, user_id=user) is None
    assert session.calls == []
    assert scopes == []


@pytest.mark.asyncio
async def test_quarantined_lineage_looks_up_exact_source_and_revision() -> None:
    service, session, scopes = reader([
        Result(scalar=1),
        Result(rows=[{
            "dataset_id": uuid.UUID(DATASET),
            "dataset_version": 2,
            "manifest_sha256": "b" * 64,
            "lineage_status": "quarantined",
        }]),
    ])
    items = await service.affected_datasets(
        tenant_id=TENANT, user_id=USER,
        source_event_id=SOURCE, source_revision=REVISION,
    )
    assert len(items) == 1
    assert items[0].dataset_id == DATASET
    assert items[0].dataset_version == 2
    assert items[0].manifest_sha256 == "b" * 64
    assert items[0].lineage_status == "quarantined"
    assert scopes == [{"tenant_id": TENANT, "user_id": USER}]
    assert len(session.calls) == 2
    sql, params = session.calls[-1]
    assert "FROM public.kcm_dataset_source_lineage" in sql
    assert "user_id = CAST(:user_id AS uuid)" in sql
    assert "source_event_id = CAST(:source_event_id AS uuid)" in sql
    assert params["source_revision"] == REVISION
    assert params["limit"] == 100


@pytest.mark.asyncio
async def test_revoked_source_visible_as_revoked_not_safe() -> None:
    service, _, _ = reader([
        Result(scalar=1),
        Result(rows=[{
            "dataset_id": DATASET, "dataset_version": 1,
            "manifest_sha256": "c" * 64, "lineage_status": "revoked",
        }]),
    ])
    result = await service.affected_datasets(
        tenant_id=TENANT, user_id=USER,
        source_event_id=SOURCE, source_revision=REVISION,
    )
    assert result[0].lineage_status == "revoked"


@pytest.mark.asyncio
async def test_missing_governance_row_is_not_a_clean_lineage_report() -> None:
    service, session, _ = reader([Result(scalar=None)])
    with pytest.raises(KcmGovernanceUnavailable, match="scope_not_provisioned"):
        await service.affected_datasets(
            tenant_id=TENANT, user_id=USER,
            source_event_id=SOURCE, source_revision=REVISION,
        )
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_invalid_lineage_status_fails_closed() -> None:
    service, _, _ = reader([
        Result(scalar=1),
        Result(rows=[{
            "dataset_id": DATASET, "dataset_version": 1,
            "manifest_sha256": "c" * 64, "lineage_status": "approved",
        }]),
    ])
    with pytest.raises(KcmGovernanceUnavailable, match="lineage_status_invalid"):
        await service.affected_datasets(
            tenant_id=TENANT, user_id=USER,
            source_event_id=SOURCE, source_revision=REVISION,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["z" * 64, "a" * 63, "", "A" * 64])
async def test_revision_must_match_canonical_source_hash(bad: str) -> None:
    service, session, scopes = reader([])
    with pytest.raises(KcmGovernanceUnavailable, match="source_revision_invalid"):
        await service.affected_datasets(
            tenant_id=TENANT, user_id=USER,
            source_event_id=SOURCE, source_revision=bad,
        )
    assert session.calls == [] and scopes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [-1, 0, 501, True, None, 1.5])
async def test_lineage_read_budget_is_bounded(limit: Any) -> None:
    service, session, _ = reader([])
    with pytest.raises(KcmGovernanceUnavailable, match="lineage_limit_invalid"):
        await service.affected_datasets(
            tenant_id=TENANT, user_id=USER,
            source_event_id=SOURCE, source_revision=REVISION,
            limit=limit,
        )
    assert session.calls == []


def test_migration_has_owner_rls_and_cannot_authorize_training() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "supabase" / "migrations"
        / "20261116190000_58_kcm_training_lineage_revocation.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    for name in (
        "kcm_training_scope_state",
        "kcm_dataset_source_lineage",
        "kcm_training_source_revocations",
    ):
        assert f"CREATE TABLE public.{name}" in sql
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 3
    assert sql.count("FORCE ROW LEVEL SECURITY") == 3
    assert sql.count("training_authorized = false") >= 2
    assert "app.current_tenant_id" in sql
    assert "app.current_user_id" in sql
    assert "REVOKE ALL ON FUNCTION" in sql
    assert "ON DELETE CASCADE" in sql
    assert "FOR UPDATE" in sql
    assert "lineage_status = 'revoked'" in sql
    assert "COMMIT;" in sql
