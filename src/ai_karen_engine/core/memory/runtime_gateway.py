"""Memory runtime gateway for API routes.

This gateway centralizes resolution of the active memory runtime and provides
deterministic degraded/unavailable signaling for route-layer error contracts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_karen_engine.core.memory.memory_service import WebUIMemoryService


@dataclass(frozen=True)
class MemoryRuntimeResolution:
    available: bool
    service: WebUIMemoryService | None
    reason: str


async def resolve_memory_runtime() -> MemoryRuntimeResolution:
    """Resolve the runtime memory service through a single gateway."""
    try:
        from ai_karen_engine.core.services.service_registry import get_service_registry

        registry = get_service_registry()
        service = await registry.get_service("memory_service")
        if service is None:
            return MemoryRuntimeResolution(
                available=False,
                service=None,
                reason="memory_service_not_registered",
            )
        return MemoryRuntimeResolution(available=True, service=service, reason="ok")
    except Exception:
        return MemoryRuntimeResolution(
            available=False,
            service=None,
            reason="memory_runtime_unavailable",
        )
