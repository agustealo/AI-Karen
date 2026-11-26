"""Authenticated HTTP contract for the canonical communications service."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.content import communications as route
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.persistence.repositories.communications_inbox_repository import (
    InboxConflict, InboxEntry, InboxFilter, InboxMutation, InboxNotFound,
    InboxOperation, InboxPage,
)
from ai_karen_engine.services import communications_inbox as service_module

pytestmark = pytest.mark.asyncio


async def test_communications_authenticated_http_contract(monkeypatch, caplog):
    tenant, owner, entry_id, conversation, execution = map(str, (uuid4() for _ in range(5)))
    now = datetime.now(timezone.utc)
    entry = InboxEntry(
        entry_id, conversation, execution, "terminal_chat_attention", "failed",
        now, None, None, None, 9007199254740993,
    )
    principal = UserData(user_id=owner, tenant_id=tenant, roles=["user"])
    assert get_rbac_manager().has_permission(principal, Permission.COMMUNICATIONS_READ)
    assert get_rbac_manager().has_permission(principal, Permission.COMMUNICATIONS_WRITE)
    audits = []
    producer = SimpleNamespace(enable_communications_terminal_producer=False)
    monkeypatch.setattr(service_module, "get_runtime_settings", lambda: SimpleNamespace(features=producer))
    monkeypatch.setattr(service_module.auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(service_module, "get_audit_logger", lambda: SimpleNamespace(
        log_audit_event=audits.append,
    ))

    class Repository:
        calls = []
        failure = None

        async def list_entries(self, **kwargs):
            self.calls.append(kwargs)
            if self.failure:
                raise self.failure
            return InboxPage((entry,), None, 1)

        async def reconcile_pending(self, **kwargs):
            self.calls.append(kwargs)
            return 2

        async def mutate(self, **kwargs):
            self.calls.append(kwargs)
            if self.failure:
                raise self.failure
            return InboxMutation(entry, False)

    repo = Repository()
    service = service_module.CommunicationsInboxService(repo)
    app = FastAPI()
    app.include_router(route.router, prefix="/communications")
    app.dependency_overrides[route.get_communications_inbox_service] = lambda: service

    def unauthorized():
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[route.get_current_user] = unauthorized
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoint = "/communications/inbox"
        mutation = endpoint + "/" + entry_id
        payload = {"operation": "acknowledge", "expected_revision": "9007199254740993"}
        assert (await client.get(endpoint)).status_code == 401
        assert (await client.patch(mutation, json=payload)).status_code == 401
        assert not repo.calls
        app.dependency_overrides[route.get_current_user] = lambda: principal
        response = await client.get(endpoint, params={"tenant_id": str(uuid4()), "user_id": str(uuid4())})
        assert response.status_code == 200
        assert response.json()["entries"][0]["revision"] == "9007199254740993"
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["capabilities"] == {"can_mutate": True, "producer_enabled": False, "can_reconcile": False}
        assert repo.calls[-1]["tenant_id"] == tenant
        assert repo.calls[-1]["user_id"] == owner
        assert repo.calls[-1]["inbox_filter"] == InboxFilter.ACTIVE
        assert (await client.get(endpoint, params={"cursor_id": entry_id})).status_code == 422
        assert (await client.get(endpoint, params={"limit": 101})).status_code == 422
        assert (await client.patch(mutation, json={**payload, "tenant_id": tenant})).status_code == 422
        assert (await client.patch(mutation, json={**payload, "expected_revision": 1})).status_code == 422
        assert (await client.patch(mutation, json={**payload, "operation": "restart"})).status_code == 422
        assert (await client.post(endpoint, json=payload)).status_code == 405
        assert (await client.post(endpoint + "/reconcile")).status_code == 503
        producer.enable_communications_terminal_producer = True
        active_response = await client.get(endpoint)
        assert active_response.status_code == 200
        assert active_response.json()["capabilities"] == {"can_mutate": True, "producer_enabled": True, "can_reconcile": True}
        recovery = await client.post(endpoint + "/reconcile", params={"tenant_id": str(uuid4())})
        assert recovery.status_code == 200 and recovery.json() == {"admitted_count": 2}
        assert repo.calls[-1] == {"tenant_id": tenant, "user_id": owner}
        response = await client.patch(mutation, json=payload)
        assert response.status_code == 200 and response.json()["changed"] is False
        assert repo.calls[-1]["operation"] == InboxOperation.ACKNOWLEDGE
        assert repo.calls[-1]["expected_revision"] == 9007199254740993
        assert repo.calls[-1]["entry_id"] == entry_id
        assert repo.calls[-1]["tenant_id"] == tenant
        for error, status in (
            (InboxNotFound("foreign-secret"), 404),
            (InboxConflict("revision-secret"), 409),
            (RuntimeError("sql-secret"), 503),
        ):
            repo.failure = error
            response = await client.patch(mutation, json=payload)
            assert response.status_code == status
            assert "secret" not in response.text
        repo.failure = RuntimeError("read-secret")
        response = await client.get(endpoint)
        assert response.status_code == 503 and "secret" not in response.text
        assert "sql-secret" not in caplog.text and "read-secret" not in caplog.text
        repo.failure = None
        before = len(repo.calls)
        for unprivileged in (
            UserData(user_id=owner, tenant_id=tenant, roles=["readonly"]),
            UserData(user_id=owner, tenant_id=tenant, roles=["user"], is_active=False),
            UserData(user_id=owner, tenant_id=tenant, roles=["user"], is_verified=False),
            UserData(user_id=owner, tenant_id="", roles=["user"]),
        ):
            app.dependency_overrides[route.get_current_user] = lambda: unprivileged
            assert (await client.get(endpoint)).status_code == 403
            assert (await client.patch(mutation, json=payload)).status_code == 403
            assert (await client.post(endpoint + "/reconcile")).status_code == 403
        read_only = UserData(user_id=owner, tenant_id=tenant, permissions=["communications:read"])
        app.dependency_overrides[route.get_current_user] = lambda: read_only
        read_only_response = await client.get(endpoint)
        assert read_only_response.status_code == 200
        assert read_only_response.json()["capabilities"] == {"can_mutate": False, "producer_enabled": True, "can_reconcile": False}
        before += 1
        assert (await client.patch(mutation, json=payload)).status_code == 403
        assert (await client.post(endpoint + "/reconcile")).status_code == 403
        assert len(repo.calls) == before
        app.dependency_overrides[route.get_current_user] = lambda: principal
        monkeypatch.setattr(service_module.auth_config, "should_bypass_auth", lambda: True)
        assert (await client.get(endpoint)).status_code == 403
        assert len(repo.calls) == before
        assert audits


async def test_communications_wait_rechecks_identity_and_permission(monkeypatch):
    from unittest.mock import AsyncMock
    from ai_karen_engine.auth.auth_middleware import AuthenticationError

    tenant, owner, foreign = map(str, (uuid4() for _ in range(3)))
    principal = UserData(user_id=owner, tenant_id=tenant, roles=["user"])
    settings = SimpleNamespace(features=SimpleNamespace(
        enable_communications_invalidation=True, enable_communications_invalidation_wait=True,
    ))
    monkeypatch.setattr(service_module, "get_runtime_settings", lambda: settings)
    monkeypatch.setattr(service_module.auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(service_module, "get_audit_logger", lambda: SimpleNamespace(log_audit_event=lambda event: None))
    wait = AsyncMock(return_value=True)
    monkeypatch.setattr(service_module, "wait_for_inbox_invalidation", wait)
    fresh = AsyncMock(return_value=principal)
    service = service_module.CommunicationsInboxService(object())
    app = FastAPI()
    app.include_router(route.router, prefix="/communications")
    # FastAPI captured the original dependency at route registration; replace
    # the module symbol only for the explicit fresh reauthentication call.
    app.dependency_overrides[route.get_current_user] = lambda: principal
    monkeypatch.setattr(route, "get_current_user", fresh)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoint = "/communications/inbox/wait"
        assert (await client.get(endpoint, params={"user_id": foreign})).status_code == 422
        wait.assert_not_awaited()
        response = await client.get(endpoint)
        assert response.status_code == 200
        assert response.json() == {"changed": True}
        assert response.headers["cache-control"] == "no-store"
        assert wait.call_args.kwargs["tenant_id"] == tenant
        assert wait.call_args.kwargs["user_id"] == owner
        fresh.assert_awaited_once()
        wait.return_value = False
        assert (await client.get(endpoint)).json() == {"changed": False}
        for user in (
            UserData(user_id=foreign, tenant_id=tenant, roles=["user"]),
            UserData(user_id=owner, tenant_id=tenant, roles=["readonly"]),
        ):
            fresh.return_value = user
            assert (await client.get(endpoint)).status_code == 403
        fresh.side_effect = AuthenticationError("private session detail", 401)
        response = await client.get(endpoint)
        assert response.status_code == 401 and "private" not in response.text
        assert response.headers["cache-control"] == "no-store"
        fresh.side_effect = None
        fresh.return_value = principal
        settings.features.enable_communications_invalidation_wait = False
        assert (await client.get(endpoint)).status_code == 503
