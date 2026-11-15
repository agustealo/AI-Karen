"""Persistent plugin configuration never becomes an action-input contract."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services.plugin_service import PluginService


def _manifest(*, configuration=True, execution_input=None):
    details = {
        "name": "configuration-boundary",
        "version": "1.0.0",
        "display_name": "Invocation boundary",
        "description": "Separate action data from persistent credentials",
        "author": "Test",
        "license": "MIT",
        "category": "test",
        "entrypoint": "handler:MainExtension",
    }
    if configuration:
        details["config_schema"] = {
            "type": "object",
            "properties": {
                "region": {"type": "string", "enum": ["east", "west"]},
                "api_key": {"type": "string", "writeOnly": True},
            },
            "required": ["region", "api_key"],
            "additional_properties": False,
        }
    if execution_input is not None:
        details["execution_input_schema"] = execution_input
    return ExtensionManifest.from_dict(details)


def _service(manifest):
    service = PluginService()
    service._get_kernel = lambda: SimpleNamespace(
        get_record=lambda _: {"manifest": manifest},
    )
    return service


def test_config_schema_without_invocation_schema_never_authorizes_secret_or_config_args():
    manifest = _manifest()
    projected = PluginKernel.execution_input_schema(manifest)
    assert projected == {
        "type": "object", "properties": {}, "required": [],
        "additionalProperties": False,
    }
    service = _service(manifest)
    assert service._validate_parameter_contract("configuration-boundary", {}) == {}
    for forbidden in ({"api_key": "secret"}, {"region": "east"}, {"query": "hi"}):
        with pytest.raises(ValueError):
            service._validate_parameter_contract("configuration-boundary", forbidden)


def test_canonical_runtime_projection_uses_only_execution_contract(tmp_path: Path):
    manifest = _manifest(
        execution_input={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
            },
            "required": ["query"],
            "additional_properties": False,
        }
    )
    kernel = PluginKernel(tmp_path)
    runtime = kernel._project_runtime_manifest(manifest)
    assert runtime.input_schema["required"] == ["query"]
    assert runtime.capabilities[0].input_schema["required"] == ["query"]
    assert "api_key" not in str(runtime.input_schema)
    assert "region" not in str(runtime.input_schema)

    service = _service(manifest)
    assert service._validate_parameter_contract(
        "configuration-boundary", {"query": "hello"}
    ) == {"query": "hello"}
    for invalid in (
        {}, {"query": ""}, {"region": "east"},
        {"api_key": "never-accept"}, {"query": "hi", "api_key": "secret"},
    ):
        with pytest.raises(ValueError):
            service._validate_parameter_contract("configuration-boundary", invalid)


@pytest.mark.parametrize("action_schema", [
    {
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "additional_properties": False,
    },
    {
        "type": "object",
        "properties": {"region": {"type": "string"}},
        "additional_properties": False,
    },
    {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "additional_properties": True,
    },
])
def test_manifest_rejects_configuration_input_overlap_or_open_action_schema(action_schema):
    with pytest.raises(ValidationError, match=(
        "must not reuse persistent configuration|closed execution input"
    )):
        _manifest(execution_input=action_schema)


def test_legacy_plugin_without_config_preserves_generic_parameter_ingress():
    manifest = _manifest(configuration=False)
    assert PluginKernel.execution_input_schema(manifest) == {}
    assert _service(manifest)._validate_parameter_contract(
        "configuration-boundary", {"query": "hello"}
    ) == {"query": "hello"}


def test_declared_execution_schema_still_works_without_config():
    manifest = _manifest(
        configuration=False,
        execution_input={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additional_properties": False,
        },
    )
    assert _service(manifest)._validate_parameter_contract(
        "configuration-boundary", {"query": "hi"}
    ) == {"query": "hi"}
    with pytest.raises(ValueError):
        _service(manifest)._validate_parameter_contract(
            "configuration-boundary", {"secret": "unrecognized"}
        )


def test_input_contract_does_not_change_settings_manifest_or_required_fields():
    manifest = _manifest(execution_input={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additional_properties": False,
    })
    assert manifest.config_schema is not None
    assert manifest.config_schema.required == ["region", "api_key"]
    assert manifest.execution_input_schema is not None
    assert manifest.execution_input_schema.required == ["query"]
    runtime = PluginKernel.execution_input_schema(manifest)
    assert set(runtime["properties"]) == {"query"}


@pytest.fixture
def runtime_readiness_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tenant-specific settings and Vault status; never a fabricated secret value."""
    from ai_karen_engine.services import plugin_service as plugin_service_module

    plugin_id = "configuration-boundary"
    package = tmp_path / plugin_id
    package.mkdir()
    manifest = _manifest()
    record = {
        "manifest": manifest,
        "path": package,
        "status": "enabled",
        "dependencies_resolved": True,
        "compatibility_checked": True,
        "error_message": None,
    }
    state = {
        "record": record,
        "uploaded": False,
        "persisted": {"settings": {"region": "west"}, "revision": 2},
        "credentials": {"api_key": {"status": "active", "revision": 3}},
        "reads": [],
    }
    service = PluginService()
    service._resolve_root = lambda: tmp_path
    service._get_kernel = lambda: SimpleNamespace(
        get_record=lambda _: state["record"],
        _is_uploaded_plugin=lambda _: state["uploaded"],
    )

    async def read_settings(tenant, name):
        state["reads"].append(("settings", tenant, name))
        if isinstance(state["persisted"], Exception):
            raise state["persisted"]
        return state["persisted"]

    async def read_credentials(*, tenant_id, plugin_id, field_keys):
        state["reads"].append(("vault_status", str(tenant_id), plugin_id))
        assert field_keys == frozenset({"api_key"})
        if isinstance(state["credentials"], Exception):
            raise state["credentials"]
        return state["credentials"]

    service._settings_repository = SimpleNamespace(get=read_settings)
    monkeypatch.setattr(
        plugin_service_module, "get_credential_vault_service",
        lambda: SimpleNamespace(list_plugin_credential_status=read_credentials),
    )
    return service, state


@pytest.mark.asyncio
async def test_configured_plugin_only_passes_after_tenant_settings_and_vault_status(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    tenant = "00000000-0000-4000-8000-000000000001"
    assert await service._execution_configuration_readiness(
        "configuration-boundary", tenant
    ) is None
    assert state["reads"] == [
        ("settings", tenant, "configuration-boundary"),
        ("vault_status", tenant, "configuration-boundary"),
    ]


@pytest.mark.asyncio
async def test_configured_plugin_rejects_unsaved_or_invalid_tenant_settings(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    tenant = "00000000-0000-4000-8000-000000000001"
    state["persisted"] = {"settings": {}, "revision": 0}
    assert await service._execution_configuration_readiness(
        "configuration-boundary", tenant
    ) == "plugin_configuration_missing"
    assert not any(read[0] == "vault_status" for read in state["reads"])

    state["persisted"] = {"settings": {"region": "unlisted"}, "revision": 2}
    assert await service._execution_configuration_readiness(
        "configuration-boundary", tenant
    ) == "plugin_configuration_invalid"


@pytest.mark.asyncio
async def test_configured_plugin_rejects_revoked_or_cross_tenant_credentials(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    tenant = "00000000-0000-4000-8000-000000000001"
    state["credentials"] = {"api_key": {"status": "revoked", "revision": 4}}
    assert await service._execution_configuration_readiness(
        "configuration-boundary", tenant
    ) == "plugin_credentials_unavailable"
    state["credentials"] = {"api_key": {"status": "missing", "revision": 0}}
    assert await service._execution_configuration_readiness(
        "configuration-boundary", "00000000-0000-4000-8000-000000000002"
    ) == "plugin_credentials_unavailable"


@pytest.mark.asyncio
async def test_unverified_plugin_installation_never_touches_tenant_stores(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    state["uploaded"] = True
    assert await service._execution_configuration_readiness(
        "configuration-boundary", "00000000-0000-4000-8000-000000000001"
    ) == "plugin_installation_unverified"
    assert state["reads"] == []
    state["uploaded"] = False
    state["record"]["dependencies_resolved"] = False
    assert await service._execution_configuration_readiness(
        "configuration-boundary", "00000000-0000-4000-8000-000000000001"
    ) == "plugin_installation_unverified"


@pytest.mark.asyncio
async def test_configuration_store_outage_fails_closed_without_vault_release(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    state["persisted"] = RuntimeError("Database unavailable")
    assert await service._execution_configuration_readiness(
        "configuration-boundary", "00000000-0000-4000-8000-000000000001"
    ) == "plugin_configuration_unavailable"
    assert [item[0] for item in state["reads"]] == ["settings"]


@pytest.mark.asyncio
async def test_configuration_free_plugin_does_not_acquire_new_tenant_dependencies(
    runtime_readiness_case,
):
    service, state = runtime_readiness_case
    state["record"]["manifest"] = _manifest(configuration=False)
    assert await service._execution_configuration_readiness(
        "configuration-boundary", "00000000-0000-4000-8000-000000000001"
    ) is None
    assert state["reads"] == []
