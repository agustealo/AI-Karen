from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
APPLICATION_RUNTIME = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "application_runtime.py"
CANONICAL_STARTUP = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
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


def test_database_shutdown_is_owned_by_canonical_lifespan_services() -> None:
    source = CANONICAL_STARTUP.read_text(encoding="utf-8")

    assert "get_database_config(settings)" in source
    assert "await database_config.cleanup()" in source


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
