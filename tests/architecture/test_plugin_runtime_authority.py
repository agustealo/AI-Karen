from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_CI = ROOT / ".github" / "workflows" / "plugin-ci.yml"
LEGACY_PLUGIN_DOCKERFILE = ROOT / "docker" / "Dockerfile.plugins"
LEGACY_PLUGIN_COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.plugins.yml"
CANONICAL_DOCKERFILE = ROOT / "Dockerfile"
CANONICAL_PRODUCTION_COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.prod.yml"
LEGACY_MOCK_PLUGIN_STORE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "plugins" / "store_mock.py"
CANONICAL_PLUGIN_STORE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "plugins" / "store.py"
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


def test_mock_plugin_store_is_retired_and_canonical_store_is_wired() -> None:
    assert not LEGACY_MOCK_PLUGIN_STORE.exists()

    store = CANONICAL_PLUGIN_STORE.read_text(encoding="utf-8")
    routers = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert "MOCK_PLUGINS" not in store
    assert "MOCK_CATEGORIES" not in store
    assert "MOCK_PLUGINS" not in store
    assert "from ai_karen_engine.api_routes.plugins.store import router as plugin_store_router" in routers
    assert 'RouterSpec(plugin_store_router, "/api", ("plugin-store",))' in routers


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


def test_reintroducing_retired_plugin_runtime_artifacts_retriggers_plugin_ci() -> None:
    source = PLUGIN_CI.read_text(encoding="utf-8")

    assert "'docker/Dockerfile.plugins'" in source
    assert "'deploy/compose/docker-compose.plugins.yml'" in source


def test_plugin_lifecycle_authority_uses_canonical_manifest_and_async_db_dependency() -> None:
    lifecycle = (
        ROOT
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
        / "plugin_lifecycle_manager.py"
    ).read_text(encoding="utf-8")
    management = (
        ROOT
        / "src"
        / "ai_karen_engine"
        / "api_routes"
        / "plugins"
        / "management.py"
    ).read_text(encoding="utf-8")

    assert 'plugin_path / "plugin_manifest.json"' in lifecycle
    assert 'plugin_path / "manifest.json"' not in lifecycle
    assert "registry.load_extension" not in lifecycle
    assert "registry.unload_extension" not in lifecycle
    assert "get_extension_core_manager().load_extension" in lifecycle
    assert "get_extension_core_manager().unload_extension" in lifecycle
    assert "_PLUGIN_OPERATION_LOCK" in lifecycle
    assert "get_async_db_session_dependency" in management
    assert "await get_db_session()" not in management
    assert "Permission.ADMIN_PLUGINS_MANAGE" in management
