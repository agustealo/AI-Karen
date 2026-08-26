"""Transitional startup composition adapter.

The root ``server`` package no longer owns startup policy or subsystem
initialization. Canonical lifecycle behavior lives under ``ai_karen_engine`` and
is composed through FastAPI lifespan.

This module exists only while ``server.app`` remains the transitional FastAPI
factory. It must not select providers/models, warm model stacks, initialize
memory directly, manage extension recovery, or create independent lifecycle
policy.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from ai_karen_engine.server.startup import create_lifespan

logger = logging.getLogger("kari")


def register_startup_tasks(app: FastAPI) -> None:
    """Compatibility hook retained while ``server.app`` is transitional.

    The canonical lifespan created by :func:`create_lifespan` owns application
    startup sequencing. This hook intentionally registers no startup callbacks.
    """

    if not hasattr(app.state, "database_available"):
        app.state.database_available = False


def register_shutdown_tasks(app: FastAPI) -> None:
    """Compatibility hook retained while ``server.app`` is transitional.

    Canonical lifespan owns shutdown sequencing. This hook intentionally
    registers no shutdown callbacks.
    """

    del app


async def initialize_fallback_systems() -> None:
    """Retired compatibility hook.

    Degraded operation belongs to canonical runtime/provider policy rather than
    the web-server composition layer.
    """

    logger.debug("Legacy startup fallback hook is retired")


async def run_startup_checks_and_fallbacks(log: Any) -> None:
    """Retired compatibility wrapper with no runtime authority."""

    log.debug("Legacy startup checks/fallback wrapper is retired")
