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
