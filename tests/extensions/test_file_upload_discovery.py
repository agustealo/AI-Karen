"""File Upload's catalog and admission-only destination contract."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.runtime.policy import PolicyEvaluationRequest, RuntimePolicyEnforcer
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services.plugin_service import PluginService

PLUGIN = Path(__file__).resolve().parents[2] / "src/ai_karen_engine/extensions/plugins/file-upload"
CAPABILITIES = ["file-upload", "file_upload.discover", "data:read", "artifact:create_own"]


def test_catalog_manifest_is_disabled_admission_only():
    data = json.loads((PLUGIN / "plugin_manifest.json").read_text())
    manifest = ExtensionManifest.from_dict(data)
    assert manifest.name == "file-upload"
    assert not manifest.rbac.default_enabled
    assert not manifest.capabilities.provides_ui
    assert not manifest.capabilities.provides_api
    assert not manifest.permissions.user_data_write
    assert not manifest.permissions.network_access
    assert manifest.execution_input_schema.required == ["operation"]
    assert not manifest.execution_input_schema.additional_properties


@pytest.mark.asyncio
@pytest.mark.parametrize("caps,permissions", [
    (["file-upload"], ["data:read", "artifact:create_own"]),
    (CAPABILITIES, ["data:read"]),
    (CAPABILITIES + ["file_upload.commit"], ["data:read", "artifact:create_own"]),
    (["file-upload", "file_upload.transfer", "data:read", "artifact:create_own"],
     ["data:read", "artifact:create_own"]),
])
async def test_policy_denies_missing_entitlement_or_unregistered_action(caps, permissions):
    decision = await RuntimePolicyEnforcer().evaluate(PolicyEvaluationRequest(
        user_id=str(uuid4()), tenant_id=str(uuid4()), roles=["user"],
        permissions=permissions, action="plugin_execution",
        plugin_id="file-upload", requested_capabilities=caps,
    ))
    assert not decision.allowed


@pytest.fixture
def discovery(monkeypatch):
    from ai_karen_engine.auth import rbac_middleware

    principal = SimpleNamespace(roles=["user"])
    context = SimpleNamespace(
        tenant_id=str(uuid4()), user_id=str(uuid4()), session_id=str(uuid4()),
        request_id="request", correlation_id="trace",
        require_authenticated_user=Mock(return_value=principal),
        revalidate_runtime_artifact_write_session=AsyncMock(),
    )
    manager = SimpleNamespace(get_user_permissions=Mock(return_value={
        Permission.DATA_READ, Permission.ARTIFACT_CREATE_OWN,
    }))
    monkeypatch.setattr(rbac_middleware, "get_rbac_manager", lambda: manager)
    kernel = SimpleNamespace(
        get_record=Mock(return_value={"status": "enabled", "dependencies_resolved": True}),
        admit=AsyncMock(return_value=SimpleNamespace(status="admitted")),
    )
    service = PluginService()
    service.kernel = kernel
    service.initialized = True
    return service, context, kernel


@pytest.mark.asyncio
async def test_disabled_extension_discloses_no_destinations(discovery):
    service, context, kernel = discovery
    kernel.get_record.return_value = {"status": "disabled", "dependencies_resolved": True}
    assert await service.discover_owner_upload_destinations(context) == []
    kernel.admit.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_is_admitted_but_never_advertises_transfer(discovery):
    service, context, kernel = discovery
    result = await service.discover_owner_upload_destinations(context)
    assert len(result) == 1
    assert result[0]["recipes"] == ["store_only"]
    assert result[0]["transfer_available"] is False
    assert context.revalidate_runtime_artifact_write_session.await_count == 2
    request = kernel.admit.await_args.args[0]
    assert request.plugin_id == "file-upload"
    assert request.payload == {"operation": "discover"}
    assert set(request.authorized_plan.allowed_capabilities) == set(CAPABILITIES)


@pytest.mark.asyncio
async def test_kernel_denial_never_returns_destination(discovery):
    service, context, kernel = discovery
    kernel.admit.return_value = SimpleNamespace(status="failed")
    with pytest.raises(PermissionError):
        await service.discover_owner_upload_destinations(context)


@pytest.mark.asyncio
async def test_lifecycle_changes_during_admission_hide_destination(discovery):
    service, context, kernel = discovery
    kernel.get_record.side_effect = [
        {"status": "enabled", "dependencies_resolved": True},
        {"status": "disabled", "dependencies_resolved": True},
    ]
    assert await service.discover_owner_upload_destinations(context) == []


@pytest.mark.asyncio
async def test_transfer_rejects_unknown_destination_before_kernel(discovery):
    service, context, kernel = discovery
    with pytest.raises(PermissionError):
        await service.transfer_owner_text(
            context, destination="external", recipe="store_only",
            filename="notes.txt", data=b"hello", idempotency_key=str(uuid4()),
        )
    kernel.get_record.assert_not_called()


@pytest.mark.asyncio
async def test_transfer_delegates_under_active_host_scope(discovery, monkeypatch):
    from contextlib import asynccontextmanager
    from ai_karen_engine.database import factory
    from ai_karen_engine.core.runtime.owner_text_upload import OwnerTextUploadService

    service, context, kernel = discovery
    active = {}
    kernel.active_executions = lambda: dict(active)

    @asynccontextmanager
    async def admitted(request):
        assert request.payload == {"operation": "transfer"}
        assert "file_upload.transfer" in request.authorized_plan.allowed_capabilities
        active[request.context.request_id] = request.plugin_id
        try:
            yield SimpleNamespace(status="admitted")
        finally:
            active.clear()

    kernel.admitted_host_operation = admitted
    from ai_karen_engine.persistence.repositories import plugin_lifecycle_repository as ledger_module
    observation = object()
    kernel.observe_active_host_lifecycle = AsyncMock(return_value=observation)
    durable = AsyncMock()

    @asynccontextmanager
    async def hold_enabled_execution(*, observation):
        assert observation is kernel.observe_active_host_lifecycle.return_value
        assert active == {context.request_id: "file-upload"}
        yield durable

    monkeypatch.setattr(ledger_module, "PluginLifecycleLedger", lambda: SimpleNamespace(
        hold_enabled_execution=hold_enabled_execution,
    ))
    runtime = OwnerTextUploadService(sessions=Mock(), artifacts=Mock())
    expected = object()

    async def save(context_arg, **kwargs):
        assert context_arg is context
        assert active == {context.request_id: "file-upload"}
        await kwargs["authorize_transfer"]()
        assert kwargs["data"] == b"hello"
        return expected

    runtime.save = AsyncMock(side_effect=save)
    monkeypatch.setattr(factory, "get_database_service_factory", lambda: SimpleNamespace(
        get_service=lambda name: runtime if name == "owner_text_upload" else None,
    ))
    assert await service.transfer_owner_text(
        context, destination="explorer", recipe="store_only",
        filename="notes.txt", data=b"hello", idempotency_key=str(uuid4()),
    ) is expected
    assert not active
    assert durable.await_count == 3
    assert kernel.observe_active_host_lifecycle.await_count == 4

    # A lost durable fence cannot reach the runtime.
    runtime.save.reset_mock()
    durable.side_effect = RuntimeError("fence unavailable")
    with pytest.raises(RuntimeError, match="fence unavailable"):
        await service.transfer_owner_text(
            context, destination="explorer", recipe="store_only",
            filename="notes.txt", data=b"hello", idempotency_key=str(uuid4()),
        )
    runtime.save.assert_not_awaited()
    assert not active
