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
    r"\b(?:he|she|they|someone|my\s+\w+)\s+"
    r"(?:said|says|thinks|claims|quoted)\b",
    re.IGNORECASE,
)


def is_explicit_self_correction(text: str) -> bool:
    """True only for clear correction framing of a first-person clause."""
    normalized = " ".join(str(text or "").replace("’", "'").split())
    match = _CORRECTION_PREAMBLE.match(normalized)
    if not match or any(quote in normalized for quote in ('"', "“", "”")):
        return False
    clause = normalized[match.end():]
    return bool(
        _SELF_AUTHORED_CLAUSE.match(clause)
        and not _REPORTED_SPEECH.search(clause)
    )


__all__ = ["is_explicit_self_correction"]
