from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.plugins import plugins as plugin_routes
from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    DataClassification,
    ExtensionExecutionResult,
    ResponseSource,
    ResultTrust,
    TrustTier,
)
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services.plugin_service import ExecutionStatus, PluginService


def _manifest(*, with_schema: bool = True) -> ExtensionManifest:
    schema = None
    if with_schema:
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additional_properties": False,
        }
    return ExtensionManifest(
        name="alpha-plugin",
        version="1.0.0",
        display_name="Alpha Plugin",
        description="Plugin contract fixture",
        author="Kari",
        license="MIT",
        category="test",
        tags=["contract"],
        entrypoint="handler:MainExtension",
        config_schema=schema,
    )


def _metadata(*, state: str = "enabled") -> dict:
    return {
        "manifest": _manifest(),
        "path": Path("/tmp/alpha-plugin"),
        "status": state,
        "checksum": "fixture",
        "error_message": None,
        "dependencies_resolved": True,
        "compatibility_checked": True,
    }


class _Kernel:
    def __init__(self, *, state: str = "enabled") -> None:
        self.record = _metadata(state=state)
        self.request = None
        self.runtime_registry = SimpleNamespace(get=lambda name: object())

    def get_record(self, name):
        return self.record if name == "alpha-plugin" else None

    def list_records(self):
        return [self.record]

    async def execute(self, request):
        self.request = request
        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id=request.plugin_id,
            plugin_version="1.0.0",
            capability=request.capability,
            source=ResponseSource.PLUGIN,
            payload={"ok": True},
            latency_ms=10.0,
            status="success",
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=TrustTier.FIRST_PARTY,
            result_trust=ResultTrust.VERIFIED,
            data_classification=DataClassification.PUBLIC,
        )

    def registry_stats(self):
        return {
            "total_plugins": 1,
            "by_status": {self.record["status"]: 1},
            "by_category": {"test": 1},
            "by_type": {"test": 1},
        }

    def active_executions(self):
        return {}

    async def refresh(self):
        return 1

    async def cleanup(self):
        return None

    async def enable(self, name):
        if name != "alpha-plugin":
            return False
        self.record["status"] = "enabled"
        return True

    async def disable(self, name):
        if name != "alpha-plugin":
            return False
        self.record["status"] = "disabled"
        return True


def _service(*, state: str = "enabled") -> tuple[PluginService, _Kernel]:
    service = PluginService()
    kernel = _Kernel(state=state)
    service.kernel = kernel  # type: ignore[assignment]
    service.initialized = True
    return service, kernel


def _request(path: str = "/api/plugins/alpha-plugin/enable") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [
                (b"x-request-id", b"request-123"),
                (b"x-correlation-id", b"correlation-456"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


class _RBAC:
    def __init__(self, granted: bool):
        self.granted = granted
        self.permission = None
        self.audit = None

    def has_permission(self, user, permission):
        self.permission = permission
        return self.granted

    def get_user_permissions(self, user):
        return {Permission.READ}

    def audit_access_attempt(
        self,
        user_data,
        permission,
        resource,
        granted,
        request=None,
        additional_context=None,
    ):
        self.audit = {
            "user": user_data,
            "permission": permission,
            "resource": resource,
            "granted": granted,
            "context": additional_context or {},
        }


class _Decision:
    decision_id = "policy-123"
    allowed = True
    allowed_capabilities = ["search"]
    denied_capabilities = []

    def __init__(self, request):
        self.plan = AuthorizedExecutionPlan(
            execution_id="exec-policy-123",
            policy_decision_id=self.decision_id,
            authorized_user_id=request.user_id,
            authorized_tenant_id=request.tenant_id,
            authorized_session_id=request.session_id,
            allowed_capabilities=["search"],
            allowed_plugins=[request.plugin_id] if request.plugin_id else [],
        )

    def to_authorized_plan(self):
        return self.plan


class _Policy:
    def __init__(self):
        self.request = None

    async def evaluate(self, request):
        self.request = request
        return _Decision(request)


@pytest.mark.asyncio
async def test_parameter_validation_uses_catalog_manifest_schema():
    service, _ = _service()

    assert await service.validate_plugin_parameters(
        "alpha-plugin", {"query": "hello", "limit": 5}
    )
    assert not await service.validate_plugin_parameters("alpha-plugin", {"limit": 5})
    assert not await service.validate_plugin_parameters(
        "alpha-plugin", {"query": "hello", "limit": 0}
    )
    assert not await service.validate_plugin_parameters(
        "alpha-plugin", {"query": "hello", "unknown": True}
    )


@pytest.mark.asyncio
async def test_execution_delegates_typed_request_to_canonical_kernel():
    service, kernel = _service()
    policy = _Policy()
    service._policy_enforcer = policy

    result = await service.execute_plugin(
        "alpha-plugin",
        parameters={"query": "hello"},
        user_id="user-1",
        tenant_id="tenant-a",
        session_id="session-1",
        correlation_id="corr-1",
        roles=["user"],
        permissions=["read"],
        allowed_capabilities=["search"],
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert result.user_id == "user-1"
    assert result.tenant_id == "tenant-a"
    assert result.correlation_id == "corr-1"
    assert policy.request.tenant_id == "tenant-a"
    assert policy.request.plugin_id == "alpha-plugin"
    assert kernel.request is not None
    assert kernel.request.plugin_id == "alpha-plugin"
    assert kernel.request.capability == "execute"
    assert isinstance(kernel.request.authorized_plan, AuthorizedExecutionPlan)
    assert kernel.request.authorized_plan.allowed_plugins == ["alpha-plugin"]
    assert kernel.request.context.policy_decision_id == "policy-123"


@pytest.mark.asyncio
async def test_execution_fails_closed_without_tenant_scope():
    service, kernel = _service()
    policy = _Policy()
    service._policy_enforcer = policy

    result = await service.execute_plugin(
        "alpha-plugin",
        parameters={"query": "hello"},
        user_id="user-1",
        tenant_id=None,
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "identity_scope_missing"
    assert policy.request is None
    assert kernel.request is None


@pytest.mark.asyncio
async def test_list_plugins_preserves_disabled_truth():
    service, _ = _service(state="disabled")
    plugins = await service.list_plugins()
    assert len(plugins) == 1
    assert plugins[0]["status"] == "disabled"
    assert await service.list_plugins(enabled_only=True) == []


def test_route_projects_dictionary_metadata_and_schema():
    service, kernel = _service()
    response = plugin_routes._plugin_info_response(kernel.record, service)
    assert response.name == "alpha-plugin"
    assert response.status == "enabled"
    assert response.enabled is True
    assert response.parameters["query"]["type"] == "string"


def test_dev_user_does_not_bypass_plugin_manage_permission(monkeypatch):
    rbac = _RBAC(granted=False)
    monkeypatch.setattr(plugin_routes, "get_rbac_manager", lambda: rbac)
    user = {
        "user_id": "dev-user",
        "tenant_id": "tenant-a",
        "roles": ["user"],
    }
    with pytest.raises(HTTPException) as exc_info:
        plugin_routes._require_plugin_mutation_access(_request(), user)
    assert exc_info.value.status_code == 403
    assert rbac.permission is Permission.ADMIN_PLUGINS_MANAGE
    assert rbac.audit["granted"] is False


def test_only_state_changing_routes_require_plugin_manage_permission():
    routes = {route.path: route for route in plugin_routes.router.routes}
    for path in {"/reload", "/{plugin_name}/enable", "/{plugin_name}/disable"}:
        assert any(
            dependency.call is plugin_routes._require_plugin_mutation_access
            for dependency in routes[path].dependant.dependencies
        )
    for path in {
        "/",
        "/categories",
        "/metrics",
        "/health",
        "/{plugin_name}",
        "/{plugin_name}/validate",
    }:
        assert all(
            dependency.call is not plugin_routes._require_plugin_mutation_access
            for dependency in routes[path].dependant.dependencies
        )


def test_private_routes_keep_authenticated_identity_dependency():
    for route in plugin_routes.router.routes:
        assert any(
            dependency.call is plugin_routes.bypass_user_context_func
            for dependency in route.dependant.dependencies
        )


@pytest.mark.asyncio
async def test_public_catalog_does_not_fake_empty_success():
    class Unavailable:
        async def list_plugins(self, *args, **kwargs):
            raise RuntimeError("registry unavailable")

    with pytest.raises(HTTPException) as exc_info:
        await plugin_routes.list_plugins_public(
            category=None,
            enabled_only=False,
            plugin_service=Unavailable(),
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Plugin catalog is unavailable"


def test_route_source_contains_no_literal_dev_user_bypass():
    source = (
        Path(__file__).parents[2]
        / "src"
        / "ai_karen_engine"
        / "api_routes"
        / "plugins"
        / "plugins.py"
    ).read_text(encoding="utf-8")
    assert 'user_id != "dev-user"' not in source
    assert "return empty response" not in source
