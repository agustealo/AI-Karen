"""Regression tests for plugin-store runtime status projection."""

from __future__ import annotations

from ai_karen_engine.api_routes.plugins import store
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        name="alpha-plugin",
        version="1.0.0",
        display_name="Alpha Plugin",
        description="Plugin store status fixture",
        author="Kari",
        license="MIT",
        category="test",
        entrypoint="handler:MainExtension",
    )


def test_enabled_runtime_plugin_remains_installed_in_store_projection() -> None:
    payload = store._plugin_payload(
        {
            "manifest": _manifest(),
            "status": "enabled",
        }
    )

    assert payload["status"] == "installed"
    assert payload["runtime_status"] == "enabled"


def test_disabled_runtime_plugin_remains_installed_but_reports_disabled_truth() -> None:
    payload = store._plugin_payload(
        {
            "manifest": _manifest(),
            "status": "disabled",
        }
    )

    assert payload["status"] == "installed"
    assert payload["runtime_status"] == "disabled"


def test_discovered_runtime_plugin_is_available_not_installed() -> None:
    payload = store._plugin_payload(
        {
            "manifest": _manifest(),
            "status": "discovered",
        }
    )

    assert payload["status"] == "available"
    assert payload["runtime_status"] == "discovered"
