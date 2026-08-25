from __future__ import annotations

from threading import RLock

from .capability_types import CapabilityDefinition, CapabilityId, CapabilityLookupResult


class CapabilityRegistry:
    """
    Canonical registry for Karen AI/ML capabilities.

    This registry owns what Karen can do.
    It does not own provider selection, model loading, extension execution,
    or prompt construction.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._capabilities: dict[CapabilityId, CapabilityDefinition] = {}

    def register(self, capability: CapabilityDefinition) -> None:
        with self._lock:
            if capability.id in self._capabilities:
                raise ValueError(f"Capability already registered: {capability.id.value}")
            self._capabilities[capability.id] = capability

    def upsert(self, capability: CapabilityDefinition) -> None:
        with self._lock:
            self._capabilities[capability.id] = capability

    def get(self, capability_id: CapabilityId | str) -> CapabilityLookupResult:
        cid = self._normalize_id(capability_id)
        with self._lock:
            capability = self._capabilities.get(cid)
            if capability is None:
                return CapabilityLookupResult(
                    found=False,
                    capability=None,
                    reason="capability_not_registered",
                )
            return CapabilityLookupResult(found=True, capability=capability)

    def require(self, capability_id: CapabilityId | str) -> CapabilityDefinition:
        result = self.get(capability_id)
        if not result.found or result.capability is None:
            raise KeyError(result.reason or "capability_not_registered")
        return result.capability

    def list(self) -> tuple[CapabilityDefinition, ...]:
        with self._lock:
            return tuple(sorted(self._capabilities.values(), key=lambda item: item.id.value))

    def ids(self) -> tuple[str, ...]:
        return tuple(item.id.value for item in self.list())

    def clear(self) -> None:
        with self._lock:
            self._capabilities.clear()

    @staticmethod
    def _normalize_id(capability_id: CapabilityId | str) -> CapabilityId:
        if isinstance(capability_id, CapabilityId):
            return capability_id
        return CapabilityId(str(capability_id))


_registry = CapabilityRegistry()


def get_capability_registry() -> CapabilityRegistry:
    return _registry