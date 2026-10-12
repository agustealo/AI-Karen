"""Contract tests for canonical plugin identity and retained metadata."""

import pytest

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest


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
