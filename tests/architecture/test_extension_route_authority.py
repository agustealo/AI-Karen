from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app.py"
SERVER_ROUTERS = REPO_ROOT / "server" / "routers.py"
EXTENSION_ROUTES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "extensions"
    / "extensions.py"
)


def test_root_server_app_owns_no_plugins_listing_route() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    assert '@app.get("/plugins"' not in source
    assert "async def list_plugins" not in source
    assert "ExtensionRegistry()" not in source


def test_canonical_extension_routes_are_mounted() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")
    route_source = EXTENSION_ROUTES.read_text(encoding="utf-8")

    assert 'app.include_router(extensions_router, prefix="/api/extensions"' in router_source
    assert '@router.get("/"' in route_source
    assert '@router.get("/list"' in route_source


def test_plugin_management_has_separate_canonical_surface() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert 'plugin_management_router, prefix="/api/plugins"' in router_source
