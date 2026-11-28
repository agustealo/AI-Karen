"""Regression coverage for bounded legacy artifact upload admission."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request

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
    principal = SimpleNamespace(tenant_id="tenant-a", user_id="owner-a")
    rbac = SimpleNamespace(has_permission=Mock(return_value=True), audit_access_attempt=Mock())
    revalidate = AsyncMock()
    monkeypatch.setattr(routes, "get_rbac_manager", lambda: rbac)
    monkeypatch.setattr(routes, "ChatExecutionContext", lambda **kwargs: SimpleNamespace(
        **kwargs, revalidate_runtime_artifact_write_session=revalidate,
    ))
    return SimpleNamespace(principal=principal, rbac=rbac, revalidate=revalidate)


def _request():
    return Request({
        "type": "http", "path": "/artifacts/upload",
        "scheme": "http", "server": ("test", 80), "headers": [],
    })


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_before_storage(scoped, monkeypatch):
    store = Store()
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: store)
    file = File(b"12345" + b"X" * 1024)
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal)
    assert exc.value.status_code == 413
    assert file.read_sizes == [5]
    assert store.requests == []


@pytest.mark.asyncio
async def test_repository_error_does_not_escape_to_client(scoped, monkeypatch):
    store = Store()
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: store)
    file = File(b"1234")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal)
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
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal)
    assert exc.value.status_code == 503
    assert file.read_sizes == []


@pytest.mark.parametrize("value", [0, -1, True, 1024 * 1024 * 1024 + 1])
def test_invalid_legacy_limits_rejected(value):
    with pytest.raises(ValueError):
        ArtifactStorageConfig(max_legacy_upload_bytes=value)


def test_default_legacy_limit_is_bounded(monkeypatch):
    monkeypatch.delenv("KAREN_ARTIFACT_LEGACY_UPLOAD_MAX_BYTES", raising=False)
    assert ArtifactStorageConfig.from_environment().max_legacy_upload_bytes == 16 * 1024 * 1024

@pytest.mark.asyncio
@pytest.mark.parametrize("denied", [routes.Permission.DATA_READ, routes.Permission.ARTIFACT_CREATE_OWN])
async def test_upload_denied_before_body_or_storage_without_owner_permissions(scoped, monkeypatch, denied):
    scoped.rbac.has_permission.side_effect = lambda principal, permission: permission != denied
    resolve = Mock(side_effect=AssertionError("storage must not resolve"))
    monkeypatch.setattr(routes, "_get_artifact_store", resolve)
    file = File(b"1234")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal)
    assert exc.value.status_code == 403
    assert file.read_sizes == []
    scoped.revalidate.assert_not_awaited()
    resolve.assert_not_called()
    args, kwargs = scoped.rbac.audit_access_attempt.call_args
    assert args == (scoped.principal, denied)
    assert kwargs["granted"] is False
    assert kwargs["additional_context"] == {"operation": "artifact_owner_upload"}


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [
    {"conversation_id": "foreign-conversation"},
    {"message_id": "foreign-message"},
    {"conversation_id": "", "message_id": ""},
])
async def test_legacy_upload_rejects_unpersisted_resource_bindings(scoped, monkeypatch, binding):
    resolve = Mock(side_effect=AssertionError("storage must not resolve"))
    monkeypatch.setattr(routes, "_get_artifact_store", resolve)
    file = File(b"1234")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal, **binding)
    assert exc.value.status_code == 422
    assert file.read_sizes == []
    resolve.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked_after_read", [False, True])
async def test_upload_revalidates_live_session_before_write(scoped, monkeypatch, revoked_after_read):
    scoped.revalidate.side_effect = [None, PermissionError()] if revoked_after_read else PermissionError()
    resolve = Mock(side_effect=AssertionError("storage must not resolve"))
    monkeypatch.setattr(routes, "_get_artifact_store", resolve)
    file = File(b"1234")
    with pytest.raises(HTTPException) as exc:
        await routes.upload_artifact(_request(), file=file, current_user=scoped.principal)
    assert exc.value.status_code == 403
    assert file.read_sizes == ([5] if revoked_after_read else [])
    assert scoped.revalidate.await_count == (2 if revoked_after_read else 1)
    resolve.assert_not_called()


@pytest.mark.asyncio
async def test_owner_upload_uses_canonical_scope_without_broad_data_write(scoped, monkeypatch):
    from hashlib import sha256
    from ai_karen_engine.services.database.repositories.artifact_store import Artifact

    scoped.rbac.has_permission.side_effect = lambda principal, permission: permission in {
        routes.Permission.DATA_READ, routes.Permission.ARTIFACT_CREATE_OWN,
    }
    item = Artifact(id="artifact", tenant_id="tenant-a", user_id="owner-a",
                    filename="document.txt", mime_type="text/plain",
                    size_bytes=4, sha256=sha256(b"1234").hexdigest())
    store = Store(RepositoryResult(success=True, data=item))
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: store)
    result = await routes.upload_artifact(_request(), file=File(b"1234"), current_user=scoped.principal)
    assert result.id == item.id
    assert result.sha256 == item.sha256
    assert scoped.revalidate.await_count == 2
    assert len(store.requests) == 1
    upload = store.requests[0]
    assert (upload.tenant_id, upload.user_id) == ("tenant-a", "owner-a")
    assert upload.conversation_id is None and upload.message_id is None
    assert upload.data == b"1234"


def test_upload_uses_witness_issuing_ingress_dependency():
    route = next(route for route in routes.router.routes if route.path == "/artifacts/upload")
    dependencies = [dependency.call for dependency in route.dependant.dependencies]
    assert routes.get_chat_execution_context in dependencies
    assert routes.get_current_user not in dependencies


@pytest.fixture
def raw_upload(scoped, monkeypatch):
    from uuid import uuid4
    from ai_karen_engine.core.runtime.owner_text_upload import OwnerTextUploadReceipt

    monkeypatch.setenv("KAREN_GOVERNED_TEXT_UPLOAD_INGRESS_ENABLED", "true")
    monkeypatch.setenv("KAREN_GOVERNED_TEXT_UPLOAD_MAX_BYTES", "4")
    key = str(uuid4())
    receipt = OwnerTextUploadReceipt(str(uuid4()), str(uuid4()), "document.txt", "a" * 64, 4)
    service = SimpleNamespace(transfer_owner_text=AsyncMock(return_value=receipt))
    monkeypatch.setattr(routes, "get_plugin_service", AsyncMock(return_value=service))
    headers = [
        (b"content-type", b"text/plain"), (b"x-upload-filename", b"document.txt"),
        (b"idempotency-key", key.encode()), (b"x-upload-destination", b"explorer"),
        (b"x-upload-recipe", b"store_only"),
    ]
    def request(chunks, extra_headers=()):
        receive = AsyncMock(side_effect=[
            {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
            for index, chunk in enumerate(chunks)
        ])
        req = Request({
            "type": "http", "path": "/artifacts/upload/text",
            "scheme": "http", "server": ("test", 80), "headers": headers + list(extra_headers),
            "query_string": b"",
        }, receive=receive)
        return req, receive
    return SimpleNamespace(request=request, service=service, scoped=scoped, key=key, receipt=receipt)


@pytest.mark.asyncio
async def test_raw_transfer_disabled_without_reading_body(raw_upload, monkeypatch):
    from fastapi import Response
    monkeypatch.setenv("KAREN_GOVERNED_TEXT_UPLOAD_INGRESS_ENABLED", "false")
    req, receive = raw_upload.request([b"1234"])
    with pytest.raises(HTTPException) as exc:
        await routes.transfer_owner_text(req, Response(), raw_upload.scoped.principal)
    assert exc.value.status_code == 404
    receive.assert_not_awaited()
    raw_upload.service.transfer_owner_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_transfer_counts_actual_chunks_before_runtime(raw_upload):
    from fastapi import Response
    req, receive = raw_upload.request([b"123", b"45", b"not-consumed"])
    with pytest.raises(HTTPException) as exc:
        await routes.transfer_owner_text(req, Response(), raw_upload.scoped.principal)
    assert exc.value.status_code == 413
    assert receive.await_count == 2
    raw_upload.service.transfer_owner_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_transfer_rejects_declared_oversize_before_read(raw_upload):
    from fastapi import Response
    req, receive = raw_upload.request([b"1234"], [(b"content-length", b"5")])
    with pytest.raises(HTTPException) as exc:
        await routes.transfer_owner_text(req, Response(), raw_upload.scoped.principal)
    assert exc.value.status_code == 413
    receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_transfer_revocation_after_body_denies_runtime(raw_upload):
    from fastapi import Response
    raw_upload.scoped.revalidate.side_effect = [None, PermissionError()]
    req, receive = raw_upload.request([b"1234"])
    with pytest.raises(HTTPException) as exc:
        await routes.transfer_owner_text(req, Response(), raw_upload.scoped.principal)
    assert exc.value.status_code == 403
    receive.assert_awaited_once()
    raw_upload.service.transfer_owner_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_transfer_returns_only_verified_receipt(raw_upload):
    from fastapi import Response
    req, receive = raw_upload.request([b"12", b"34"])
    response = Response()
    result = await routes.transfer_owner_text(req, response, raw_upload.scoped.principal)
    assert result.artifact_id == raw_upload.receipt.artifact_id
    assert response.headers["cache-control"] == "no-store"
    args, kwargs = raw_upload.service.transfer_owner_text.await_args
    assert args[0].authenticated_user is raw_upload.scoped.principal
    assert kwargs == dict(destination="explorer", recipe="store_only",
                          filename="document.txt", data=b"1234", idempotency_key=raw_upload.key)
    assert receive.await_count == 2


def test_raw_transfer_has_no_framework_body_parser():
    route = next(route for route in routes.router.routes if route.path == "/artifacts/upload/text")
    assert route.body_field is None
    assert routes.get_chat_execution_context in [d.call for d in route.dependant.dependencies]
