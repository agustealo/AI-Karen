"""KOC-04A: channel admission remains host-owned and inactive until Gateway PR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryReceipt,
    ChannelDeliveryState,
    InboundChannelEvent,
)
from ai_karen_engine.extensions.contracts import (
    DataClassification,
    ExtensionLifecycleState,
    ExtensionRegistration,
    RiskClass,
    SideEffectLevel,
)
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.plugin_kernel import PluginKernel


def _channel_catalog():
    return {
        "name": "test-channel",
        "version": "1.0.0",
        "display_name": "Test Channel",
        "description": "Transport contract smoke",
        "author": "Karen",
        "license": "MIT",
        "category": "communication",
        "entrypoint": "handler:MainExtension",
        "permissions": {"network_access": ["provider.example"]},
        "capabilities": {
            "provides_webhooks": True,
            "communication_channel": {
                "version": "1.0.0",
                "transport": "example-transport",
                "ingress": ["webhook"],
                "inbound": ["text", "media"],
                "outbound": ["text"],
                "authentication": "hmac",
                "supports_delivery_receipts": True,
            },
        },
    }


def test_catalog_channel_manifest_projects_into_host_only_registry(tmp_path):
    declaration = ExtensionManifest.from_dict(_channel_catalog())
    kernel = PluginKernel(tmp_path)
    projected = kernel._project_runtime_manifest(declaration)

    assert [cap.id for cap in projected.capabilities] == ["communication_channel"]
    capability = projected.capabilities[0]
    assert capability.version == "1.0.0"
    assert capability.risk_class is RiskClass.HIGH
    assert capability.data_classification is DataClassification.CONFIDENTIAL
    assert capability.side_effect_level is SideEffectLevel.EXTERNAL
    assert capability.requires_credentials is True
    assert capability.requires_network is True
    assert capability.provides_webhooks is True
    assert capability.required_permissions == ["network_access", "network_access:provider.example"]
    assert projected.risk_class is RiskClass.HIGH
    assert projected.side_effect_level is SideEffectLevel.EXTERNAL
    assert projected.enabled_by_default is False
    assert projected.trust_tier.value == "untrusted"
    assert projected.metadata["communication_channel"]["transport"] == "example-transport"


@pytest.mark.asyncio
async def test_channel_registration_discoverable_but_cannot_activate(tmp_path):
    kernel = PluginKernel(tmp_path)
    manifest = kernel._project_runtime_manifest(
        ExtensionManifest.from_dict(_channel_catalog())
    )
    await kernel.runtime_registry.register(
        ExtensionRegistration(
            manifest=manifest, state=ExtensionLifecycleState.DISCOVERED
        )
    )
    candidates = kernel.runtime_registry.get_capability_candidates(
        "communication_channel", ">=1.0.0"
    )
    assert len(candidates) == 1
    assert candidates[0].manifest.name == "test-channel"

    with pytest.raises(ValueError, match="requires the governed Channel Gateway"):
        await kernel.enable("test-channel")
    assert kernel.runtime_registry.get("test-channel").state is ExtensionLifecycleState.REGISTERED


def test_ordinary_plugin_projection_is_unchanged(tmp_path):
    original = _channel_catalog()
    original["capabilities"] = {"provides_api": True}
    original["category"] = "productivity"
    declaration = ExtensionManifest.from_dict(original)
    projected = PluginKernel(tmp_path)._project_runtime_manifest(declaration)

    assert [cap.id for cap in projected.capabilities] == ["execute"]
    assert projected.capabilities[0].risk_class is RiskClass.LOW
    assert projected.enabled_by_default is True


@pytest.mark.parametrize("mutation", [
    {"authentication": "none"},
    {"ingress": ["webhook", "webhook"]},
    {"ingress": ["unsupported"]},
    {"outbound": []},
    {"version": "v1"},
    {"tenant_id": "attacker-controlled"},
])
def test_invalid_channel_declarations_fail_closed(mutation):
    values = _channel_catalog()
    values["capabilities"]["communication_channel"].update(mutation)
    with pytest.raises(ValidationError):
        ExtensionManifest.from_dict(values)


def test_channel_declared_category_cannot_fall_back_to_generic_execute():
    catalog = _channel_catalog()
    catalog["capabilities"] = {"communication_chanel": {"transport": "fake"}}
    with pytest.raises(ValueError, match="communication channel capability declaration required"):
        ExtensionManifest.from_dict(catalog)


def test_channel_manifest_rejects_unknown_outer_capability_fields():
    catalog = _channel_catalog()
    catalog["capabilities"]["execute_anything"] = True
    with pytest.raises(ValueError, match="Unknown communication channel capability fields"):
        ExtensionManifest.from_dict(catalog)


def test_untrusted_inbound_event_cannot_supply_karen_principal():
    base = {
        "connection_id": "connection-1",
        "external_event_id": "message-1",
        "external_sender_id": "sender-1",
        "external_conversation_id": "external-chat-1",
        "message_kind": "text",
        "text": "Hello",
    }
    assert InboundChannelEvent(**base).external_sender_id == "sender-1"
    with pytest.raises(ValidationError):
        InboundChannelEvent(**base, tenant_id="tenant-a", user_id="victim")


def test_connection_requires_host_scoped_tenant_and_credential_handle():
    with pytest.raises(ValidationError):
        ChannelConnection(
            connection_id="one", installation_id="adapter", tenant_id="",
            provider_account_id="bot", credential_handle="", revision=0,
        )


def test_receipts_cannot_claim_unrecognized_delivery_states():
    assert ChannelDeliveryReceipt(
        delivery_id="delivery-one", state=ChannelDeliveryState.UNKNOWN
    ).state is ChannelDeliveryState.UNKNOWN
    with pytest.raises(ValidationError):
        ChannelDeliveryReceipt(delivery_id="delivery-one", state="pretend-sent")


def test_schema_parity_covers_runtime_and_channel_catalog():
    jsonschema = pytest.importorskip("jsonschema")
    from ai_karen_engine import extensions

    root = Path(extensions.__file__).resolve().parents[1]
    schema = json.loads((root / "config" / "plugin_schema.json").read_text())
    jsonschema.Draft7Validator.check_schema(schema)

    catalog = _channel_catalog()
    jsonschema.validate(catalog, schema)
    runtime = PluginKernel(root / "extensions" / "plugins")._project_runtime_manifest(
        ExtensionManifest.from_dict(catalog)
    )
    jsonschema.validate(runtime.model_dump(mode="json"), schema)
    invalid = _channel_catalog()
    invalid["capabilities"]["communication_channel"]["authentication"] = "none"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
