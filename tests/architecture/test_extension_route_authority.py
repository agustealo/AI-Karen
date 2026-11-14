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
PLUGIN_API_ROUTES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "plugins"
)
RETIRED_PLUGIN_MANAGEMENT_ROUTE = PLUGIN_API_ROUTES / "management.py"
PLATFORM_API_ROUTES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "extensions"
    / "platform"
    / "api_routes"
)
GOVERNED_UI_MATERIALIZATION_ROUTES = (
    PLATFORM_API_ROUTES / "ui_materialization_routes.py"
)
RETIRED_PLATFORM_ROUTES = (
    PLATFORM_API_ROUTES / "marketplace_routes.py",
    PLATFORM_API_ROUTES / "plugin_settings_routes.py",
    PLATFORM_API_ROUTES / "health_routes.py",
    PLATFORM_API_ROUTES / "prompt_routes.py",
    PLATFORM_API_ROUTES / "ui_materialization.py",
)
RETIRED_PLATFORM_ROUTE_MODULE_NAMES = (
    "marketplace_routes",
    "plugin_settings_routes",
    "health_routes",
    "prompt_routes",
    "ui_materialization import",
)


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


def test_shadow_plugin_management_route_stays_retired() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert not RETIRED_PLUGIN_MANAGEMENT_ROUTE.exists()
    assert "api_routes.plugins.management" not in router_source
    assert "plugin_management_router" not in router_source
    assert 'RouterSpec(plugin_router, "/api/plugins", ("plugins",))' in router_source
    assert 'RouterSpec(plugin_store_router, "/api", ("plugin-store",))' in router_source


def test_unmounted_shadow_extension_ingress_stays_retired() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    for retired_route in RETIRED_PLATFORM_ROUTES:
        assert not retired_route.exists()

    for module_name in RETIRED_PLATFORM_ROUTE_MODULE_NAMES:
        assert module_name not in router_source


def test_only_governed_platform_route_is_mounted_from_platform_namespace() -> None:
    router_source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert GOVERNED_UI_MATERIALIZATION_ROUTES.exists()
    assert (
        "from ai_karen_engine.extensions.platform.api_routes.ui_materialization_routes "
        "import ("
        in router_source
    )
    assert "ui_materialization_router" in router_source
    assert 'RouterSpec(ui_materialization_router, tags=("ui-materialization",))' in router_source


def test_plugin_settings_have_one_mounted_route_and_no_legacy_shadow_writer() -> None:
    api = EXTENSION_ROUTES.read_text(encoding="utf-8")
    router = SERVER_ROUTERS.read_text(encoding="utf-8")
    assert 'RouterSpec(extensions_router, "/api/extensions", ("extensions",))' in router
    assert api.index('@router.get("/settings")') < api.index('@router.get("/{extension_name}")')
    for method in ("get", "post", "delete"):
        assert f'@router.{method}("/{{extension_name}}/settings")' in api
    assert api.count("Depends(require_extension_mutation_access)") >= 8
    assert "plugin_service.write_plugin_settings(" in api
    assert "plugin_service.read_plugin_settings(" in api
    assert "plugin_service.list_plugin_settings(" in api
    assert "PluginSettingsRevisionConflict" in api
    assert "status_code=503, detail=\"Plugin settings persistence unavailable\"" in api
    assert "api_routes.extensions.platform" not in router
    assert not (PLATFORM_API_ROUTES / "plugin_settings_routes.py").exists()


def test_plugin_settings_workflow_proves_all_affected_owners() -> None:
    workflow = (REPO_ROOT / ".github/workflows/plugin-ci.yml").read_text(
        encoding="utf-8"
    )
    for path in (
        "src/ai_karen_engine/api_routes/extensions/extensions.py",
        "src/ai_karen_engine/services/plugin_service.py",
        "src/ai_karen_engine/services/plugin_settings_repository.py",
        "src/ui_launchers/Karen-AI-Theme/src/plugin_host/plugin-settings.tsx",
        "supabase/migrations/*plugin_settings*.sql",
    ):
        assert workflow.count(path) >= 2
    assert "tests/extensions/" in workflow
    assert "tests/architecture/test_extension_route_authority.py" in workflow
