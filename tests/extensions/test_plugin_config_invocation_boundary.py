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
