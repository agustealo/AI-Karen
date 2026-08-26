"""Write-side base for the canonical memory runtime.

The mature write/governance implementation is temporarily quarantined in
`_legacy_memory_runtime_impl` while its write methods are extracted. This
module deliberately exposes no usable recall path. Production reads belong to
NeuroRecall through `memory_runtime_manager.MemoryRuntimeManager`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from . import _legacy_memory_runtime_impl as _legacy

_METRICS = _legacy._METRICS


class MemoryRuntimeManager(_legacy.MemoryRuntimeManager):
    """Write/governance runtime base with recall explicitly disabled."""

    def __init__(self, consolidation_adapter: Any | None = None) -> None:
        super().__init__(
            retrieval_adapter=None,
            consolidation_adapter=consolidation_adapter,
            recall_service=None,
        )
        self._retrieval_adapter = None
        self._recall_service = None

    def set_recall_service(self, service: Any) -> None:
        del service
        raise RuntimeError("write runtime base cannot own recall; use NeuroRecall")

    def set_retrieval_adapter(self, adapter: Any) -> None:
        del adapter
        raise RuntimeError("write runtime base cannot own retrieval; use NeuroRecall")

    async def recall_context(
        self,
        user_id: Any,
        query: str,
        top_k: int = 10,
        tiers: Sequence[str] | None = None,
        tenant_id: str | None = None,
        include_embeddings: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del user_id, query, top_k, tiers, tenant_id, include_embeddings, kwargs
        raise RuntimeError("write runtime base cannot recall; use canonical NeuroRecall")


def bind_memory_manager(manager: Any) -> None:
    """Bind legacy write compatibility functions to the canonical runtime instance."""
    _legacy.memory_manager = manager


async def update_memory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return await _legacy.update_memory(*args, **kwargs)


async def export_promoted_artifacts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return await _legacy.export_promoted_artifacts(*args, **kwargs)


def get_metrics() -> dict[str, Any]:
    return _legacy.get_metrics()


__all__ = [
    "MemoryRuntimeManager",
    "bind_memory_manager",
    "export_promoted_artifacts",
    "get_metrics",
    "update_memory",
]
