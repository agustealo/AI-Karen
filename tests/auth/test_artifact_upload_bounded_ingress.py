"""Regression coverage for bounded legacy artifact upload admission."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes import artifacts as routes
from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig
from ai_karen_engine.services.database.repositories.base import RepositoryResult


class File:
    filename = "document.txt"
    content_type = "text/plain"

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.body[:size]


class Store:
    def __init__(self, result: RepositoryResult | None = None) -> None:
        self.requests = []
        self.result = result or RepositoryResult(success=False, error="private-key=secret")

    async def upload(self, request):
        self.requests.append(request)
        return self.result


@pytest.fixture
def scoped(monkeypatch):
    monkeypatch.setattr(routes, "coerce_tenant_id", str)
    monkeypatch.setattr(routes, "coerce_user_id", str)
    monkeypatch.setenv("KAREN_ARTIFACT_LEGACY_UPLOAD_MAX_BYTES", "4")
    return SimpleNamespace(tenant_id="tenant-a", user_id="owner-a")


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_before_storage(scoped, monkeypatch):
    store = Store()
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: store)
    file = File(b"12345" + b"X" * 1024)
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(file=file, current_user=scoped)
    assert exc.value.status_code == 413
    assert file.read_sizes == [5]
    assert store.requests == []


@pytest.mark.asyncio
async def test_repository_error_does_not_escape_to_client(scoped, monkeypatch):
    store = Store()
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: store)
    file = File(b"1234")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(file=file, current_user=scoped)
    assert exc.value.status_code == 503
    assert "secret" not in str(exc.value.detail)
    assert file.read_sizes == [5]
    assert len(store.requests) == 1
    assert store.requests[0].data == b"1234"


@pytest.mark.asyncio
async def test_invalid_upload_config_fails_closed(scoped, monkeypatch):
    monkeypatch.setenv("KAREN_ARTIFACT_LEGACY_UPLOAD_MAX_BYTES", "not-an-int")
    file = File(b"123")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(file=file, current_user=scoped)
    assert exc.value.status_code == 503
    assert file.read_sizes == []


@pytest.mark.parametrize("value", [0, -1, True, 1024 * 1024 * 1024 + 1])
def test_invalid_legacy_limits_rejected(value):
    with pytest.raises(ValueError):
        ArtifactStorageConfig(max_legacy_upload_bytes=value)


def test_default_legacy_limit_is_bounded(monkeypatch):
    monkeypatch.delenv("KAREN_ARTIFACT_LEGACY_UPLOAD_MAX_BYTES", raising=False)
    assert ArtifactStorageConfig.from_environment().max_legacy_upload_bytes == 16 * 1024 * 1024
