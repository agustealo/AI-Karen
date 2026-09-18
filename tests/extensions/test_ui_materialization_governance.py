from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.extensions.platform.api_routes import (
    ui_materialization_routes as ui_routes,
)
from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
    UIMaterializationPipeline,
)


class _EmptyRegistry:
    async def list_all_extensions(self):
        return []

    def list_extensions(self):
        return []

    def get_metadata(self, plugin_id: str):
        return None


class _Registry:
    def __init__(self, plugin, metadata):
        self.plugin = plugin
        self.metadata = metadata

    async def list_all_extensions(self):
        return [self.plugin]

    def list_extensions(self):
        return [self.plugin]

    def get_metadata(self, plugin_id: str):
        return self.metadata if plugin_id == self.plugin.name else None


class _RecordingRBAC:
    def __init__(self, granted: bool):
        self.granted = granted
        self.permission = None
        self.audit = None

    def has_permission(self, user, permission):
        self.permission = permission
        return self.granted

    def audit_access_attempt(
        self,
        user_data,
        permission,
        resource,
        granted,
        request=None,
        additional_context=None,
    ):
        self.audit = {
            "user": user_data,
            "permission": permission,
            "resource": resource,
            "granted": granted,
            "request": request,
            "additional_context": additional_context or {},
        }


class _RecordingAuditLogger:
    def __init__(self):
        self.events = []

    def log_audit_event(self, event):
        self.events.append(event)


def _pipeline(tmp_path: Path) -> UIMaterializationPipeline:
    return UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin_repo"),
    )


def _request(path: str = "/api/ui-materialization/materialize") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [
                (b"x-request-id", b"request-123"),
                (b"x-correlation-id", b"correlation-456"),
                (b"user-agent", b"pytest"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.asyncio
async def test_registry_unavailable_does_not_fallback_to_filesystem(tmp_path):
    plugin_dir = tmp_path / "extensions" / "rogue-plugin"
    ui_dir = plugin_dir / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "PluginPage.tsx").write_text(
        "export default function Page() {}", encoding="utf-8"
    )
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "rogue-plugin",
                "version": "9.9.9",
                "capabilities": {"provides_ui": True},
                "ui": {"source_path": "ui", "entry_file": "PluginPage.tsx"},
            }
        ),
        encoding="utf-8",
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _EmptyRegistry()

    assert await pipeline.discover_ui_plugins() == []


@pytest.mark.asyncio
async def test_invalid_registry_metadata_cannot_materialize_ui(tmp_path):
    plugin_dir = tmp_path / "extensions" / "weather-query"
    plugin_dir.mkdir(parents=True)
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "weather-query",
                "version": "1.0.0",
                "ui": {"source_path": "ui", "entry_file": "PluginPage.tsx"},
            }
        ),
        encoding="utf-8",
    )

    plugin = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="1.0.0",
        status=SimpleNamespace(value="active"),
        capabilities={"provides_ui": True},
    )
    metadata = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="1.0.0",
        category="information",
        capabilities={"provides_ui": True},
        directory=plugin_dir,
        manifest_path=manifest_path,
        is_valid=False,
        validation_errors=["invalid manifest"],
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _Registry(plugin, metadata)

    assert await pipeline.discover_ui_plugins() == []


@pytest.mark.asyncio
async def test_valid_registry_metadata_is_the_only_operational_truth(tmp_path):
    plugin_dir = tmp_path / "extensions" / "weather-query"
    ui_dir = plugin_dir / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "WeatherPage.tsx").write_text(
        "export default function WeatherPage() {}",
        encoding="utf-8",
    )
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "weather-query",
                "version": "2.3.0",
                "capabilities": {"provides_ui": True},
                "ui": {
                    "source_path": "ui",
                    "entry_file": "WeatherPage.tsx",
                    "menu": [{"placement": "tools"}],
                },
            }
        ),
        encoding="utf-8",
    )

    plugin = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="2.3.0",
        status=SimpleNamespace(value="inactive"),
        capabilities={"provides_ui": True},
    )
    metadata = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="2.3.0",
        category="information",
        capabilities={"provides_ui": True},
        directory=plugin_dir,
        manifest_path=manifest_path,
        is_valid=True,
        validation_errors=[],
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _Registry(plugin, metadata)

    discovered = await pipeline.discover_ui_plugins()

    assert len(discovered) == 1
    item = discovered[0]
    assert item["plugin_id"] == "weather-query"
    assert item["version"] == "2.3.0"
    assert item["status"] == "inactive"
    assert item["category"] == "information"
    assert item["registry_validated"] is True
    assert item["capabilities"] == {"provides_ui": True}
    assert item["has_component"] is True
    assert item["component_path"].endswith("WeatherPage.tsx")


@pytest.mark.asyncio
async def test_ui_mutation_access_denies_without_plugin_manage_permission(monkeypatch):
    rbac = _RecordingRBAC(granted=False)
    monkeypatch.setattr(ui_routes, "get_rbac_manager", lambda: rbac)
    request = _request()
    user = {
        "user_id": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["user"],
    }

    with pytest.raises(HTTPException) as exc_info:
        await ui_routes._require_ui_mutation_access(request, user)

    assert exc_info.value.status_code == 403
    assert rbac.permission is Permission.ADMIN_PLUGINS_MANAGE
    assert rbac.audit is not None
    assert rbac.audit["permission"] is Permission.ADMIN_PLUGINS_MANAGE
    assert rbac.audit["granted"] is False
    assert rbac.audit["user"]["tenant_id"] == "tenant-a"
    assert rbac.audit["additional_context"] == {
        "action": "manage_ui_artifacts",
        "request_id": "request-123",
        "correlation_id": "correlation-456",
    }


@pytest.mark.asyncio
async def test_ui_mutation_access_allows_canonical_plugin_manager(monkeypatch):
    rbac = _RecordingRBAC(granted=True)
    monkeypatch.setattr(ui_routes, "get_rbac_manager", lambda: rbac)
    request = _request("/api/ui-materialization/cleanup")
    user = {
        "user_id": "admin-1",
        "tenant_id": "tenant-a",
        "roles": ["admin"],
    }

    resolved = await ui_routes._require_ui_mutation_access(request, user)

    assert resolved is user
    assert rbac.permission is Permission.ADMIN_PLUGINS_MANAGE
    assert rbac.audit is not None
    assert rbac.audit["granted"] is True
    assert rbac.audit["resource"] == "/api/ui-materialization/cleanup"


def test_ui_mutation_audit_preserves_tenant_and_correlation_context(monkeypatch):
    audit_logger = _RecordingAuditLogger()
    monkeypatch.setattr(ui_routes, "get_audit_logger", lambda: audit_logger)
    request = _request()
    user = {
        "user_id": "admin-1",
        "tenant_id": "tenant-a",
        "roles": ["admin"],
    }

    ui_routes._audit_ui_operation(
        request=request,
        current_user=user,
        action="materialize_all_ui_artifacts",
        outcome="attempt",
        details={"plugin_id": "weather-query"},
    )

    assert len(audit_logger.events) == 1
    event = audit_logger.events[0]
    assert event["event_type"] == "ui_materialization_mutation"
    assert event["user_id"] == "admin-1"
    assert event["tenant_id"] == "tenant-a"
    assert event["correlation_id"] == "correlation-456"
    assert event["metadata"] == {
        "action": "materialize_all_ui_artifacts",
        "outcome": "attempt",
        "request_id": "request-123",
        "plugin_id": "weather-query",
    }


def test_only_state_changing_ui_routes_require_plugin_manage_permission():
    routes = {route.path: route for route in ui_routes.router.routes}
    mutation_paths = {
        "/api/ui-materialization/materialize",
        "/api/ui-materialization/materialize/{plugin_id}",
        "/api/ui-materialization/install/{plugin_id}",
        "/api/ui-materialization/cleanup",
    }
    observational_paths = {
        "/api/ui-materialization/status",
        "/api/ui-materialization/discover",
        "/api/ui-materialization/installed",
        "/api/ui-materialization/import-map",
        "/api/ui-materialization/plugin/{plugin_id}",
        "/api/ui-materialization/icons/{plugin_id}",
    }

    for path in mutation_paths:
        assert path in routes
        assert any(
            dependency.call is ui_routes._require_ui_mutation_access
            for dependency in routes[path].dependant.dependencies
        )

    for path in observational_paths:
        assert path in routes
        assert all(
            dependency.call is not ui_routes._require_ui_mutation_access
            for dependency in routes[path].dependant.dependencies
        )


def test_pipeline_contains_no_filesystem_authority_fallback():
    source = (
        Path(__file__).parents[2]
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
        / "registry"
        / "ui_materialization.py"
    )
    text = source.read_text(encoding="utf-8")

    forbidden = (
        "_discover_plugins_filesystem",
        '"status": "active"',
        '"version", "1.0.0"',
        "Assume active",
    )
    for token in forbidden:
        assert token not in text
