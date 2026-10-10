"""Canonical profile attribute interpretation without modifying user language.

This identifies the requested fact only. It never changes user text, grants recall,
infers a fact, or bypasses tenant/consent/validity checks.
"""
from __future__ import annotations

import re


def normalize_personal_query(text: str) -> str:
    """Canonicalize typography and whitespace, not vocabulary or tone."""
    return " ".join(str(text or "").casefold().replace("’", "'").split())


# Bounded connective text accommodates tone, filler, and natural word order.
# No prohibited-word vocabulary is maintained here.
_GAP = r"(?:[\w'-]+\s+){0,5}"
_ATTRIBUTE_QUESTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("preferred_name", (
        rf"(?:what(?:\s+is|'s|s)|hats|hat's|remember)\s+{_GAP}my\s+{_GAP}name",
        r"my\s+name\s+is\s+(?:what|who)",
        rf"what\s+{_GAP}am\s+i\s+{_GAP}called",
        rf"what\s+{_GAP}do\s+(?:you|people|they)\s+call\s+me",
    )),
    ("origin_location", (
        rf"where\s+{_GAP}(?:am\s+i|i'm|im)\s+from",
        rf"where\s+did\s+i\s+{_GAP}say\s+(?:i'm|i\s+am|im)\s+from",
    )),
    ("birthplace", (
        rf"where\s+{_GAP}was\s+i\s+born(?:\s+at)?",
        rf"(?:what(?:\s+is|'s|s))\s+{_GAP}my\s+birthplace",
    )),
    ("residence_location", (rf"where\s+{_GAP}do\s+i\s+{_GAP}live", rf"where\s+{_GAP}am\s+i\s+based")),
    ("work_location", (rf"where\s+{_GAP}do\s+i\s+{_GAP}work", rf"(?:what(?:\s+is|'s|s))\s+{_GAP}my\s+workplace")),
    ("current_location", (rf"where\s+{_GAP}am\s+i\s+(?:currently|right\s+now)",)),
)


def requested_profile_attribute(text: str) -> str | None:
    """Resolve one unambiguous attribute, independent of expressive wording."""
    question = normalize_personal_query(text).strip(" ?.!")
    matches = {
        attribute for attribute, patterns in _ATTRIBUTE_QUESTIONS
        if any(re.search(rf"\b{pattern}\b", question) for pattern in patterns)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def referenced_profile_attribute(
    text: str, messages: list[dict[str, object]]
) -> str | None:
    """Resolve only unambiguous, immediate user-profile follow-up references.

    No model inference, memory reads, or cross-session guesswork. Only recent
    user turns establish the subject; assistant claims never establish facts.
    """
    explicit = requested_profile_attribute(text)
    if explicit:
        return explicit
    utterance = normalize_personal_query(text).strip(" ?.!").strip()
    if utterance not in {"my name", "what is it", "what's it", "whats it"}:
        return None
    if utterance == "my name":
        return "preferred_name"
    # Resolve a pronoun only if the immediately preceding user turn was
    # explicitly about a single personal attribute.
    for item in reversed(messages[:-1]):
        if str(item.get("role") or "").casefold() == "user":
            return requested_profile_attribute(str(item.get("content") or ""))
    return None


__all__ = ["normalize_personal_query", "requested_profile_attribute", "referenced_profile_attribute"]
