"""Backend-neutral entity cue extraction for memory-graph recall.

This module owns deterministic query-to-entity cues. Database-specific alias,
fuzzy, or semantic resolution remains behind graph/platform repositories.
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "about",
    "after",
    "again",
    "before",
    "could",
    "did",
    "does",
    "from",
    "have",
    "how",
    "into",
    "last",
    "memory",
    "our",
    "that",
    "the",
    "then",
    "this",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
    "would",
    "you",
}


def extract_entity_cues(text: str, *, max_cues: int = 8) -> tuple[str, ...]:
    """Return bounded, stable entity-like cues from natural-language text.

    Order favors explicit quoted phrases, multi-word capitalized names, then
    informative tokens. This is intentionally deterministic and cheap; it does
    not claim that every cue is a resolved entity.
    """
    raw = str(text or "").strip()
    if not raw or max_cues < 1:
        return ()

    candidates: list[str] = []

    for match in re.finditer(r"[\"']([^\"']{2,100})[\"']", raw):
        candidates.append(match.group(1).strip())

    capitalized = re.findall(
        r"\b(?:[A-Z][\w.-]*)(?:\s+[A-Z][\w.-]*){1,4}\b",
        raw,
    )
    candidates.extend(capitalized)

    tokens = re.findall(r"[\w.-]{3,}", raw, flags=re.UNICODE)
    informative = [token for token in tokens if token.casefold() not in _STOPWORDS]
    informative.sort(key=lambda token: (-len(token), raw.find(token)))
    candidates.extend(informative)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split()).casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate.strip())
        if len(deduped) >= max_cues:
            break
    return tuple(deduped)


__all__ = ["extract_entity_cues"]
