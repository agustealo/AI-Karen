"""Authenticated Content Intelligence source ingress and application policy tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.plugins import plugins as ingress
from ai_karen_engine.core.runtime.policy.runtime_policy import PolicyDecision
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
        self.executions.append(request)
        return SimpleNamespace(status="success", payload={"operation": "analyze"})


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
async def test_application_composes_real_source_host_and_uses_verified_text(monkeypatch):
    """Prove policy, repository, admission, and execution are connected."""
    import hashlib

    from ai_karen_engine.database import factory as database_factory
    from ai_karen_engine.services.database.repositories import repository_factory

    kernel = Kernel()
    store = Store()
    digest = hashlib.sha256(b"example").hexdigest()
    monkeypatch.setattr(
        database_factory,
        "get_database_client",
        lambda: SimpleNamespace(get_async_session=lambda: None),
    )
    monkeypatch.setattr(
        repository_factory,
        "RepositoryFactory",
        lambda **kwargs: SimpleNamespace(create_artifact_store=lambda: store),
    )
    # Stored metadata and text must agree on their SHA-256 revision.
    original_read = store.read_owner_active_code

    async def read_verified(*args):
        result = await original_read(*args)
        result.data.sha256 = digest
        return result

    store.read_owner_active_code = read_verified
    service = _service(kernel=kernel)
    response = await PluginService.analyze_content_owner_sources(
        service,
        **_args(references=[{"source_id": FILE, "revision": digest}]),
    )
    assert response["operation"] == "analyze"
    assert store.calls == [(FILE, TENANT, OWNER)]
    assert len(kernel.admissions) == 1
    assert len(kernel.executions) == 1
    assert kernel.executions[0].payload["documents"] == [{
        "id": FILE, "name": "notes.txt", "text": "example",
    }]
