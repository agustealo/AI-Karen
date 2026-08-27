from __future__ import annotations

from .contracts import MemoryCandidate, MemoryClass


def classify_memory_candidate(candidate: MemoryCandidate) -> MemoryClass:
    """Classify a recall candidate without discarding explicit source truth."""
    declared = str(candidate.metadata.get("memory_class") or "").strip().casefold()
    if declared:
        try:
            return MemoryClass(declared)
        except ValueError:
            pass

    if candidate.source == "redis":
        return MemoryClass.STM

    text = candidate.text.lower()
    source_trust = float(candidate.metadata.get("source_trust", 1.0))
    if candidate.metadata.get("explicit_forget") or candidate.metadata.get("user_correction"):
        return MemoryClass.LESSON
    if candidate.source in {"web", "plugin"} and source_trust < 0.8:
        return MemoryClass.QUARANTINE
    if "when i ask" in text or "workflow" in text or "use the same" in text:
        return MemoryClass.PROCEDURAL
    if "favorite" in text or "my " in text:
        return MemoryClass.SEMANTIC
    if "by friday" in text or "deadline" in text or "today" in text:
        return MemoryClass.EPISODIC
    return candidate.memory_class
