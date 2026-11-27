"""Pure evidence grammar for explicitly self-authored profile corrections.

CORTEX/formation decide eligibility and memory retention. This module only
identifies explicit linguistic correction framing, across arbitrary domains.
"""
from __future__ import annotations

import re


_CORRECTION_PREAMBLE = re.compile(
    r"^\s*(?:actually\b\s*[,;:]?\s*|"
    r"to\s+correct\s+myself\b\s*[,;:]?\s*|"
    r"correction\s*:\s*|"
    r"i\s+was\s+wrong\s*[,;:]\s*)",
    re.IGNORECASE,
)
_SELF_AUTHORED_CLAUSE = re.compile(
    r"^(?:i(?:'m|\s|\b)|my\s|call\s+me\b)",
    re.IGNORECASE,
)

_REPORTED_SPEECH = re.compile(
    r"\b(?:he|she|they|i|we|someone|my\s+\w+)\s+"
    r"(?:said|says|thinks|claims|quoted)\b",
    re.IGNORECASE,
)

_EMBEDDED_SUBJECT = re.compile(
    r"\b(?:i|my|me|we|our|us|you|your|he|his|she|her|they|their|them|someone)\b",
    re.IGNORECASE,
)


def is_atomic_correction_value(value: str) -> bool:
    """Conservatively reject clause-like subject markers inside a matched value.

    Only used for the narrow correction admission path. Ordinary fact
    classification retains its existing treatment of names and locations.
    """
    return bool(value.strip() and not _EMBEDDED_SUBJECT.search(value))


def explicit_self_correction_clause(text: str) -> str | None:
    """Return a correction-framed clause, not proof that its claim is direct."""
    normalized = " ".join(str(text or "").replace("’", "'").split())
    match = _CORRECTION_PREAMBLE.match(normalized)
    if not match or any(quote in normalized for quote in ('"', "“", "”")):
        return None
    clause = normalized[match.end():]
    if not _SELF_AUTHORED_CLAUSE.match(clause) or _REPORTED_SPEECH.search(clause):
        return None
    return clause


def is_explicit_self_correction(text: str) -> bool:
    """True only for clear correction framing of a first-person clause."""
    return explicit_self_correction_clause(text) is not None


__all__ = [
    "is_explicit_self_correction", "explicit_self_correction_clause",
    "is_atomic_correction_value",
]
