"""Memory runtime gateway for API and service composition.

This gateway centralizes resolution of the active unified memory service and
provides deterministic degraded/unavailable signaling. It does not construct
memory implementations and does not depend on the legacy Web UI facade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryRuntimeResolution:
    available: bool
    service: Any | None
    reason: str


async def resolve_memory_runtime() -> MemoryRuntimeResolution:
    """Resolve the registered canonical unified memory service.

    The service container is consulted first. If no ``memory_service`` has been
    registered (the legacy runtime registry that performed this registration
    was removed), the canonical ``MemoryRuntimeManager`` singleton is resolved
    and registered so subsequent lookups are served from the container.
    """
    try:
        from ai_karen_engine.core.services.service_registry import get_service_registry

        registry = get_service_registry()
        service = registry.get_service("memory_service")
        if service is not None:
            return MemoryRuntimeResolution(available=True, service=service, reason="ok")
    except ValueError:
        pass  # not registered yet; resolve canonical manager below
    except Exception:
        logger.debug("memory_service registry lookup failed", exc_info=True)

    try:
        from ai_karen_engine.core.memory.memory_runtime_manager import get_memory_manager

        service = get_memory_manager()
    except Exception:
        logger.exception("Canonical memory runtime manager failed to initialize")
        return MemoryRuntimeResolution(
            available=False,
            service=None,
            reason="memory_runtime_unavailable",
        )

    if service is None:
        return MemoryRuntimeResolution(
            available=False,
            service=None,
            reason="memory_service_not_registered",
        )

    try:
        from ai_karen_engine.core.services.container import get_container

        get_container()._singletons.setdefault("memory_service", service)
    except Exception:
        logger.debug("Unable to cache memory_service in container", exc_info=True)

    return MemoryRuntimeResolution(available=True, service=service, reason="ok")
