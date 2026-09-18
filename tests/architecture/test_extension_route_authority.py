from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app.py"
SERVER_ROUTERS = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "routers.py"
EXTENSION_ROUTES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "extensions"
    / "extensions.py"
)
LEGACY_PLATFORM_API_ROUTES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "extensions"
    / "platform"
    / "api_routes"
)
LEGACY_MARKETPLACE_ROUTES = LEGACY_PLATFORM_API_ROUTES / "marketplace_routes.py"
LEGACY_PLUGIN_SETTINGS_ROUTES = LEGACY_PLATFORM_API_ROUTES / "plugin_settings_routes.py"


def test_root_server_app_owns_no_plugins_listing_route() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    assert '@app.get("/plugins"' not in source
    assert "async def list_plugins" not in source
    assert "ExtensionRegistry()" not in source


def test_canonical_extension_routes_are_mounted() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")
    route_source = EXTENSION_ROUTES.read_text(encoding="utf-8")

    assert 'RouterSpec(extensions_router, "/api/extensions", ("extensions",))' in router_source
    assert '@router.get("/"' in route_source
    assert '@router.get("/list"' in route_source


def test_plugin_management_has_separate_canonical_surface() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert (
        'RouterSpec(plugin_management_router, "/api/plugins", ("plugin-management",))'
        in router_source
    )
    assert 'RouterSpec(plugin_store_router, "/api", ("plugin-store",))' in router_source


def test_unmounted_shadow_extension_ingress_stays_retired() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert not LEGACY_MARKETPLACE_ROUTES.exists()
    assert not LEGACY_PLUGIN_SETTINGS_ROUTES.exists()
    assert "marketplace_routes" not in router_source
    assert "plugin_settings_routes" not in router_source


def test_only_governed_platform_route_is_mounted_from_legacy_namespace() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert (
        "from ai_karen_engine.extensions.platform.api_routes.ui_materialization_routes "
        "import ("
        in router_source
    )
    assert "ui_materialization_router" in router_source
