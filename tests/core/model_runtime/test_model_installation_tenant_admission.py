"""SQL-before-pagination model eligibility and fail-closed legacy ownership."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    ModelOrchestratorError,
)
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)
from ai_karen_engine.persistence.repositories import (
    model_download_repository as repository_module,
)
from ai_karen_engine.persistence.repositories.model_download_repository import (
    ModelDownloadRepository,
)


TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
MODEL = "kyutai/pocket-tts"
REVISION = "db04f0e653473e5c7333c69686ac92b7460b0c1d"
CHANNEL = "plugin_audio"


@pytest.mark.asyncio
async def test_database_filters_exact_owned_licensed_installs_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, object]]] = []
    approved = {
        "job_id": "approved-test-job",
        "tenant_id": TENANT, "model_id": MODEL, "revision": REVISION,
        "channel_id": CHANNEL, "status": "completed",
        "license_accepted": True, "trust_remote_code": False,
        "install_path": "/verified/install",
    }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [approved]

    class FakeSession:
        async def execute(self, statement, parameters):
            captured.append((str(statement), dict(parameters)))
            return FakeResult()

    @asynccontextmanager
    async def transaction_scope():
        yield FakeSession()

    monkeypatch.setattr(repository_module, "async_transaction_scope", transaction_scope)
    rows = await ModelDownloadRepository().list_completed_model_installations(
        tenant_id=TENANT, model_id=MODEL, revision=REVISION,
        channel_id=CHANNEL,
    )

    assert rows == [approved]
    assert len(captured) == 1
    sql, params = captured[0]
    assert params == {
        "tenant_id": TENANT, "model_id": MODEL,
        "revision": REVISION, "channel_id": CHANNEL, "limit": 128,
    }
    for predicate in (
        "tenant_id = :tenant_id",
        "model_id = :model_id",
        "revision = :revision",
        "channel_id = :channel_id",
        "status = 'completed'",
        "license_accepted IS TRUE",
        "trust_remote_code IS NOT TRUE",
    ):
        assert predicate in sql
    assert sql.index("WHERE tenant_id") < sql.index("ORDER BY created_at DESC LIMIT")
    assert "tenant_id IS NULL" not in sql
    assert "tenant_id = ''" not in sql
    assert "SELECT *" not in sql


@pytest.mark.asyncio
async def test_model_authority_refuses_unverified_tenant_and_preserves_exact_query(
    tmp_path: Path,
) -> None:
    approved = {
        "job_id": "model-job", "tenant_id": TENANT,
        "model_id": MODEL, "revision": REVISION, "channel_id": CHANNEL,
        "status": "completed", "license_accepted": True,
        "trust_remote_code": False, "install_path": "/approved",
    }
    repository = SimpleNamespace(
        list_completed_model_installations=AsyncMock(return_value=[approved])
    )
    service = ModelDownloadControlService(
        {"models_root": str(tmp_path / "models")},
        repository=repository,
    )
    service.initialize = AsyncMock()

    for invalid in ("", "default", "not-uuid", OTHER + "/bad"):
        with pytest.raises(ModelOrchestratorError, match="tenant"):
            await service.list_completed_model_installations(
                tenant_id=invalid, model_id=MODEL,
                revision=REVISION, channel_id=CHANNEL,
            )
    repository.list_completed_model_installations.assert_not_awaited()

    result = await service.list_completed_model_installations(
        tenant_id=TENANT, model_id=MODEL,
        revision=REVISION, channel_id=CHANNEL,
    )
    assert result == [approved]
    repository.list_completed_model_installations.assert_awaited_once_with(
        tenant_id=TENANT, model_id=MODEL,
        revision=REVISION, channel_id=CHANNEL, limit=128,
    )


def test_installation_lookup_index_preserves_migration_42_legacy_denial() -> None:
    root = Path(__file__).resolve().parents[3]
    old = (root / "supabase/migrations/20261025010000_42_model_download_tenant_ownership.sql").read_text()
    new = (root / "supabase/migrations/20261116020000_55_model_installation_tenant_lookup.sql").read_text()
    assert "null legacy rows remain admin-only" in old
    assert "tenant_id IS NOT NULL" in new
    assert "license_accepted IS TRUE" in new
    assert "trust_remote_code IS NOT TRUE" in new
    assert "status = 'completed'" in new
