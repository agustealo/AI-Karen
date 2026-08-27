from __future__ import annotations

"""Application lifecycle ownership for the canonical Runtime services.

The FastAPI lifespan is the process lifecycle boundary. Runtime composition,
ChatRuntime, and ChatRuntimeControlPlane are attached to ``app.state`` here so
application startup owns the live service graph and application shutdown owns
its background tasks.

Module-level runtime accessors remain compatibility surfaces during
CORE-COMPOSE convergence, but they resolve the same process composition and are
no longer the only place where the live objects can be reached.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_RUNTIME_ATTACHED_STATE_KEY = "_canonical_runtime_attached"
_RUNTIME_SHUTDOWN_STATE_KEY = "_canonical_runtime_shutdown"


async def initialize_application_runtime(app: FastAPI) -> None:
    """Attach canonical Runtime services to the application lifecycle."""
    if getattr(app.state, _RUNTIME_ATTACHED_STATE_KEY, False) and not getattr(
        app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False
    ):
        return

    from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
    from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
        get_chat_runtime_control_plane,
    )
    from ai_karen_engine.core.runtime.composition import get_runtime_composition

    composition = get_runtime_composition()
    control_plane = await get_chat_runtime_control_plane()
    if not getattr(control_plane, "_initialized", False):
        await control_plane.initialize()
    chat_runtime = get_chat_runtime()

    app.state.runtime_composition = composition
    app.state.chat_runtime = chat_runtime
    app.state.chat_runtime_control_plane = control_plane
    setattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False)
    setattr(app.state, _RUNTIME_ATTACHED_STATE_KEY, True)

    logger.info("Canonical application Runtime services attached")


async def shutdown_application_runtime(app: FastAPI) -> None:
    """Stop application-owned Runtime background work exactly once."""
    if getattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False):
        return

    control_plane = getattr(app.state, "chat_runtime_control_plane", None)
    if control_plane is not None:
        try:
            await control_plane.shutdown()
        except Exception as exc:
            logger.warning("Runtime ControlPlane shutdown degraded: %s", exc)

    setattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, True)
    logger.info("Canonical application Runtime services shut down")


def create_application_lifespan(settings: Any):
    """Create the canonical app lifespan around existing service startup.

    Existing service initialization remains in ``server.startup`` while this
    boundary takes ownership of Runtime attachment and teardown. That keeps the
    migration behavior-preserving and gives CORE-COMPOSE a stable seam for the
    later ``server.app`` inversion.
    """
    from ai_karen_engine.server.startup import on_shutdown, on_startup

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await on_startup(settings, app)
        await initialize_application_runtime(app)
        try:
            yield
        finally:
            await shutdown_application_runtime(app)
            await on_shutdown(app)

    return lifespan


__all__ = [
    "create_application_lifespan",
    "initialize_application_runtime",
    "shutdown_application_runtime",
]
