"""Authenticated Content Intelligence source ingress and application policy tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.plugins import plugins as ingress
from ai_karen_engine.core.runtime.policy.runtime_policy import PolicyDecision
from ai_karen_engine.extensions.content_intelligence_sources import MAX_CONTENT_SOURCE_REFERENCES
from ai_karen_engine.services.plugin_service import PluginService

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
FILE = "44444444-4444-4444-8444-000000000001"
SHA = "a" * 64


def _payload():
    return ingress.ContentOwnerSourcesRequest.model_validate({
        "operation": "analyze",
        "references": [{"source_id": FILE, "revision": SHA}],
    })


def _request():
    return Request({
        "type": "http", "method": "POST",
        "path": "/api/plugins/content-intelligence/owner-sources",
        "headers": [],
    })


def _args(**overrides):
    result = dict(
        user_id=OWNER, tenant_id=TENANT,
        roles=["user"], permissions=["data:read"],
        request_id="request-1", correlation_id="correlation-1",
        operation="analyze",
        references=[{"source_id": FILE, "revision": SHA}],
    )
    result.update(overrides)
    return result


def _policy(allowed=True, tenant=TENANT):
    return SimpleNamespace(evaluate=AsyncMock(return_value=PolicyDecision(
        decision_id="policy-verified", policy_version="v2",
        allowed=allowed,
        allowed_capabilities=["content-intelligence", "data:read"],
        runtime_constraints={
            "authorized_user_id": OWNER,
            "authorized_tenant_id": tenant,
            "allowed_plugins": ["content-intelligence"],
        },
    )))


class Kernel:
    def __init__(self, status="enabled"):
        self.status = status
        self.admissions = []
        self.executions = []

    def get_record(self, plugin_id):
        assert plugin_id == "content-intelligence"
        return {"status": self.status, "dependencies_resolved": True}

    async def admit(self, request):
        self.admissions.append(request)
        return SimpleNamespace(status="admitted")

    async def execute(self, request):
        import hashlib

        self.executions.append(request)
        documents = request.payload["documents"]
        return SimpleNamespace(status="success", payload={
            "operation": "analyze",
            "persisted": False,
            "documents": [{
                "id": document["id"],
                "name": document["name"],
                "folder_id": None,
                "sha256": hashlib.sha256(document["text"].encode("utf-8")).hexdigest(),
                "characters": len(document["text"]),
                "top_terms": [],
            } for document in documents],
            "relationships": [],
            "relationship_semantics": "lexical_hints_not_verified_entities",
        })


class Store:
    def __init__(self):
        self.calls = []

    async def read_owner_active_code(self, artifact_id, tenant_id, user_id):
        self.calls.append((artifact_id, tenant_id, user_id))
        return SimpleNamespace(success=True, data=SimpleNamespace(
            artifact_id=FILE, tenant_id=TENANT, user_id=OWNER,
            filename="notes.txt", sha256=SHA, text="example",
        ))


def _service(kernel=None, policy=None):
    service = object.__new__(PluginService)
    service._ensure_initialized = AsyncMock()
    service._get_kernel = lambda: kernel or Kernel()
    service._policy_enforcer = policy or _policy()
    return service


@pytest.mark.asyncio
async def test_service_requires_read_permission_before_policy_and_repository():
    policy = _policy()
    service = _service(policy=policy)
    with pytest.raises(PermissionError, match="read_permission_required"):
        await PluginService.analyze_content_owner_sources(
            service, **_args(permissions=[]),
        )
    service._ensure_initialized.assert_not_awaited()
    policy.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_plugin_denied_before_policy_or_store():
    policy = _policy()
    service = _service(kernel=Kernel(status="disabled"), policy=policy)
    with pytest.raises(PermissionError, match="plugin_disabled"):
        await PluginService.analyze_content_owner_sources(service, **_args())
    policy.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_denial_and_foreign_tenant_fail_before_read():
    for policy in (_policy(allowed=False), _policy(tenant="33333333-3333-4333-8333-333333333333")):
        service = _service(policy=policy)
        with pytest.raises(PermissionError):
            await PluginService.analyze_content_owner_sources(service, **_args())


@pytest.mark.asyncio
async def test_authenticated_ingress_delegates_only_valid_references(monkeypatch):
    granted = []
    rbac = SimpleNamespace(
        has_permission=lambda user, permission: True,
        get_user_permissions=lambda user: [ingress.Permission.DATA_READ],
        audit_access_attempt=lambda *args, **kwargs: granted.append(kwargs),
    )
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: rbac)
    service = SimpleNamespace(analyze_content_owner_sources=AsyncMock(
        return_value={"operation": "analyze", "documents": [], "persisted": False}
    ))
    answer = await ingress.analyze_content_owner_sources(
        payload=_payload(), request=_request(),
        current_user={
            "user_id": OWNER, "tenant_id": TENANT, "roles": ["user"],
            "permissions": ["data:read"],
        },
        plugin_service=service,
    )
    assert answer["operation"] == "analyze"
    kwargs = service.analyze_content_owner_sources.await_args.kwargs
    assert kwargs["references"] == [{"source_id": FILE, "revision": SHA}]
    assert kwargs["user_id"] == OWNER and kwargs["tenant_id"] == TENANT
    assert granted and granted[0]["granted"] is True


@pytest.mark.asyncio
async def test_ingress_rejects_denied_permission_without_calling_service(monkeypatch):
    rbac = SimpleNamespace(
        has_permission=lambda *args: False,
        audit_access_attempt=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: rbac)
    service = SimpleNamespace(analyze_content_owner_sources=AsyncMock())
    with pytest.raises(HTTPException) as denied:
        await ingress.analyze_content_owner_sources(
            payload=_payload(), request=_request(),
            current_user={"user_id": OWNER, "tenant_id": TENANT},
            plugin_service=service,
        )
    assert denied.value.status_code == 403
    service.analyze_content_owner_sources.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingress_rejects_synthetic_identity_before_rbac(monkeypatch):
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: (
        _ for _ in ()
    ).throw(AssertionError("RBAC must not see synthetic tenants")))
    with pytest.raises(HTTPException) as denied:
        await ingress.analyze_content_owner_sources(
            payload=_payload(), request=_request(),
            current_user={"user_id": OWNER, "tenant_id": "default"},
            plugin_service=SimpleNamespace(),
        )
    assert denied.value.status_code == 401


@pytest.mark.parametrize("invalid", [
    {"operation": "analyze", "references": [{"source_id": FILE, "revision": SHA, "text": "secret"}]},
    {"operation": "analyze", "references": [{"source_id": FILE, "revision": "invalid"}]},
    {"operation": "analyze", "references": []},
    {"operation": "browse", "references": [{"source_id": FILE, "revision": SHA}]},
])
def test_untrusted_request_shapes_rejected(invalid):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ingress.ContentOwnerSourcesRequest.model_validate(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate_during_policy", [False, True])
async def test_application_composes_real_source_host_and_uses_verified_text(
    monkeypatch, mutate_during_policy,
):
    """Prove policy, repository, admission, and execution are connected."""
    import hashlib

    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.integrations import supabase_client
    from ai_karen_engine.services.database.repositories import repository_factory

    kernel = Kernel()
    store = Store()
    digest = hashlib.sha256(b"example").hexdigest()
    monkeypatch.setattr(
        database_factory,
        "get_database_client",
        lambda: SimpleNamespace(get_async_session=lambda: None),
    )
    platform = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: object()))

    def configured_factory(*, session_factory, storage_client=None):
        assert storage_client is platform
        return SimpleNamespace(create_artifact_store=lambda: store)

    monkeypatch.setattr(supabase_client, "get_supabase_platform", lambda: platform)
    monkeypatch.setattr(
        repository_factory, "RepositoryFactory", configured_factory,
    )
    # Stored metadata and text must agree on their SHA-256 revision.
    original_read = store.read_owner_active_code

    async def read_verified(*args):
        result = await original_read(*args)
        result.data.sha256 = digest
        return result

    store.read_owner_active_code = read_verified
    references = [{"source_id": FILE, "revision": digest}]
    roles = ["user"]
    permissions = ["data:read"]
    policy = _policy()
    service = _service(kernel=kernel, policy=policy)
    if mutate_during_policy:
        decision = policy.evaluate.return_value

        async def evaluate_and_mutate(request):
            assert request.roles == ["user"]
            assert request.permissions == ["data:read"]
            references[0]["source_id"] = "55555555-5555-4555-8555-000000000001"
            references[0]["revision"] = "b" * 64
            roles[:] = ["admin"]
            permissions.append("data:write")
            return decision

        policy.evaluate.side_effect = evaluate_and_mutate
    response = await PluginService.analyze_content_owner_sources(
        service,
        **_args(references=references, roles=roles, permissions=permissions),
    )
    assert kernel.admissions[0].context.audit_context["user_roles"] == ["user"]
    assert kernel.admissions[0].context.audit_context["permissions"] == ["data:read"]
    assert response["operation"] == "analyze"
    assert response["persisted"] is False
    assert response["documents"] == [{
        "id": FILE, "name": "notes.txt", "folder_id": None,
        "sha256": digest, "characters": len("example"), "top_terms": [],
    }]
    assert response["relationships"] == []
    assert store.calls == [(FILE, TENANT, OWNER)]
    assert len(kernel.admissions) == 1
    assert len(kernel.executions) == 1
    assert kernel.executions[0].payload["documents"] == [{
        "id": FILE, "name": "notes.txt", "text": "example",
    }]


@pytest.mark.asyncio
async def test_storage_unavailable_fails_closed_before_artifact_read(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.integrations import supabase_client
    from ai_karen_engine.services.database.repositories import repository_factory

    monkeypatch.setattr(
        database_factory,
        "get_database_client",
        lambda: SimpleNamespace(get_async_session=lambda: None),
    )
    monkeypatch.setattr(
        supabase_client, "get_supabase_platform",
        lambda: SimpleNamespace(storage=None),
    )

    def forbidden_factory(**kwargs):
        raise AssertionError("No repository may be created without Storage")

    monkeypatch.setattr(repository_factory, "RepositoryFactory", forbidden_factory)
    with pytest.raises(RuntimeError, match="content_source_storage_unavailable"):
        await PluginService.analyze_content_owner_sources(_service(), **_args())


def _inventory_args(**overrides):
    args = _args()
    args.pop("operation")
    args.pop("references")
    args.update(overrides)
    return args


@pytest.mark.asyncio
async def test_content_inventory_independent_of_file_explorer(monkeypatch):
    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    kernel = Kernel()

    async def list_page(tenant_id, user_id, *, limit, cursor):
        assert len(kernel.admissions) == 1
        assert (tenant_id, user_id, limit, cursor) == (TENANT, OWNER, 10, None)
        return SimpleNamespace(
            success=True, data=[SimpleNamespace(
                id=FILE, tenant_id=TENANT, user_id=OWNER, filename="notes.txt",
                sha256=SHA, size_bytes=12, deleted_at=None,
            )], metadata={"has_more": False, "next_cursor": None},
        )

    repo = SimpleNamespace(
        list_owner_artifacts_page=list_page, get_metadata=AsyncMock(),
    )
    monkeypatch.setattr(database_factory, "get_database_client",
                        lambda: SimpleNamespace(get_async_session=lambda: None))
    monkeypatch.setattr(repository_factory, "RepositoryFactory",
                        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: repo))
    page = await _service(kernel=kernel).list_content_owner_page(**_inventory_args(limit=10))
    assert page["items"][0]["source_id"] == FILE
    assert page["items"][0]["revision"] == SHA
    assert page["inventory_semantics"] == "owner_metadata_page_not_live_acl"
    assert page["max_selection"] == MAX_CONTENT_SOURCE_REFERENCES
    assert kernel.admissions[0].plugin_id == "content-intelligence"
    assert kernel.executions == []
    repo.get_metadata.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disabled", "policy", "foreign", "kernel", "permission"])
async def test_content_inventory_denies_before_repository(monkeypatch, failure):
    from ai_karen_engine.database import factory as database_factory

    kernel = Kernel(status="disabled" if failure == "disabled" else "enabled")
    if failure == "kernel":
        kernel.admit = AsyncMock(return_value=SimpleNamespace(status="denied"))
    policy = _policy(allowed=failure != "policy",
                     tenant="33333333-3333-4333-8333-333333333333" if failure == "foreign" else TENANT)
    def forbidden_database():
        raise AssertionError("Denied inventory must not access repository")
    monkeypatch.setattr(database_factory, "get_database_client", forbidden_database)
    with pytest.raises(PermissionError):
        await _service(kernel=kernel, policy=policy).list_content_owner_page(
            **_inventory_args(permissions=[] if failure == "permission" else ["data:read"]),
        )


@pytest.mark.asyncio
async def test_content_inventory_ingress_delegates_authenticated_scope(monkeypatch):
    rbac = SimpleNamespace(
        has_permission=lambda *args: True,
        get_user_permissions=lambda user: [ingress.Permission.DATA_READ],
        audit_access_attempt=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: rbac)
    service = SimpleNamespace(list_content_owner_page=AsyncMock(return_value={
        "items": [], "has_more": False, "next_cursor": None,
        "inventory_semantics": "owner_metadata_page_not_live_acl",
        "request_id": "request-1", "correlation_id": "correlation-1",
        "max_selection": MAX_CONTENT_SOURCE_REFERENCES,
    }))
    result = await ingress.list_content_inventory(
        request=_request(), limit=10, cursor=None,
        current_user={"user_id": OWNER, "tenant_id": TENANT, "roles": ["user"],
                      "permissions": ["data:read"]},
        plugin_service=service,
    )
    assert result.items == []
    assert result.max_selection == MAX_CONTENT_SOURCE_REFERENCES
    assert service.list_content_owner_page.await_args.kwargs["user_id"] == OWNER
    assert service.list_content_owner_page.await_args.kwargs["tenant_id"] == TENANT


@pytest.mark.asyncio
@pytest.mark.parametrize("ceiling", [{}, {"max_selection": None}, {"max_selection": True},
                                    {"max_selection": "12"}, {"max_selection": 0},
                                    {"max_selection": MAX_CONTENT_SOURCE_REFERENCES + 1}])
async def test_content_inventory_rejects_invalid_service_ceiling(monkeypatch, ceiling):
    monkeypatch.setattr(ingress, "get_rbac_manager", lambda: SimpleNamespace(
        has_permission=lambda *_: True,
        get_user_permissions=lambda *_: [ingress.Permission.DATA_READ],
        audit_access_attempt=lambda *args, **kwargs: None,
    ))
    service = SimpleNamespace(list_content_owner_page=AsyncMock(return_value={
        "items": [], "has_more": False, "next_cursor": None,
        "inventory_semantics": "owner_metadata_page_not_live_acl",
        "request_id": "request-1", "correlation_id": "correlation-1",
        **ceiling,
    }))
    with pytest.raises(HTTPException) as exc:
        await ingress.list_content_inventory(
            request=_request(), limit=10, cursor=None,
            current_user={"user_id": OWNER, "tenant_id": TENANT, "roles": ["user"],
                          "permissions": ["data:read"]},
            plugin_service=service,
        )
    assert exc.value.status_code == 503
    assert exc.value.detail == "Content inventory is unavailable"
    service.list_content_owner_page.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("references", [
    [{"source_id": FILE, "revision": SHA}] * 2,
    [{"source_id": FILE, "revision": "invalid"}],
    [{"source_id": "not-a-uuid", "revision": SHA}],
    [{"source_id": FILE, "revision": SHA, "text": "caller content"}],
])
async def test_invalid_source_selection_is_denied_before_async_policy(references):
    policy = _policy()
    service = _service(policy=policy)
    with pytest.raises(ValueError):
        await service.analyze_content_owner_sources(**_args(references=references))
    service._ensure_initialized.assert_not_awaited()
    policy.evaluate.assert_not_awaited()
