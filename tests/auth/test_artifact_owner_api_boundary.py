"""Owner-only artifact API boundary before governed organizational sharing."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes import artifacts as routes
from ai_karen_engine.services.database.repositories.artifact_store import Artifact
from ai_karen_engine.services.database.repositories.base import RepositoryResult


OWNER = SimpleNamespace(tenant_id="tenant-a", user_id="alice")
PEER = SimpleNamespace(tenant_id="tenant-a", user_id="bob")
FOREIGN = SimpleNamespace(tenant_id="tenant-b", user_id="alice")


class Store:
    def __init__(self) -> None:
        self.item = Artifact(
            id="file-1",
            tenant_id="tenant-a",
            user_id="alice",
            filename="contract.txt",
            created_at=datetime.now(timezone.utc),
        )
        self.actions: list[str] = []
        self.available = True

    async def get_metadata(self, artifact_id, tenant_id):
        self.actions.append("metadata")
        if not self.available:
            return RepositoryResult(success=False, error="private database error")
        if artifact_id == self.item.id and tenant_id == self.item.tenant_id:
            return RepositoryResult(success=True, data=self.item)
        return RepositoryResult(success=True, data=None)

    async def list_artifacts(self, tenant_id, conversation_id=None, message_id=None):
        self.actions.append("list")
        return RepositoryResult(success=True, data=[
            self.item,
            replace(self.item, id="file-2", user_id="bob"),
            replace(self.item, id="file-3", tenant_id="tenant-b"),
        ])

    async def list_archived(self, tenant_id, conversation_id=None, message_id=None):
        self.actions.append("list_archived")
        return RepositoryResult(success=True, data=[
            replace(self.item, deleted_at=datetime.now(timezone.utc)),
            replace(self.item, id="file-2", user_id="bob"),
        ])

    async def delete(self, *args):
        self.actions.append("delete")
        return RepositoryResult(success=True, data=True)

    async def archive(self, *args):
        self.actions.append("archive")
        return RepositoryResult(success=True, data=True)

    async def restore(self, *args):
        self.actions.append("restore")
        return RepositoryResult(success=True, data=True)

    async def purge(self, *args):
        self.actions.append("purge")
        return RepositoryResult(success=True, data=True)


@pytest.fixture
def store(monkeypatch):
    result = Store()
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: result)
    monkeypatch.setattr(routes, "coerce_tenant_id", str)
    monkeypatch.setattr(routes, "coerce_user_id", str)
    return result


@pytest.mark.parametrize("user", [
    SimpleNamespace(tenant_id=None, user_id="alice"),
    SimpleNamespace(tenant_id="tenant-a", user_id=None),
    SimpleNamespace(tenant_id="default", user_id="alice"),
])
def test_scope_must_be_explicit(user, store):
    with pytest.raises(HTTPException) as exc:
        routes._artifact_principal(user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_read_metadata(store):
    result = await routes.get_artifact_metadata("file-1", current_user=OWNER)
    assert result.id == "file-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [PEER, FOREIGN])
async def test_peer_or_foreign_tenant_cannot_read_metadata(principal, store):
    with pytest.raises(HTTPException) as exc:
        await routes.get_artifact_metadata("file-1", current_user=principal)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,method", [
    (routes.delete_artifact, "delete"),
    (routes.archive_artifact, "archive"),
    (routes.restore_artifact, "restore"),
    (routes.purge_artifact, "purge"),
])
async def test_same_tenant_peer_cannot_mutate_artifact(handler, method, store):
    with pytest.raises(HTTPException) as exc:
        await handler("file-1", current_user=PEER)
    assert exc.value.status_code == 404
    assert method not in store.actions


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,method", [
    (routes.delete_artifact, "delete"),
    (routes.archive_artifact, "archive"),
    (routes.restore_artifact, "restore"),
    (routes.purge_artifact, "purge"),
])
async def test_owner_can_mutate_artifact(handler, method, store):
    await handler("file-1", current_user=OWNER)
    assert store.actions == ["metadata", method]


@pytest.mark.asyncio
async def test_active_list_filters_owners_and_tenants(store):
    results = await routes.list_artifacts(current_user=OWNER)
    assert [item.id for item in results] == ["file-1"]


@pytest.mark.asyncio
async def test_archived_list_filters_other_owners(store):
    results = await routes.list_archived_artifacts(current_user=OWNER)
    assert [item.id for item in results] == ["file-1"]


@pytest.mark.asyncio
async def test_metadata_outage_fails_closed_without_leaking_error(store):
    store.available = False
    with pytest.raises(HTTPException) as exc:
        await routes.delete_artifact("file-1", current_user=OWNER)
    assert exc.value.status_code == 503
    assert "private database error" not in str(exc.value.detail)
    assert "delete" not in store.actions



def test_archived_route_precedes_dynamic_artifact_id_route():
    """Starlette resolves the first matching route, not the most specific."""
    get_paths = [
        route.path
        for route in routes.router.routes
        if "GET" in getattr(route, "methods", set())
    ]
    assert get_paths.index("/artifacts/archived") < get_paths.index(
        "/artifacts/{artifact_id}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["match", "wrong", "invalid", "revoked", "legacy"])
async def test_revision_pinned_text_route_enforces_current_access(monkeypatch, case):
    from unittest.mock import AsyncMock
    from fastapi import Request, Response
    from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

    artifact_id = "11111111-1111-4111-8111-111111111111"
    revision = "a" * 64
    principal = SimpleNamespace(
        tenant_id="22222222-2222-4222-8222-222222222222",
        user_id="33333333-3333-4333-8333-333333333333",
    )
    monkeypatch.setattr(routes, "coerce_tenant_id", str)
    monkeypatch.setattr(routes, "coerce_user_id", str)
    rbac = SimpleNamespace(has_permission=lambda *args: True,
                           audit_access_attempt=lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "get_rbac_manager", lambda: rbac)
    revalidate = AsyncMock(side_effect=[None, PermissionError()] if case == "revoked" else None)
    monkeypatch.setattr(routes, "ChatExecutionContext",
                        lambda **kwargs: SimpleNamespace(**kwargs, revalidate_runtime_attachment_session=revalidate))
    value = VerifiedArtifactText(
        artifact_id=artifact_id, tenant_id=principal.tenant_id, user_id=principal.user_id,
        filename="example.txt", mime_type="text/plain",
        sha256="b" * 64 if case == "wrong" else revision, text="private test text",
    )
    read = AsyncMock(return_value=RepositoryResult(success=True, data=value))
    if case == "legacy":
        read.side_effect = TypeError("unsupported revision")
    monkeypatch.setattr(routes, "_get_artifact_store",
                        lambda: SimpleNamespace(read_owner_active_text_bounded=read))
    request = Request({"type": "http", "path": "/artifacts/" + artifact_id + "/text",
                       "scheme": "http", "server": ("test", 80), "headers": []})
    response = Response()
    if case == "match":
        result = await routes.read_artifact_text(
            artifact_id, request, response, current_user=principal, revision=revision,
        )
        assert result["sha256"] == revision
        assert response.headers["Cache-Control"] == "private, no-store"
        assert revalidate.await_count == 2
    else:
        with pytest.raises(HTTPException) as exc:
            await routes.read_artifact_text(
                artifact_id, request, response, current_user=principal,
                revision="invalid" if case == "invalid" else revision,
            )
        assert exc.value.status_code == (403 if case == "revoked" else 404)
        assert "private test text" not in str(exc.value.detail)
    if case == "invalid":
        read.assert_not_awaited()
    else:
        read.assert_awaited_once_with(
            artifact_id, principal.tenant_id, principal.user_id,
            max_bytes=65536, expected_sha256=revision,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["match", "missing", "revoked", "wrong_revision", "invalid", "disabled"])
async def test_historical_attachment_route_requires_receipt_and_fresh_current_access(monkeypatch, case):
    from unittest.mock import AsyncMock
    from fastapi import Request, Response
    from ai_karen_engine.core.runtime.owned_history_projection import UnreplayableHistory
    from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

    artifact_id = "11111111-1111-4111-8111-111111111111"
    thread_id = "44444444-4444-4444-8444-444444444444"
    assistant_id = "55555555-5555-4555-8555-555555555555"
    revision = "a" * 64
    principal = SimpleNamespace(
        tenant_id="22222222-2222-4222-8222-222222222222",
        user_id="33333333-3333-4333-8333-333333333333",
    )
    monkeypatch.setattr(routes, "coerce_tenant_id", str)
    monkeypatch.setattr(routes, "coerce_user_id", str)
    monkeypatch.setattr(routes, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(enable_ag_ui_bridge=case != "disabled", enable_ag_ui_durable_runs=True),
    ))
    monkeypatch.setattr(routes, "get_rbac_manager", lambda: SimpleNamespace(
        has_permission=lambda *args: True, audit_access_attempt=lambda *args, **kwargs: None,
    ))
    revalidate = AsyncMock(side_effect=[None, None, PermissionError()] if case == "revoked" else None)
    monkeypatch.setattr(routes, "ChatExecutionContext", lambda **kwargs: SimpleNamespace(
        **kwargs, revalidate_runtime_attachment_session=revalidate,
    ))
    resolve = AsyncMock(return_value={"source_id": artifact_id, "revision": revision})
    if case == "missing":
        resolve.side_effect = UnreplayableHistory("unsupported_rich_history")
    monkeypatch.setattr(routes, "read_owned_historical_attachment_reference", resolve)
    value = VerifiedArtifactText(
        artifact_id=artifact_id, tenant_id=principal.tenant_id, user_id=principal.user_id,
        filename="example.txt", mime_type="text/plain",
        sha256="b" * 64 if case == "wrong_revision" else revision, text="private text",
    )
    read = AsyncMock(return_value=RepositoryResult(success=True, data=value))
    monkeypatch.setattr(routes, "_get_artifact_store", lambda: SimpleNamespace(
        read_owner_active_text_bounded=read,
    ))
    request = Request({"type": "http", "path": "/artifacts/history/test",
                       "scheme": "http", "server": ("test", 80), "headers": []})
    response = Response()
    if case == "match":
        result = await routes.read_historical_attachment_text(
            thread_id, assistant_id, 1, request, response, current_user=principal,
        )
        assert result == {"filename": "example.txt", "mime_type": "text/plain",
                          "size_bytes": 12, "text": "private text"}
        assert response.headers["Cache-Control"] == "private, no-store"
    else:
        with pytest.raises(HTTPException) as exc:
            await routes.read_historical_attachment_text(
                thread_id, assistant_id, 0 if case == "invalid" else 1,
                request, response, current_user=principal,
            )
        assert exc.value.status_code == (403 if case == "revoked" else 404)
        assert "private text" not in str(exc.value.detail)
    if case in {"invalid", "disabled"}:
        resolve.assert_not_awaited()
    else:
        resolve.assert_awaited_once()
        context = resolve.await_args.args[0]
        assert context.conversation_id == thread_id
        assert context.authenticated_user is principal
        assert resolve.await_args.kwargs == {"assistant_message_id": assistant_id, "ordinal": 1}
    if case in {"invalid", "disabled", "missing"}:
        read.assert_not_awaited()
    else:
        read.assert_awaited_once_with(
            artifact_id, principal.tenant_id, principal.user_id,
            max_bytes=65536, expected_sha256=revision,
        )
