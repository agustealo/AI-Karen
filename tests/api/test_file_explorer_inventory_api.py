"""Authenticated File Explorer route and RuntimePolicy admission contract."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.plugins import plugins as ingress
from ai_karen_engine.core.runtime.policy.runtime_policy import PolicyDecision
from ai_karen_engine.services.plugin_service import PluginService
from ai_karen_engine.extensions.executor import ExtensionExecutionService

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
FILE = "44444444-4444-4444-8444-000000000001"
SHA = "a" * 64


class Kernel:
    def __init__(self, status="enabled"):
        self.status = status
        self.calls = []

    def get_record(self, plugin_id):
        assert plugin_id == "file-explorer"
        return {"status": self.status, "dependencies_resolved": True}

    async def execute(self, request):
        self.calls.append(request)
        assert request.context.resource_scope["file_explorer_grant"] == "host_verified"
        entries = request.context.resource_scope["file_explorer_entries"]
        return SimpleNamespace(
            status="success", payload={"operation": "list", "items": entries}
        )


class Repository:
    def __init__(self):
        self.calls = []

    async def list_owner_artifacts_page(self, tenant_id, user_id, *, limit, cursor):
        self.calls.append((tenant_id, user_id, limit, cursor))
        return SimpleNamespace(
            success=True,
            data=[SimpleNamespace(
                id=FILE, tenant_id=TENANT, user_id=OWNER, deleted_at=None,
                filename="report.txt", sha256=SHA, size_bytes=11,
            )],
            metadata={"has_more": False, "next_cursor": None},
        )

    async def get_metadata(self, artifact_id, tenant_id):
        raise AssertionError("Listing must not open file metadata per item")


def _service(kernel=None, policy=None):
    kernel = kernel or Kernel()
    decision = PolicyDecision(
        decision_id="policy-verified",
        policy_version="v2",
        allowed=True,
        allowed_capabilities=["file-explorer", "data:read"],
        runtime_constraints={
            "authorized_user_id": OWNER,
            "authorized_tenant_id": TENANT,
            "allowed_plugins": ["file-explorer"],
        },
    )
    policy = policy or SimpleNamespace(evaluate=AsyncMock(return_value=decision))
    service = object.__new__(PluginService)
    service._ensure_initialized = AsyncMock()
    service._get_kernel = lambda: kernel
    service._policy_enforcer = policy
    return service, kernel, policy


def _args(**overrides):
    values = dict(
        user_id=OWNER,
        tenant_id=TENANT,
        roles=["user"],
        permissions=["data:read"],
        request_id="request-1",
        correlation_id="corr-1",
        limit=25,
        cursor=None,
    )
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_owner_inventory_evaluates_runtime_policy_and_uses_one_kernel(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    repository = Repository()
    monkeypatch.setattr(
        database_factory,
        "get_database_client",
        lambda: SimpleNamespace(get_async_session=lambda: None),
    )
    monkeypatch.setattr(
        repository_factory,
        "RepositoryFactory",
        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository),
    )
    service, kernel, policy = _service()
    page = await PluginService.list_file_explorer_owner_page(service, **_args())
    assert repository.calls == [(TENANT, OWNER, 25, None)]
    assert len(kernel.calls) == 1
    assert page["items"][0]["source_id"] == FILE
    assert page["items"][0]["sha256"] == SHA
    assert page["next_cursor"] is None
    assert page["inventory_semantics"] == "owner_metadata_page_not_live_acl"
    assert page["request_id"] == "request-1"
    assert kernel.calls[0].authorized_plan.policy_decision_id == "policy-verified"
    assert kernel.calls[0].context.audit_context["user_roles"] == ["user"]
    assert kernel.calls[0].context.audit_context["permissions"] == ["data:read"]
    assert ExtensionExecutionService._check_rbac(
        None,
        SimpleNamespace(required_roles=["user"]),
        kernel.calls[0].context,
        SimpleNamespace(required_roles=["user"]),
    ) is True
    assert ExtensionExecutionService._check_rbac(
        None,
        SimpleNamespace(required_roles=["admin"]),
        kernel.calls[0].context,
        SimpleNamespace(required_roles=["admin"]),
    ) is False
    evaluation = policy.evaluate.call_args.args[0]
    assert evaluation.plugin_id == "file-explorer"
    assert evaluation.user_id == OWNER
    assert evaluation.tenant_id == TENANT
    assert evaluation.requested_capabilities == ["file-explorer", "data:read"]


@pytest.mark.asyncio
async def test_service_denies_missing_entitlement_before_discovery():
    service, kernel, policy = _service()
    with pytest.raises(PermissionError, match="read_permission_required"):
        await PluginService.list_file_explorer_owner_page(
            service, **_args(permissions=[])
        )
    service._ensure_initialized.assert_not_awaited()
    policy.evaluate.assert_not_awaited()
    assert kernel.calls == []


@pytest.mark.asyncio
async def test_disabled_plugin_denied_before_policy_or_database():
    service, kernel, policy = _service(kernel=Kernel(status="disabled"))
    with pytest.raises(PermissionError, match="file_explorer_disabled"):
        await PluginService.list_file_explorer_owner_page(service, **_args())
    policy.evaluate.assert_not_awaited()
    assert kernel.calls == []


@pytest.mark.asyncio
async def test_policy_denial_and_identity_replay_fail_before_artifact_lookup():
    decision = PolicyDecision(
        decision_id="policy-denied", policy_version="v2", allowed=False,
    )
    service, kernel, _ = _service(
        policy=SimpleNamespace(evaluate=AsyncMock(return_value=decision))
    )
    with pytest.raises(PermissionError, match="policy_denied"):
        await PluginService.list_file_explorer_owner_page(service, **_args())
    assert kernel.calls == []

    decision = PolicyDecision(
        decision_id="policy-cross-tenant", policy_version="v2", allowed=True,
        allowed_capabilities=["file-explorer", "data:read"],
        runtime_constraints={
            "authorized_user_id": OWNER,
            "authorized_tenant_id": "33333333-3333-4333-8333-333333333333",
            "allowed_plugins": ["file-explorer"],
        },
    )
    service, kernel, _ = _service(
        policy=SimpleNamespace(evaluate=AsyncMock(return_value=decision))
    )
    with pytest.raises(PermissionError, match="policy_scope_denied"):
        await PluginService.list_file_explorer_owner_page(service, **_args())
    assert kernel.calls == []


@pytest.mark.asyncio
async def test_route_rejects_rbac_denial_without_calling_service(monkeypatch):
    rbac = SimpleNamespace(
        has_permission=lambda *_: False,
        audit_access_attempt=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: rbac)
    service = SimpleNamespace(list_file_explorer_owner_page=AsyncMock())
    request = Request({"type": "http", "method": "GET", "path": "/api/plugins/file-explorer/inventory", "headers": []})
    with pytest.raises(HTTPException) as error:
        await ingress.list_file_explorer_inventory(
            request=request,
            limit=25,
            cursor=None,
            current_user={"user_id": OWNER, "tenant_id": TENANT, "roles": ["user"]},
            plugin_service=service,
        )
    assert error.value.status_code == 403
    service.list_file_explorer_owner_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_rejects_synthetic_tenant_before_rbac(monkeypatch):
    monkeypatch.setattr(
        ingress, "get_rbac_manager",
        lambda: (_ for _ in ()).throw(AssertionError("RBAC should not be consulted")),
    )
    request = Request({"type": "http", "method": "GET", "path": "/api/plugins/file-explorer/inventory", "headers": []})
    with pytest.raises(HTTPException) as error:
        await ingress.list_file_explorer_inventory(
            request=request, limit=10, cursor=None,
            current_user={"user_id": OWNER, "tenant_id": "default"},
            plugin_service=SimpleNamespace(),
        )
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_hierarchy_uses_existing_policy_and_kernel_before_capability(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    repository = Repository()
    service, kernel, policy = _service()
    async def probe(tenant_id, user_id):
        assert (tenant_id, user_id) == (TENANT, OWNER)
        assert len(kernel.calls) == 1
        assert policy.evaluate.await_count == 1
        return SimpleNamespace(success=False, data=None)
    repository.owner_hierarchy_available = probe
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository))
    page = await service.list_file_explorer_owner_page(**_args(), hierarchy=True)
    assert page["available"] is False
    assert page["folders"] == page["breadcrumbs"] == []
    assert repository.calls == []


@pytest.mark.asyncio
async def test_hierarchy_route_denies_rbac_before_service(monkeypatch):
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: SimpleNamespace(
        has_permission=lambda *_: False,
        audit_access_attempt=lambda *args, **kwargs: None,
    ))
    service = SimpleNamespace(list_file_explorer_owner_page=AsyncMock())
    request = Request({"type": "http", "method": "GET",
                       "path": "/api/plugins/file-explorer/hierarchy", "headers": []})
    with pytest.raises(HTTPException) as error:
        await ingress.list_file_explorer_hierarchy(
            request=request, limit=25,
            current_user={"user_id": OWNER, "tenant_id": TENANT, "roles": ["user"]},
            plugin_service=service,
        )
    assert error.value.status_code == 403
    service.list_file_explorer_owner_page.assert_not_awaited()
