"""Executable recovery hold checks, run with canonical runtime dependencies."""
from __future__ import annotations


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

