"""Memory runtime gateway for API and service composition.

This gateway centralizes resolution of the active unified memory service and
provides deterministic degraded/unavailable signaling. It does not construct
memory implementations and does not depend on the legacy Web UI facade.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_karen_engine.core.memory.unified_memory_service import UnifiedMemoryService


@dataclass(frozen=True)
class MemoryRuntimeResolution:
    available: bool
    service: UnifiedMemoryService | None
    reason: str


async def resolve_memory_runtime() -> MemoryRuntimeResolution:
    """Resolve the registered canonical unified memory service."""
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
        if not isinstance(service, UnifiedMemoryService):
            return MemoryRuntimeResolution(
                available=False,
                service=None,
                reason="memory_service_contract_mismatch",
            )
        return MemoryRuntimeResolution(available=True, service=service, reason="ok")
    except Exception:
        return MemoryRuntimeResolution(
            available=False,
            service=None,
            reason="memory_runtime_unavailable",
        )
