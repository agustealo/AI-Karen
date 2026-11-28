"""Executable recovery hold checks, run with canonical runtime dependencies."""
from __future__ import annotations


def test_recovery_hold_denies_app_before_startup_or_router_wiring(monkeypatch) -> None:
    import pytest
    import builtins
    from ai_karen_engine.config.database import DatabaseRecoveryHold

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"ai_karen_engine.server.routers", "ai_karen_engine.server.security"}:
            pytest.fail("held application attempted router or security import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    from ai_karen_engine.app import create_app

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



def test_legacy_application_module_denies_before_eager_imports(monkeypatch) -> None:
    import builtins
    import runpy
    from pathlib import Path

    import pytest
    from ai_karen_engine.config.database import DatabaseRecoveryHold

    source = Path(__file__).resolve().parents[2] / "src/ai_karen_engine/server/app.py"
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"fastapi", "ai_karen_engine.server.security", "ai_karen_engine.server.routers"}:
            pytest.fail("held legacy app attempted eager application import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "hold")
    with pytest.raises(DatabaseRecoveryHold):
        runpy.run_path(str(source))


def test_legacy_startup_and_lifespan_cannot_degrade_around_hold(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest
    from ai_karen_engine.config.database import DatabaseRecoveryHold
    from ai_karen_engine.server import startup

    initialize = AsyncMock()
    cleanup = AsyncMock()
    for name in ("init_database", "init_crawl4ai_service", "_initialize_optional_local_voice"):
        monkeypatch.setattr(startup, name, initialize)
    for name in ("on_shutdown", "on_shutdown_with_extensions"):
        monkeypatch.setattr(startup, name, cleanup)
    monkeypatch.setenv("KAREN_DATABASE_RECOVERY_MODE", "hold")
    settings = SimpleNamespace(environment="development")
    app = SimpleNamespace(state=SimpleNamespace())

    async def attempt():
        for start in (startup.on_startup, startup.on_startup_with_extensions):
            with pytest.raises(DatabaseRecoveryHold):
                await start(settings, app)
        for factory in (startup.create_lifespan, startup.create_lifespan_with_extensions):
            with pytest.raises(DatabaseRecoveryHold):
                async with factory(settings)(app):
                    pytest.fail("held legacy lifespan yielded")

    asyncio.run(attempt())
    initialize.assert_not_awaited()
    cleanup.assert_not_awaited()
    assert not hasattr(app.state, "settings")
