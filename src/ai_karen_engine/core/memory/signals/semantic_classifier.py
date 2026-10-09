"""Deterministic semantic memory classification for explicit user statements.

This module owns only memory-candidate semantics. It does not authorize writes,
persist data, rank recall, or infer hidden reasoning. Model-assisted formation
may enrich these candidates later through prompt contracts, but explicit user
statements are classified deterministically first so identity/preferences/goals
remain reliable when NLP models degrade.
"""

from __future__ import annotations

import re

from .general_fact_classifier import classify_general_user_facts
from .signal_models import MemorySignal


_NAME = re.compile(
    r"(?i)\b(?:my name is|call me)\s+([A-Za-z][A-Za-z' -]{0,60}?)(?=[.!?,;]|$)"
)
_FAVORITE_COLOR = re.compile(
    r"(?i)\bmy favou?rite colou?r is\s+([A-Za-z][A-Za-z -]{0,30}?)(?=[.!?,;]|$)"
)
_COLOR_IS_FAVORITE = re.compile(
    r"(?i)\b(?:actually\s+)?([A-Za-z][A-Za-z -]{0,30}?)\s+is\s+"
    r"my favou?rite colou?r(?:\s+now)?(?=[.!?,;]|$)"
)
_GOAL_PATTERNS = (
    re.compile(r"(?i)\bmy goal is\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bi(?:'m| am) trying to\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bi want to\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bi plan to\s+(.+?)(?=[.!?]|$)"),
)
_INTERVIEW = re.compile(
    r"(?i)\b(?:i have|i(?:'ve| have) got|i(?:'m| am) scheduled for)\s+"
    r"(?:an?\s+)?(?:job\s+)?interview\b(.*?)(?=[.!?]|$)"
)
_INTERVIEW_CANCELLED = re.compile(
    r"(?i)\b(?:my\s+)?(?:job\s+)?interview\b.*\b(?:was|is|got)\s+cancel(?:led|ed)\b"
)
_INTERVIEW_DONE = re.compile(
    r"(?i)\b(?:my\s+)?(?:job\s+)?interview\b.*\b(?:is|was)\s+(?:done|over|finished|completed)\b"
)
_JOB_OFFER = re.compile(
    r"(?i)\b(?:i got the job|they offered me the job|i got an? offer)\b"
)
_GOAL_ABANDON = re.compile(
    r"(?i)\bi(?:'m| am| have)?\s*(?:no longer|not)\s+(?:trying to|working on)\s+(.+?)(?=[.!?]|$)"
)
_GOAL_STOPPED = re.compile(
    r"(?i)\bi\s+(?:stopped|quit|gave up)\s+(?:trying to|working on)?\s*(.+?)(?=[.!?]|$)"
)
_OPEN_LOOP_PATTERNS = (
    re.compile(r"(?i)\bi still need to\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bi need to follow up(?: with| on)?\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bi promised to\s+(.+?)(?=[.!?]|$)"),
    re.compile(r"(?i)\bwe still need to\s+(.+?)(?=[.!?]|$)"),
)
_OPEN_LOOP_DONE = re.compile(
    r"(?i)\bi\s+(?:finished|completed|handled|took care of)\s+(.+?)(?=[.!?]|$)"
)


_EXPLICIT_MEMORY_SAVE = re.compile(
    r"^(?:(?:please|can you|could you|i want you to)\s+)?"
    r"(?:remember|save|store)\s+"
    r"(?P<target>this|that|my\b.+?|the\b.+?|what i (?:just )?(?:said|told you))"
    r"(?:\s+(?:for later|long[- ]term|permanently|in (?:your )?memory))?[.!?]*$",
    re.IGNORECASE,
)
_MEMORY_SAVE_DEICTIC_TARGETS = {
    "this",
    "that",
    "what i said",
    "what i just said",
    "what i told you",
    "what i just told you",
}
_MEMORY_SAVE_TARGET_STOPWORDS = {
    "my",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "in",
    "on",
    "about",
    "information",
    "info",
    "fact",
    "facts",
}


def _normalize_save_text(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("’", "'").split())


_PERSONAL_RECALL_QUERY = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?"
    r"(?:where\s+(?:am|was)\s+i\s+(?:from|born|currently|right now|based)|"
    r"where\s+did\s+i\s+grow\s+up|"
    r"where\s+do\s+i\s+(?:live|work)|"
    r"(?:what\s+is|what's|whats|hats|hat's)\s+my\s+.+|"
    r"what\s+(?:are|was|were)\s+my\s+.+|"
    r"what\s+do\s+you\s+(?:remember|know)\s+about\s+me|"
    r"do\s+you\s+remember\s+my\s+.+|"
    r"what\s+did\s+i\s+tell\s+you\s+about\s+.+|"
    r"i\s+already\s+told\s+you(?:\s+.+)?)"
    r"[?.!]*$",
    re.IGNORECASE,
)


def is_personal_memory_recall_query(text: str) -> bool:
    """Recognize a bounded recall cue; authorization remains with policy."""
    normalized = " ".join(str(text or "").strip().replace("’", "'").split())
    return bool(_PERSONAL_RECALL_QUERY.fullmatch(normalized))


def is_explicit_memory_save_request(text: str) -> bool:
    """Recognize bounded user-directed save intent, never authorize a write."""
    return bool(_EXPLICIT_MEMORY_SAVE.fullmatch(_normalize_save_text(text)))


def explicit_memory_save_target_terms(text: str) -> frozenset[str] | None:
    """Return semantic target terms, or an empty set for deictic save requests."""
    match = _EXPLICIT_MEMORY_SAVE.fullmatch(_normalize_save_text(text))
    if not match:
        return None

    target = " ".join(str(match.group("target") or "").split())
    if target in _MEMORY_SAVE_DEICTIC_TARGETS:
        return frozenset()

    terms = {
        token
        for token in re.findall(r"[a-z0-9]+", target)
        if token not in _MEMORY_SAVE_TARGET_STOPWORDS
    }
    return frozenset(terms)


def memory_save_request_matches_signal(text: str, signal: MemorySignal) -> bool:
    """Match a requested fact to an attribute, not just a shared generic word."""
    target_terms = explicit_memory_save_target_terms(text)
    if target_terms is None:
        return False
    if not target_terms:
        return True

    metadata = signal.metadata or {}
    attribute = str(metadata.get("attribute") or "").casefold()
    attribute_terms = set(
        re.findall(r"[a-z0-9]+", attribute.replace("_", " ").replace(".", " "))
    )
    # Explicit canonical attributes take priority over broad overlapping
    # category words such as "location", "relationship" and "work".
    if attribute and attribute_terms.issubset(target_terms):
        return True

    generic_terms = {"location", "place", "fact", "memory", "information"}
    specific_target_terms = target_terms - generic_terms
    if not specific_target_terms:
        return False

    # A location-qualified request may only select another location
    # attribute if the subtype itself also matches. "residence location"
    # must not match "current location" just because both say location.
    location_attributes = {
        "birthplace",
        "origin_location",
        "upbringing_location",
        "residence_location",
        "work_location",
        "current_location",
    }
    if attribute in location_attributes and "location" in target_terms:
        return False

    semantic_text = " ".join(
        str(value or "")
        for value in (
            signal.text,
            signal.signal_type,
            attribute,
            metadata.get("category"),
            metadata.get("semantic_class"),
            metadata.get("relationship_type"),
            metadata.get("goal_type"),
            metadata.get("event_type"),
        )
    ).casefold()
    semantic_terms = set(
        re.findall(r"[a-z0-9]+", semantic_text.replace("_", " ").replace(".", " "))
    )
    return any(
        requested == semantic
        or (
            min(len(requested), len(semantic)) >= 4
            and (requested.startswith(semantic) or semantic.startswith(requested))
        )
        for requested in specific_target_terms
        for semantic in semantic_terms
    )


def classify_explicit_user_memory(text: str) -> list[MemorySignal]:
    """Return high-confidence typed candidates from explicit first-person claims."""

    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return []

    signals: list[MemorySignal] = []

    name_match = _NAME.search(normalized)
    if name_match:
        value = _clean_value(name_match.group(1))
        if value:
            signals.append(
                MemorySignal(
                    text=f"My name is {value}",
                    signal_type="identity_fact",
                    confidence=0.98,
                    scope="user",
                    metadata={
                        "source": "explicit_semantic_rule",
                        "explicit_user_statement": True,
                        "semantic_class": "identity",
                        "category": "identity",
                        "attribute": "preferred_name",
                        "normalized_value": value,
                        "retention_scope": "user_profile",
                    },
                )
            )

    color_match = _FAVORITE_COLOR.search(normalized) or _COLOR_IS_FAVORITE.search(
        normalized
    )
    if color_match:
        value = _clean_value(color_match.group(1)).casefold()
        if value:
            signals.append(
                MemorySignal(
                    text=f"My favorite color is {value}",
                    signal_type="preference",
                    confidence=0.98,
                    scope="user",
                    metadata={
                        "source": "explicit_semantic_rule",
                        "explicit_user_statement": True,
                        "semantic_class": "preference",
                        "category": "preference",
                        "attribute": "favorite_color",
                        "normalized_value": value,
                        "retention_scope": "user_profile",
                        "stability": "long_term",
                    },
                )
            )

    if _INTERVIEW_CANCELLED.search(normalized):
        signals.append(
            MemorySignal(
                text=normalized,
                signal_type="prospective_transition",
                confidence=0.99,
                scope="user",
                metadata={
                    "source": "explicit_semantic_rule",
                    "explicit_user_statement": True,
                    "semantic_class": "prospective_transition",
                    "event_type": "job_interview",
                    "target_state": "cancelled",
                    "transition_reason": "user_reported_cancelled",
                    "retention_scope": "user_profile",
                },
            )
        )
    elif _INTERVIEW_DONE.search(normalized):
        signals.append(
            MemorySignal(
                text=normalized,
                signal_type="prospective_transition",
                confidence=0.98,
                scope="user",
                metadata={
                    "source": "explicit_semantic_rule",
                    "explicit_user_statement": True,
                    "semantic_class": "prospective_transition",
                    "event_type": "job_interview",
                    "target_state": "completed",
                    "transition_reason": "user_reported_completed",
                    "retention_scope": "user_profile",
                },
            )
        )
    elif _JOB_OFFER.search(normalized):
        signals.append(
            MemorySignal(
                text=normalized,
                signal_type="prospective_transition",
                confidence=0.99,
                scope="user",
                metadata={
                    "source": "explicit_semantic_rule",
                    "explicit_user_statement": True,
                    "semantic_class": "prospective_transition",
                    "event_type": "job_interview",
                    "target_state": "completed",
                    "transition_reason": "job_offer_received",
                    "outcome": "job_offer",
                    "retention_scope": "user_profile",
                },
            )
        )

    goal_abandon = _GOAL_ABANDON.search(normalized) or _GOAL_STOPPED.search(normalized)
    if goal_abandon:
        description = _clean_value(goal_abandon.group(1))
        signals.append(
            MemorySignal(
                text=normalized,
                signal_type="goal_transition",
                confidence=0.98,
                scope="user",
                metadata={
                    "source": "explicit_semantic_rule",
                    "explicit_user_statement": True,
                    "semantic_class": "goal_transition",
                    "target_state": "abandoned",
                    "target_description": description or None,
                    "transition_reason": "user_abandoned_goal",
                    "retention_scope": "user_profile",
                },
            )
        )

    open_loop_done = _OPEN_LOOP_DONE.search(normalized)
    if open_loop_done:
        description = _clean_value(open_loop_done.group(1))
        if description:
            signals.append(
                MemorySignal(
                    text=normalized,
                    signal_type="open_loop_transition",
                    confidence=0.97,
                    scope="user",
                    metadata={
                        "source": "explicit_semantic_rule",
                        "explicit_user_statement": True,
                        "semantic_class": "open_loop_transition",
                        "target_state": "completed",
                        "target_description": description,
                        "transition_reason": "user_reported_completed",
                        "retention_scope": "user_profile",
                    },
                )
            )
    else:
        for pattern in _OPEN_LOOP_PATTERNS:
            match = pattern.search(normalized)
            if match:
                description = _clean_value(match.group(1))
                if description:
                    signals.append(
                        MemorySignal(
                            text=normalized,
                            signal_type="open_loop",
                            confidence=0.96,
                            scope="user",
                            metadata={
                                "source": "explicit_semantic_rule",
                                "explicit_user_statement": True,
                                "semantic_class": "open_loop",
                                "loop_type": "unfinished_work",
                                "description": description,
                                "lifecycle_state": "open",
                                "retention_scope": "user_profile",
                            },
                        )
                    )
                break

    interview_match = _INTERVIEW.search(normalized)
    has_prospective_transition = any(
        signal.signal_type == "prospective_transition" for signal in signals
    )
    if interview_match and not has_prospective_transition:
        detail = _clean_value(interview_match.group(1))
        signals.append(
            MemorySignal(
                text=normalized,
                signal_type="prospective_event",
                confidence=0.96,
                scope="user",
                metadata={
                    "source": "explicit_semantic_rule",
                    "explicit_user_statement": True,
                    "semantic_class": "prospective_event",
                    "event_type": "job_interview",
                    "attribute": "job_interview",
                    "temporal_text": detail or None,
                    "retention_scope": "user_profile",
                    "lifecycle_state": "dormant",
                },
            )
        )

    has_goal_transition = any(
        signal.signal_type == "goal_transition" for signal in signals
    )
    for pattern in _GOAL_PATTERNS:
        if has_goal_transition:
            break
        match = pattern.search(normalized)
        if match:
            description = _clean_value(match.group(1))
            if description and not _looks_like_event_duplicate(description, signals):
                signals.append(
                    MemorySignal(
                        text=normalized,
                        signal_type="goal",
                        confidence=0.95,
                        scope="user",
                        metadata={
                            "source": "explicit_semantic_rule",
                            "explicit_user_statement": True,
                            "semantic_class": "goal",
                            "goal_type": "explicit",
                            "description": description,
                            "retention_scope": "user_profile",
                            "lifecycle_state": "active",
                        },
                    )
                )
            break

    signals.extend(classify_general_user_facts(normalized))
    return _dedupe(signals)


def _dedupe(signals: list[MemorySignal]) -> list[MemorySignal]:
    seen: set[tuple[str, str, str]] = set()
    result: list[MemorySignal] = []
    for signal in signals:
        key = (
            signal.signal_type,
            str(signal.metadata.get("attribute") or ""),
            str(
                signal.metadata.get("normalized_value")
                or signal.metadata.get("description")
                or signal.text
            ).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result


def _clean_value(value: str) -> str:
    return " ".join(str(value or "").strip(" \t\n\r.,;:!?").split())


def _looks_like_event_duplicate(
    description: str,
    existing: list[MemorySignal],
) -> bool:
    if not any(signal.signal_type == "prospective_event" for signal in existing):
        return False
    lowered = description.casefold()
    return "interview" in lowered


__all__ = [
    "classify_explicit_user_memory",
    "explicit_memory_save_target_terms",
    "is_explicit_memory_save_request",
    "memory_save_request_matches_signal",
    "is_personal_memory_recall_query",
]
