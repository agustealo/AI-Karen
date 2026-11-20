"""Contract tests for canonical plugin identity and retained metadata."""

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.platform.core.manager import ExtensionCoreManager
from ai_karen_engine.api_routes.extensions.extensions import ExtensionStatusAPI


def _manifest():
    return {
        "id": "time-query",
        "name": "time-query",
        "version": "0.2.0",
        "display_name": "Time Query",
        "description": "Time features",
        "purpose": "Shared app time authority",
        "author": "Kari Team",
        "license": "MIT",
        "category": "productivity",
        "entrypoint": "handler:MainExtension",
    }


def test_compatible_duplicate_manifest_id_is_validated_and_purpose_preserved(caplog):
    model = ExtensionManifest.from_dict(_manifest())
    assert model.name == "time-query"
    assert model.purpose == "Shared app time authority"
    assert "Stripped unknown manifest fields" not in caplog.text


def test_mismatched_manifest_id_fails_closed():
    data = _manifest()
    data["id"] = "different-extension"
    with pytest.raises(ValueError, match="id must match canonical name"):
        ExtensionManifest.from_dict(data)


def test_first_party_voice_capability_survives_extension_catalog_without_implying_ui():
    plugin = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins/pocket-tts/plugin_manifest.json"
    )
    manifest = ExtensionManifest.from_dict(json.loads(plugin.read_text(encoding="utf-8")))
    status = ExtensionCoreManager._status_from_record(
        {"manifest": manifest, "status": "enabled"}
    )
    payload = ExtensionStatusAPI.model_validate(status).model_dump()

    assert payload["capabilities"]["provides_ui"] is False
    assert payload["capabilities"]["voice_modality"] == {
        "version": "1.0.0",
        "modalities": ["tts"],
    }
    # This declaration is intentionally NOT a ready model or enabled playback.
    assert "ready" not in payload["capabilities"]["voice_modality"]
    assert "model_id" not in payload["capabilities"]["voice_modality"]


def test_non_voice_manifest_does_not_invent_voice_capability():
    manifest = ExtensionManifest.from_dict(_manifest())
    projected = ExtensionCoreManager._extension_capabilities(manifest)
    assert "voice_modality" not in projected


def test_canonical_generative_declaration_is_bounded_and_catalog_only():
    manifest_data = _manifest()
    manifest_data["capabilities"] = {
        "provides_ui": False,
        "generative_presentations": {
            "version": "1.0.0",
            "component_types": ["time.observation", "data.table"],
            "surfaces": ["chat", "workspace"],
            "interaction_mode": "read_only",
        },
    }
    manifest = ExtensionManifest.from_dict(manifest_data)
    result = ExtensionCoreManager._extension_capabilities(manifest)
    assert result["provides_ui"] is False
    assert result["generative_presentations"] == {
        "version": "1.0.0",
        "component_types": ["time.observation", "data.table"],
        "surfaces": ["chat", "workspace"],
        "interaction_mode": "read_only",
        "status": "declaration_only",
    }
    assert "generative_presentations" not in ExtensionCoreManager._extension_capabilities(
        ExtensionManifest.from_dict(_manifest())
    )


@pytest.mark.parametrize("declaration", [
    {"component_types": ["arbitrary.html"]},
    {"component_types": ["chart.line"]},
    {"component_types": ["data.table", "data.table"]},
    {"component_types": []},
    {"component_types": ["data.table"], "surfaces": ["untrusted_dom"]},
    {"component_types": ["data.table"], "surfaces": ["chat", "chat"]},
    {"component_types": ["data.table"], "interaction_mode": "execute"},
    {"component_types": ["data.table"], "javascript": "alert(1)"},
    {"component_types": ["data.table"], "version": "not-semver"},
])
def test_manifest_rejects_untrusted_generative_renderer_and_action_contract(declaration):
    manifest_data = _manifest()
    manifest_data["capabilities"] = {"generative_presentations": declaration}
    with pytest.raises(ValueError):
        ExtensionManifest.from_dict(manifest_data)


def test_generative_declaration_survives_manifest_roundtrip():
    manifest_data = _manifest()
    manifest_data["capabilities"] = {
        "generative_presentations": {
            "component_types": ["search.results"],
        },
    }
    parsed = ExtensionManifest.from_dict(manifest_data)
    restored = ExtensionManifest.model_validate(parsed.model_dump())
    assert restored.capabilities.generative_presentations is not None
    assert restored.capabilities.generative_presentations.component_types == ["search.results"]
    assert restored.capabilities.generative_presentations.surfaces == ["chat"]
