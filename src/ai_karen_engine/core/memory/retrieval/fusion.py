from __future__ import annotations

from collections.abc import Iterable

from ..types import MemoryEntry


def reciprocal_rank_fusion(scored_lists: dict[str, list[MemoryEntry]], k: int = 60) -> list[MemoryEntry]:
    fused: dict[str, float] = {}
    best: dict[str, MemoryEntry] = {}
    for _, entries in scored_lists.items():
        for rank, entry in enumerate(entries, start=1):
            fused[entry.id] = fused.get(entry.id, 0.0) + 1.0 / (k + rank)
            if entry.id not in best or entry.relevance > best[entry.id].relevance:
                best[entry.id] = entry
    ranked = sorted(best.values(), key=lambda e: fused.get(e.id, 0.0), reverse=True)
    for entry in ranked:
        entry.relevance = max(entry.relevance, fused.get(entry.id, 0.0))
        if entry.metadata:
            entry.metadata.custom["fusion_score"] = fused.get(entry.id, 0.0)
    return ranked


def dedupe_by_id(entries: Iterable[MemoryEntry]) -> list[MemoryEntry]:
    seen = set()
    out: list[MemoryEntry] = []
    for entry in entries:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        out.append(entry)
    return out
