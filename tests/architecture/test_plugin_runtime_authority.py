from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_CI = ROOT / ".github" / "workflows" / "plugin-ci.yml"
LEGACY_PLUGIN_DOCKERFILE = ROOT / "docker" / "Dockerfile.plugins"
LEGACY_PLUGIN_COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.plugins.yml"
CANONICAL_DOCKERFILE = ROOT / "Dockerfile"
CANONICAL_PRODUCTION_COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.prod.yml"
LEGACY_MOCK_PLUGIN_STORE = (
    ROOT / "src" / "ai_karen_engine" / "api_routes" / "plugins" / "store_mock.py"
)
LEGACY_PLUGIN_MANAGEMENT_ROUTE = (
    ROOT / "src" / "ai_karen_engine" / "api_routes" / "plugins" / "management.py"
)
LEGACY_INTELLIGENT_SEARCH_ROUTE = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "plugins"
    / "intelligent_search.py"
)
LEGACY_SHADOW_PLUGIN_STORE = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "extensions"
    / "platform"
    / "api_routes"
    / "plugin_store_routes.py"
)
CANONICAL_PLUGIN_STORE = (
    ROOT / "src" / "ai_karen_engine" / "api_routes" / "plugins" / "store.py"
)
PLUGIN_STORE_SERVICE = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "src"
    / "lib"
    / "PluginStoreService.ts"
)
PLUGIN_TYPES = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "src"
    / "types"
    / "plugin.ts"
)
SERVER_ROUTERS = ROOT / "src" / "ai_karen_engine" / "server" / "routers.py"


def test_plugins_do_not_own_a_parallel_application_runtime() -> None:
    assert not LEGACY_PLUGIN_DOCKERFILE.exists()
    assert not LEGACY_PLUGIN_COMPOSE.exists()

    dockerfile = CANONICAL_DOCKERFILE.read_text(encoding="utf-8")
    assert "ai_karen_engine.app:create_app" in dockerfile

    production = CANONICAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    assert "plugins-backend:" not in production
    assert "karen-plugins-db" not in production
    assert "karen-plugins-redis" not in production


def test_shadow_plugin_ingress_is_retired_and_canonical_store_is_wired() -> None:
    assert not LEGACY_MOCK_PLUGIN_STORE.exists()
    assert not LEGACY_PLUGIN_MANAGEMENT_ROUTE.exists()
    assert not LEGACY_INTELLIGENT_SEARCH_ROUTE.exists()
    assert not LEGACY_SHADOW_PLUGIN_STORE.exists()

    store = CANONICAL_PLUGIN_STORE.read_text(encoding="utf-8")
    routers = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert "MOCK_PLUGINS" not in store
    assert "MOCK_CATEGORIES" not in store
    assert "Depends(get_plugin_service)" in store
    assert "api_routes.plugins.management" not in routers
    assert "plugin_management_router" not in routers
    assert "intelligent_search_router" not in routers
    assert (
        "from ai_karen_engine.api_routes.plugins.store import router as plugin_store_router"
        in routers
    )
    assert 'RouterSpec(plugin_store_router, "/api", ("plugin-store",))' in routers


def test_plugin_store_is_thin_and_does_not_fabricate_capabilities() -> None:
    source = CANONICAL_PLUGIN_STORE.read_text(encoding="utf-8")

    forbidden = (
        "class PluginStore:",
        "async def get_db_session",
        "ExtensionDBModel",
        "MarketplaceDiscovery(None",
        "LifecycleManager(None",
        '"Rating captured"',
        'return []  # No updates available',
        '"current_version": "1.0.0"',
        '"latest_version": "1.1.0"',
    )
    for token in forbidden:
        assert token not in source

    assert "metadata_items = await plugin_service.list_plugins()" in source
    assert "await plugin_service.get_plugin_info(plugin_id)" in source
    assert "await plugin_service.enable_plugin(request.plugin_id)" in source
    assert "status.HTTP_501_NOT_IMPLEMENTED" in source
    assert "durable_plugin_rating_store_not_configured" in source
    assert "canonical_update_feed_not_configured" in source
    assert "_audit_plugin_event(" in source
    assert '"correlation_id": meta["correlation_id"]' in source


def test_plugin_store_frontend_displays_backend_truth_only() -> None:
    service = PLUGIN_STORE_SERVICE.read_text(encoding="utf-8")
    types = PLUGIN_TYPES.read_text(encoding="utf-8")

    assert "latest_version: plugin.version" not in service
    assert "min_karen_version: '1.0.0'" not in service
    assert "requirements: []" not in service
    assert "Default to 'available'" not in service
    assert "Unsupported plugin status from backend" in service
    assert "display_name: plugin.display_name ?? plugin.name" in service
    assert "update_available: response.update_available" in service
    assert "z.boolean().nullable().optional()" in types


def test_plugin_ci_proves_governed_plugin_surfaces_without_deploying_a_sidecar() -> None:
    source = PLUGIN_CI.read_text(encoding="utf-8")

    assert "tests/extensions/" in source
    assert "test_extension_lifecycle_authority.py" in source
    assert "test_extension_route_authority.py" in source
    assert "test_plugin_runtime_authority.py" in source

    forbidden = (
        "docker/build-push-action",
        "docker/login-action",
        "kubectl set image deployment/plugin-ecosystem",
        "Build Plugin Docker Images",
        "Deploy to Staging",
        "Deploy to Production",
        "migrate_plugins.py",
        "ghcr.io/karen-ai/plugin-ecosystem",
    )
    for token in forbidden:
        assert token not in source


def test_plugin_truth_surfaces_retrigger_plugin_ci() -> None:
    source = PLUGIN_CI.read_text(encoding="utf-8")

    required_paths = (
        "'src/ai_karen_engine/api_routes/plugins/**'",
        "'src/ai_karen_engine/extensions/platform/api_routes/plugin_store_routes.py'",
        "'src/ui_launchers/Karen-AI-Theme/src/lib/PluginStoreService.ts'",
        "'src/ui_launchers/Karen-AI-Theme/src/types/plugin.ts'",
        "'tests/architecture/test_plugin_runtime_authority.py'",
        "'docker/Dockerfile.plugins'",
        "'deploy/compose/docker-compose.plugins.yml'",
    )
    for path in required_paths:
        assert path in source

    assert "src/ai_karen_engine/api_routes/plugins/" in source
