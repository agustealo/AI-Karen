"""Deterministic semantic memory classification for explicit user statements.

This module owns only memory-candidate semantics. It does not authorize writes,
persist data, rank recall, or infer hidden reasoning. Model-assisted formation
may enrich these candidates later through prompt contracts, but explicit user
statements are classified deterministically first so identity/preferences/goals
remain reliable when NLP models degrade.
"""

from __future__ import annotations

import re

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

    return signals


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


__all__ = ["classify_explicit_user_memory"]
