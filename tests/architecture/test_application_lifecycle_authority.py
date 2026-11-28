from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
APPLICATION_RUNTIME = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "application_runtime.py"
STARTUP = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
LEGACY_SERVER_APP = REPO_ROOT / "server" / "app.py"


def test_canonical_application_owns_lifespan_selection() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "create_application_lifespan" in source
    assert "lifespan=create_application_lifespan(settings)" in source
    assert "from server import app as legacy_app" not in source


def test_application_runtime_owns_runtime_shutdown_before_service_shutdown() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert "await shutdown_application_runtime(app)" in source
    assert "await on_shutdown(app)" in source
    assert source.index("await shutdown_application_runtime(app)") < source.index(
        "await on_shutdown(app)"
    )


def test_database_shutdown_is_owned_by_canonical_application_runtime() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert "get_database_config(settings)" in source
    assert "await database_config.cleanup()" in source
    assert source.index("await database_config.cleanup()") < source.index(
        "await on_shutdown(app)"
    )


def test_legacy_server_app_has_no_lifecycle_or_shutdown_authority() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    assert "@app.on_event" not in source
    assert "async def _shutdown_database" not in source
    assert "db_config.cleanup" not in source
    assert "create_lifespan" not in source
    assert "FastAPI(" not in source


def test_canonical_entrypoint_does_not_create_database_shutdown_authority() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "get_database_config" not in source
    assert "db_config.cleanup" not in source


def test_canonical_startup_does_not_run_legacy_ai_startup_manager() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    start = source.index("async def on_startup(")
    end = source.index("\n\nasync def on_shutdown(", start)
    startup_source = source[start:end]

    assert "await init_database(app)" in startup_source
    assert "await init_crawl4ai_service(app)" in startup_source
    assert "init_security(settings)" in startup_source
    assert "init_ai_services(" not in startup_source
    assert "optimized_startup_sequence" not in startup_source
    assert "MinimalStartupMode" not in startup_source


def test_recovery_hold_precedes_application_and_database_acquisition() -> None:
    app = APP_ENTRYPOINT.read_text(encoding="utf-8")
    lifecycle = APPLICATION_RUNTIME.read_text(encoding="utf-8")
    engine = (REPO_ROOT / "src/ai_karen_engine/persistence/postgres/engine.py").read_text(encoding="utf-8")
    factory = app.split("def create_app()", 1)[1]
    assert factory.index("require_database_recovery_not_held()") < factory.index("wire_routers(app, settings)")
    router_import = "from ai_karen_engine.server.routers import wire_routers"
    assert router_import not in app.split("def create_app()", 1)[0]
    assert factory.index("require_database_recovery_not_held()") < factory.index("_validate_environment()") < factory.index(router_import)
    security_import = "from ai_karen_engine.server.security import validate_environment_security"
    assert security_import not in app.split("def _validate_environment()", 1)[0]
    assert security_import in app.split("def _validate_environment()", 1)[1].split("def _register_canonical_routes", 1)[0]
    lifespan = lifecycle.split("async def lifespan(app: FastAPI):", 1)[1]
    assert lifespan.index("require_database_recovery_not_held()") < lifespan.index("await on_startup(settings, app)")
    assert 'event.listen(self._engine, "checkout", _guard_recovery_checkout)' in engine
    assert 'event.listen(self._async_engine.sync_engine, "checkout", _guard_recovery_checkout)' in engine


def test_recovery_hold_is_forwarded_through_production_compose_environment() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    api = compose.split("\n  api:", 1)[1].split("\n  web:", 1)[0]
    assert 'KAREN_DATABASE_RECOVERY_MODE: "${KAREN_DATABASE_RECOVERY_MODE-normal}"' in api
    overlay = (REPO_ROOT / "deploy/compose/docker-compose.prod.yml").read_text(encoding="utf-8")
    api_override = overlay.split("\n  api:", 1)[1].split("\n  web:", 1)[0]
    assert "env_file: !reset []" in api_override
    assert "KAREN_DATABASE_RECOVERY_MODE:" not in api_override
