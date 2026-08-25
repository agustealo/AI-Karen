"""
Shared helpers for Stage 3 curated semantic recall.

These helpers keep curated-recall selection logic in one place so the chat
orchestrator, memory processor, and higher-level memory services do not drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

CURATED_MEMORY_KIND = "curated_memory"
DEFAULT_CURATED_MEMORY_CLASSES = (
    "semantic_long_term",
    "episodic",
    "user_fact",
    "project_fact",
)


def build_curated_metadata_filter(
    base_filter: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a metadata filter that scopes retrieval to curated artifacts."""
    metadata_filter = dict(base_filter or {})
    metadata_filter["curated"] = True
    return metadata_filter


def is_curated_memory_metadata(
    metadata: Mapping[str, Any] | None,
    allowed_classes: Sequence[str] | None = None,
) -> bool:
    """Check whether metadata represents a curated Stage 3 artifact."""
    if not metadata or metadata.get("curated") is not True:
        return False
    memory_class = metadata.get("memory_class")
    if not allowed_classes:
        return True
    return memory_class in set(allowed_classes)


def filter_curated_memories(
    memories: Iterable[Any],
    allowed_classes: Sequence[str] | None = None,
) -> list[Any]:
    """Filter a memory iterable down to curated artifacts only."""
    return [
        memory
        for memory in memories
        if is_curated_memory_metadata(
            getattr(memory, "metadata", None),
            allowed_classes=allowed_classes,
        )
    ]
