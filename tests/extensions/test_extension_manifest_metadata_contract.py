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
