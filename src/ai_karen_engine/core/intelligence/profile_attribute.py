"""Canonical rule-backed personal profile query attribute interpretation.

This interprets a question only. It does not grant recall, infer a personal fact,
or bypass user/tenant/consent/validity checks in persistence.
"""

from __future__ import annotations

import re


_DISCOURSE_INTENSIFIER = re.compile(
    r"\b(?:the\s+fuck|the\s+hell|fucking|fuckin|fuck|freaking|fricking|goddamn|damn)\b",
    re.IGNORECASE,
)


def normalize_personal_query(text: str) -> str:
    """Remove non-semantic emphasis, preserving the user's requested attribute.

    This transformation is only for bounded personal-recall interpretation.
    Never replace the user utterance in chat, persistence or memory evidence.
    """
    normalized = str(text or "").casefold().replace("’", "'")
    normalized = _DISCOURSE_INTENSIFIER.sub(" ", normalized)
    return " ".join(normalized.split())


def requested_profile_attribute(text: str) -> str | None:
    """Identify an unambiguous requested profile attribute or return unknown."""
    q = normalize_personal_query(text)
    cues = (
        ("preferred_name", ("what's my name", "what is my name", "whats my name",
                            "hats my name", "hat's my name", "remember my name")),
        ("origin_location", ("where am i from", "where i'm from", "where im from", "where did i say i'm from", "where did i say im from")),
        ("birthplace", ("where was i born", "my birthplace", "where was i born at")),
        ("residence_location", ("where do i live", "where i live", "where am i based")),
        ("work_location", ("where do i work", "where i work", "my workplace", "work location")),
        ("current_location", ("where am i currently", "where am i right now")),
    )
    matches = {attribute for attribute, phrases in cues if any(phrase in q for phrase in phrases)}
    return next(iter(matches)) if len(matches) == 1 else None


__all__ = ["normalize_personal_query", "requested_profile_attribute"]
