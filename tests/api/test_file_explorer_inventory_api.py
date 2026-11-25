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


@pytest.mark.asyncio
async def test_folder_scoped_files_keep_content_and_organization_revisions_separate():
    from ai_karen_engine.extensions.owner_inventory import ArtifactSourceAdapter

    folder = "55555555-5555-4555-8555-555555555555"

    class ScopedRepository(Repository):
        async def list_owner_artifacts_page(self, tenant_id, user_id, **kwargs):
            self.calls.append((tenant_id, user_id, kwargs))
            return SimpleNamespace(success=True, data=[SimpleNamespace(
                id=FILE, tenant_id=TENANT, user_id=OWNER, deleted_at=None,
                filename="report.txt", sha256=SHA, size_bytes=11,
                folder_id=folder, organization_revision=9223372036854775806,
            )], metadata={"has_more": False, "next_cursor": None})

    repository = ScopedRepository()
    adapter = ArtifactSourceAdapter(repository)
    page = await adapter.list_owner_sources_page(
        tenant_id=TENANT, user_id=OWNER, limit=10, cursor="opaque-cursor",
        folder_scoped=True, folder_id=folder,
    )
    assert repository.calls == [(TENANT, OWNER, {
        "limit": 10, "cursor": "opaque-cursor", "folder_scoped": True, "folder_id": folder,
    })]
    assert page["items"][0]["revision"] == SHA
    assert page["items"][0]["organization_revision"] == "9223372036854775806"
    assert page["items"][0]["parent_id"] == folder
    with pytest.raises(RuntimeError, match="organization_scope_invalid"):
        await adapter.list_owner_sources_page(
            tenant_id=TENANT, user_id=OWNER, folder_scoped=True, folder_id=None,
        )


@pytest.mark.asyncio
async def test_governed_hierarchy_projects_root_files_after_kernel(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    service, kernel, policy = _service()

    class RootRepository(Repository):
        async def owner_hierarchy_available(self, tenant_id, user_id):
            assert len(kernel.calls) == 1 and policy.evaluate.await_count == 1
            return SimpleNamespace(success=True, data=True)

        async def list_owner_folders(self, tenant_id, user_id, **kwargs):
            return SimpleNamespace(success=True, data=[],
                                   metadata={"has_more": False, "next_folder_id": None})

        async def list_owner_artifacts_page(self, tenant_id, user_id, **kwargs):
            assert kwargs["folder_scoped"] is True and kwargs["folder_id"] is None
            assert len(kernel.calls) == 1
            return SimpleNamespace(success=True, data=[SimpleNamespace(
                id=FILE, tenant_id=tenant_id, user_id=user_id, deleted_at=None,
                filename="report.txt", sha256=SHA, size_bytes=11,
                folder_id=None, organization_revision=1,
            )], metadata={"has_more": False, "next_cursor": None})

    repository = RootRepository()
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository))
    page = await service.list_file_explorer_owner_page(**_args(), hierarchy=True)
    response = ingress.FileExplorerHierarchyResponse.model_validate(page)
    assert response.available is True and response.files[0].revision == SHA
    assert response.files[0].organization_revision == "1"
    assert response.files_has_more is False and response.next_file_cursor is None


@pytest.mark.asyncio
async def test_folder_creation_denies_read_only_before_discovery():
    service, kernel, policy = _service()
    args = _args()
    args.pop("limit")
    args.pop("cursor")
    with pytest.raises(PermissionError):
        await service.create_file_explorer_folder(**args, name="Reports")
    service._ensure_initialized.assert_not_awaited()
    policy.evaluate.assert_not_awaited()
    assert kernel.calls == []


@pytest.mark.asyncio
async def test_folder_create_route_denies_write_before_service(monkeypatch):
    seen = []
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: SimpleNamespace(
        has_permission=lambda user, permission: seen.append(permission) or False,
        audit_access_attempt=lambda *args, **kwargs: None,
    ))
    service = SimpleNamespace(create_file_explorer_folder=AsyncMock())
    request = Request({"type": "http", "method": "POST",
                       "path": "/api/plugins/file-explorer/folders", "headers": []})
    with pytest.raises(HTTPException) as error:
        await ingress.create_file_explorer_folder(
            payload=ingress.FileExplorerCreateFolderRequest(name="Reports"),
            request=request, current_user={"user_id": OWNER, "tenant_id": TENANT},
            plugin_service=service,
        )
    assert error.value.status_code == 403
    assert seen == [ingress.Permission.DATA_WRITE]
    service.create_file_explorer_folder.assert_not_awaited()


@pytest.mark.asyncio
async def test_folder_creation_requires_bound_write_plan_and_kernel(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    service, kernel, policy = _service()
    args = _args(permissions=["data:read", "data:write"])
    args.pop("limit")
    args.pop("cursor")
    scope = {"operation": "file_explorer.folder.create", "name": "Reports",
             "parent_folder_id": None}
    decision = PolicyDecision(
        decision_id="write-verified", policy_version="v2", allowed=True,
        allowed_capabilities=["file-explorer", "data:read", "data:write",
                              "file_explorer.folder.create"],
        resource_scope=scope,
        runtime_constraints={"authorized_user_id": OWNER,
                             "authorized_tenant_id": TENANT,
                             "allowed_plugins": ["file-explorer"]},
    )
    policy.evaluate.return_value = decision
    repository = Repository()

    async def create(tenant_id, user_id, *, name, parent_folder_id):
        assert (tenant_id, user_id, name, parent_folder_id) == (TENANT, OWNER, "Reports", None)
        assert len(kernel.calls) == 1
        return SimpleNamespace(success=True, data=SimpleNamespace(
            folder_id=FILE, parent_folder_id=None, name=name, revision=1,
        ))

    repository.create_owner_folder = create
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository))
    result = await service.create_file_explorer_folder(**args, name="Reports")
    assert result["folder"]["revision"] == "1"
    assert policy.evaluate.call_args.args[0].resource_scope == scope
    with pytest.raises(PermissionError):
        await service.create_file_explorer_folder(**args, name="Different")
    assert len(kernel.calls) == 1


@pytest.mark.asyncio
async def test_folder_rename_binds_source_name_and_revision(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory
    from ai_karen_engine.extensions.owner_inventory import FileExplorerFolderConflict

    service, kernel, policy = _service()
    args = _args(permissions=["data:read", "data:write"])
    args.pop("limit")
    args.pop("cursor")
    scope = {"operation": "file_explorer.folder.rename", "folder_id": FILE,
             "name": "Renamed", "expected_revision": 7}
    policy.evaluate.return_value = PolicyDecision(
        decision_id="rename-verified", policy_version="v2", allowed=True,
        allowed_capabilities=["file-explorer", "data:read", "data:write",
                              "file_explorer.folder.rename"],
        resource_scope=scope,
        runtime_constraints={"authorized_user_id": OWNER,
                             "authorized_tenant_id": TENANT,
                             "allowed_plugins": ["file-explorer"]},
    )
    repository = Repository()
    calls = []

    async def rename(tenant_id, user_id, folder_id, *, name, expected_revision):
        calls.append((tenant_id, user_id, folder_id, name, expected_revision))
        assert len(kernel.calls) == len(calls)
        if len(calls) > 1:
            return SimpleNamespace(success=False, error="artifact_folder_conflict_or_unavailable")
        return SimpleNamespace(success=True, data=SimpleNamespace(
            folder_id=FILE, parent_folder_id=None, name=name, revision=8,
        ))

    repository.rename_owner_folder = rename
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository))
    result = await service.rename_file_explorer_folder(
        **args, folder_id=FILE, name="Renamed", expected_revision=7,
    )
    assert result["folder"]["revision"] == "8"
    assert calls == [(TENANT, OWNER, FILE, "Renamed", 7)]
    with pytest.raises(PermissionError):
        await service.rename_file_explorer_folder(
            **args, folder_id=FILE, name="Renamed", expected_revision=8,
        )
    assert len(calls) == 1
    with pytest.raises(FileExplorerFolderConflict):
        await service.rename_file_explorer_folder(
            **args, folder_id=FILE, name="Renamed", expected_revision=7,
        )


def test_rename_revision_requires_lossless_decimal_string():
    from pydantic import ValidationError
    assert ingress.FileExplorerRenameFolderRequest(
        name="Renamed", expected_revision="9223372036854775806",
    ).expected_revision == "9223372036854775806"
    for invalid in (1, True, "0", "-1", "1.0", "01"):
        with pytest.raises(ValidationError):
            ingress.FileExplorerRenameFolderRequest(name="Renamed", expected_revision=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["folder", "artifact"])
async def test_move_binds_kind_source_destination_and_revision(monkeypatch, kind):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory
    from ai_karen_engine.extensions.owner_inventory import FileExplorerFolderConflict

    service, kernel, policy = _service()
    args = _args(permissions=["data:read", "data:write"])
    args.pop("limit")
    args.pop("cursor")
    destination = "55555555-5555-4555-8555-555555555555"
    operation = f"file_explorer.{kind}.move"
    scope = {"operation": operation, "source_id": FILE,
             "destination_id": destination, "expected_revision": 7}
    policy.evaluate.return_value = PolicyDecision(
        decision_id="move-verified", policy_version="v2", allowed=True,
        allowed_capabilities=["file-explorer", "data:read", "data:write", operation],
        resource_scope=scope,
        runtime_constraints={"authorized_user_id": OWNER,
                             "authorized_tenant_id": TENANT,
                             "allowed_plugins": ["file-explorer"]},
    )
    repository = Repository()
    calls = []

    async def move(tenant_id, user_id, source_id, **kwargs):
        calls.append((tenant_id, user_id, source_id, kwargs))
        assert len(kernel.calls) == len(calls)
        if len(calls) > 1:
            return SimpleNamespace(success=False, error="artifact_folder_conflict_or_unavailable")
        return SimpleNamespace(success=True, data=8)

    setattr(repository, f"move_owner_{kind}", move)
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repository))
    result = await service.move_file_explorer_item(
        **args, kind=kind, source_id=FILE, destination_id=destination, expected_revision=7,
    )
    assert result["organization_revision"] == "8"
    assert result["parent_folder_id"] == destination
    key = "parent_folder_id" if kind == "folder" else "folder_id"
    assert calls == [(TENANT, OWNER, FILE, {key: destination, "expected_revision": 7})]
    with pytest.raises(PermissionError):
        await service.move_file_explorer_item(
            **args, kind=kind, source_id=FILE, destination_id=None, expected_revision=7,
        )
    assert len(calls) == 1
    with pytest.raises(FileExplorerFolderConflict):
        await service.move_file_explorer_item(
            **args, kind=kind, source_id=FILE, destination_id=destination, expected_revision=7,
        )


def test_move_requires_explicit_destination_and_lossless_revision():
    from pydantic import ValidationError

    assert ingress.FileExplorerMoveRequest(
        destination_id=None, expected_revision="7",
    ).destination_id is None
    with pytest.raises(ValidationError):
        ingress.FileExplorerMoveRequest(expected_revision="7")
    with pytest.raises(ValidationError):
        ingress.FileExplorerMoveRequest(destination_id=None, expected_revision=7)
