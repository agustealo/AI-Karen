from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
CANONICAL_STARTUP = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
LEGACY_SERVER_APP = REPO_ROOT / "server" / "app.py"


def test_canonical_boundary_prunes_broken_legacy_shutdown_handlers() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "_prune_legacy_shutdown_handlers" in source
    assert '"_shutdown_database"' in source
    assert '"shutdown_extension_health_monitoring"' in source
    assert 'handler_module == "server.app"' in source
    assert "app.router.on_shutdown[:] = retained_handlers" in source
    assert "_legacy_shutdown_handlers_pruned" in source
    assert "_prune_legacy_shutdown_handlers(app)" in source


def test_database_shutdown_is_owned_by_canonical_lifespan() -> None:
    source = CANONICAL_STARTUP.read_text(encoding="utf-8")

    assert "get_database_config(settings)" in source
    assert "await database_config.cleanup()" in source


def test_legacy_database_shutdown_is_known_dead_source_until_app_rewrite() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    # This block remains only because server/app.py is still a transitional monolith.
    # The canonical application boundary must prune it before the ASGI app is returned.
    assert "async def _shutdown_database" in source
    assert "await db_config.cleanup()" in source


def test_canonical_entrypoint_does_not_create_database_shutdown_authority() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "get_database_config" not in source
    assert "db_config.cleanup" not in source
