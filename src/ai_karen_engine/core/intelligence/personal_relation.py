"""Open-vocabulary, explicitly self-attributed personal relationship grammar.

Intelligence interprets user-supplied meaning only. This module neither
authorizes memory writes nor decides whether a personal detail is sensitive,
durable, useful, or correct. Formation and NeuroVault retain those decisions.

A narrow declarative grammar is intentionally preferable to guessing what an
unfamiliar sentence means. Ambiguous, third-party and negated statements are
not affirmative personal facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ai_karen_engine.core.intelligence.correction_intent import (
    is_explicit_self_correction,
)

_RELATION = r"[a-z][a-z0-9/-]*(?:\s+[a-z][a-z0-9/-]*){0,4}"
_ASSERTION = re.compile(
    rf"^(?:(?:actually|no)[,;]?\s+)?my\s+"
    rf"(?P<relation>{_RELATION})\s+(?:is|are)\s+"
    r"(?P<value>[^\n.!?;:,]{2,120})[.!]?$",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    rf"^(?:(?:what(?:\s+is|'s|s)?|tell\s+me|remind\s+me\s+of)\s+)"
    rf"my\s+(?P<relation>{_RELATION})[?.!]*$",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(r"^(?:not|never|no\s+longer|none)\b", re.I)
_HEDGED = re.compile(
    r"^(?:maybe|perhaps|possibly|probably|i\s+(?:think|guess|feel))\b",
    re.I,
)
_TEMPORAL = re.compile(
    r"\b(?:today|tonight|currently|temporarily|this\s+(?:week|month|season|year)|"
    r"right\s+now|at\s+the\s+moment)\b",
    re.I,
)
_SECONDARY_SUBJECT = re.compile(r"\b(?:he|she|they|someone|another\s+person)\s+(?:said|says)\b", re.I)
_SUBJECT_POSSESSIVE = re.compile(r"(?:'s|’s)\b", re.I)
_NON_FACT_RELATIONS = frozenset({"favorite", "fav", "favourite", "name"})


@dataclass(frozen=True, slots=True)
class PersonalRelationAssertion:
    attribute: str
    predicate: str
    value: str
    modality: str
    temporal_scope: str | None
    explicit_correction: bool
    evidence_text: str


def personal_relation_attribute(predicate: str) -> str | None:
    """Identity is derived from the relation, never from known category names."""
    cleaned = " ".join(str(predicate or "").casefold().split())
    tokens = cleaned.split()
    if (
        not tokens or len(tokens) > 5
        or tokens[0] in _NON_FACT_RELATIONS
        or any(token in {"and", "or", "your", "their", "someone", "friend's"}
               for token in tokens)
        or _SUBJECT_POSSESSIVE.search(cleaned)
    ):
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return f"personal_relation.{slug}" if 1 <= len(slug) <= 80 else None


def extract_personal_relation(text: str) -> PersonalRelationAssertion | None:
    """Recognize a simple first-person nominal relation without invention."""
    original = " ".join(str(text or "").replace("’", "'").split())
    if not original or len(original) > 220 or original[0] in {'"', "'"}:
        return None
    match = _ASSERTION.fullmatch(original)
    if match is None:
        return None
    predicate = " ".join(match.group("relation").split()).casefold()
    attribute = personal_relation_attribute(predicate)
    value = " ".join(match.group("value").strip().split())
    if (
        attribute is None or not value or len(value) > 120
        or _SECONDARY_SUBJECT.search(value)
    ):
        return None
    modality = (
        "negated" if _NEGATIVE.search(value)
        else "uncertain" if _HEDGED.search(value)
        else "asserted"
    )
    temporal_match = _TEMPORAL.search(value)
    return PersonalRelationAssertion(
        attribute=attribute,
        predicate=predicate,
        value=value,
        modality=modality,
        temporal_scope=temporal_match.group(0).casefold() if temporal_match else None,
        explicit_correction=is_explicit_self_correction(original),
        evidence_text=original,
    )


def requested_personal_relation_attribute(text: str) -> str | None:
    """Resolve only one explicit open-domain self-referential question."""
    question = " ".join(str(text or "").replace("’", "'").split()).strip()
    match = _QUESTION.fullmatch(question)
    if match is None:
        return None
    return personal_relation_attribute(match.group("relation"))


__all__ = [
    "PersonalRelationAssertion",
    "extract_personal_relation",
    "personal_relation_attribute",
    "requested_personal_relation_attribute",
]
