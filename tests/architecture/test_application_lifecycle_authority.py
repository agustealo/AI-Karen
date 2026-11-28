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


def test_recovery_hold_denies_app_before_startup_or_router_wiring(monkeypatch) -> None:
    import pytest
    from ai_karen_engine.app import create_app
    from ai_karen_engine.config.database import DatabaseRecoveryHold

    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "hold")
    with pytest.raises(DatabaseRecoveryHold):
        create_app()


def test_recovery_hold_denies_lifespan_before_startup_or_cleanup(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest
    from fastapi import FastAPI
    from ai_karen_engine.config.database import DatabaseRecoveryHold
    from ai_karen_engine.server import application_runtime, startup

    start, stop = AsyncMock(), AsyncMock()
    monkeypatch.setattr(startup, "on_startup", start)
    monkeypatch.setattr(startup, "on_shutdown", stop)
    attach, detach = AsyncMock(), AsyncMock()
    monkeypatch.setattr(application_runtime, "initialize_application_runtime", attach)
    monkeypatch.setattr(application_runtime, "shutdown_application_runtime", detach)
    lifespan = application_runtime.create_application_lifespan(SimpleNamespace())
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "hold")

    async def attempt():
        async with lifespan(FastAPI()):
            pytest.fail("held lifespan yielded")

    with pytest.raises(DatabaseRecoveryHold):
        asyncio.run(attempt())
    for mock in (start, stop, attach, detach):
        mock.assert_not_awaited()


def test_recovery_mode_is_strict_and_never_released_by_observation(monkeypatch) -> None:
    import pytest
    from ai_karen_engine.config.database import (
        DatabaseRecoveryHold, require_database_recovery_not_held,
    )

    monkeypatch.delenv("KAREN_DATABASE_RECOVERY_MODE", raising=False)
    require_database_recovery_not_held()
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "normal")
    require_database_recovery_not_held()
    for invalid in ("hold", "", "verified", "NORMAL", "false"):
        monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", invalid)
        with pytest.raises(DatabaseRecoveryHold):
            require_database_recovery_not_held()


def test_recovery_hold_blocks_cached_canonical_pool_checkout(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pytest
    from sqlalchemy import create_engine, text
    from ai_karen_engine.config.database import DatabaseRecoveryHold
    from ai_karen_engine.persistence.postgres import engine as owner

    # Real SQLAlchemy checkout behavior, with SQLite only as a disposable
    # pool fixture. No production connection is opened by this unit test.
    sync = create_engine("sqlite://")
    async_sync = create_engine("sqlite://")
    monkeypatch.setattr(owner, "create_engine", lambda *a, **k: sync)
    monkeypatch.setattr(owner, "create_async_engine", lambda *a, **k: SimpleNamespace(sync_engine=async_sync))
    monkeypatch.setattr(owner, "async_sessionmaker", Mock())
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "normal")
    canonical = owner.PostgresEngine()
    canonical.initialize()
    for cached in (sync, async_sync):
        with cached.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "hold")
    try:
        for attr in ("engine", "async_engine", "session_factory", "async_session_factory"):
            with pytest.raises(DatabaseRecoveryHold):
                getattr(canonical, attr)
        for cached in (sync, async_sync):
            with pytest.raises(DatabaseRecoveryHold), cached.connect():
                pytest.fail("held checkout succeeded")
        with pytest.raises(DatabaseRecoveryHold):
            canonical.initialize()
    finally:
        sync.dispose()
        async_sync.dispose()
