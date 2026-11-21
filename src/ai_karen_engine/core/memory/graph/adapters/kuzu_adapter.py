"""Fail-closed compatibility import for the retired Kuzu graph adapter.

The previous adapter silently kept memory graph records in process-local
dictionaries rather than durable Kuzu storage. It could also return raw event
references from direct callers without current PostgreSQL consent or external
source authorization. Kuzu is not a supported `LeanGraphConfig` backend.

Use `LeanGraphService` with the canonical PostgreSQL repository for storage.
Only NeuroRecall-selected evidence may be presented as authorized memory.
"""

from __future__ import annotations

from ..config import LeanGraphConfig


class KuzuGraphUnavailableError(RuntimeError):
    """The retired Kuzu graph path cannot execute memory operations."""


class KuzuGraphAdapter:
    """Legacy import name retained without independent graph execution."""

    def __init__(self, config: LeanGraphConfig) -> None:
        raise KuzuGraphUnavailableError(
            "Kuzu memory graph backend is retired; use canonical PostgreSQL "
            "memory graph and NeuroRecall-authorized evidence"
        )


__all__ = ["KuzuGraphAdapter", "KuzuGraphUnavailableError"]
