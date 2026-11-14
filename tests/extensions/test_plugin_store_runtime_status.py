"""Regression tests for plugin-store runtime status projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.plugins import plugins as plugin_routes
from ai_karen_engine.auth.rbac_middleware import Permission

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


@pytest.mark.asyncio
async def test_statistics_count_running_plugins_not_disabled_installs() -> None:
    class Service:
        async def list_plugins(self):
            return [
                {"manifest": _manifest(), "status": state}
                for state in ("enabled", "active", "loaded", "disabled", "discovered")
            ]

    stats = await store.get_statistics_endpoint(plugin_service=Service())
    assert stats.total_plugins == 5
    assert stats.active_plugins == 3
    assert stats.total_downloads is None


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": "/api/store/install",
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
    })


@pytest.mark.asyncio
async def test_plugin_store_rejects_role_only_admin_without_management_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_events = []

    class DeniedRBAC:
        def has_permission(self, user, permission):
            assert permission is Permission.ADMIN_PLUGINS_MANAGE
            return False

        def audit_access_attempt(self, *args, **kwargs):
            access_events.append(kwargs)

    class Service:
        async def get_plugin_info(self, plugin_id):
            pytest.fail("Store must deny before inspecting or enabling a plugin")

    monkeypatch.setattr(plugin_routes, "get_rbac_manager", DeniedRBAC)

    with pytest.raises(HTTPException) as exc:
        await store.install_plugin_endpoint(
            http_request=_request(),
            request=store.PluginInstallRequest(plugin_id="alpha-plugin"),
            current_user={"user_id": "operator", "tenant_id": "tenant-a", "roles": ["admin"]},
            plugin_service=Service(),
        )

    assert exc.value.status_code == 403
    assert access_events[0]["granted"] is False
    assert access_events[0]["resource"] == "/api/store/install"


@pytest.mark.asyncio
async def test_plugin_store_allows_explicit_permission_grant_without_admin_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_events = []
    audit_events = []
    enabled_plugins = []

    class GrantedRBAC:
        def has_permission(self, user, permission):
            assert permission is Permission.ADMIN_PLUGINS_MANAGE
            return True

        def audit_access_attempt(self, *args, **kwargs):
            access_events.append(kwargs)

    class Service:
        async def get_plugin_info(self, plugin_id):
            assert plugin_id == "alpha-plugin"
            return {"manifest": _manifest(), "status": "disabled"}

        async def enable_plugin(self, plugin_id):
            enabled_plugins.append(plugin_id)
            return True

    monkeypatch.setattr(plugin_routes, "get_rbac_manager", GrantedRBAC)
    monkeypatch.setattr(
        store,
        "get_audit_logger",
        lambda: SimpleNamespace(log_audit_event=audit_events.append),
    )

    result = await store.install_plugin_endpoint(
        http_request=_request(),
        request=store.PluginInstallRequest(plugin_id="alpha-plugin"),
        current_user={"user_id": "operator", "tenant_id": "tenant-a", "roles": ["operator"]},
        plugin_service=Service(),
    )

    assert result["success"] is True
    assert result["operation"] == "enable_local_catalog_plugin"
    assert enabled_plugins == ["alpha-plugin"]
    assert access_events[0]["granted"] is True
    assert audit_events[0]["event_type"] == "plugin_install"


def test_invalid_runtime_plugin_is_not_presented_as_installable() -> None:
    payload = store._plugin_payload(
        {"manifest": _manifest(), "status": "error"}
    )
    assert payload["status"] == "incompatible"
    assert payload["runtime_status"] == "error"


@pytest.mark.asyncio
async def test_installed_only_catalog_filter_ignores_available_plugins_before_pagination() -> None:
    class Service:
        async def list_plugins(self):
            return [
                {"manifest": _manifest(), "status": state}
                for state in ("disabled", "discovered", "enabled", "error")
            ]

    first = await store.search_plugins_endpoint(
        http_request=_request(),
        request=store.PluginSearchRequest(installed_only=True, per_page=1, page=1),
        plugin_service=Service(),
    )
    second = await store.search_plugins_endpoint(
        http_request=_request(),
        request=store.PluginSearchRequest(installed_only=True, per_page=1, page=2),
        plugin_service=Service(),
    )

    assert first["total"] == 2
    assert first["total_pages"] == 2
    assert first["has_next"] is True
    assert second["total"] == 2
    assert second["has_next"] is False
    assert {first["plugins"][0]["runtime_status"], second["plugins"][0]["runtime_status"]} == {"enabled", "disabled"}
    assert all(item["status"] == "installed" for item in first["plugins"] + second["plugins"])
