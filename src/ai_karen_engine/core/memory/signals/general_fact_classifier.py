"""Domain-neutral classification of explicit user facts.

This module handles high-confidence first-person statements that are useful for
longitudinal personalization across work, family, relationships, projects,
skills, routines, interests, and travel. It does not persist anything and it
does not infer hidden traits from weak evidence.
"""

from __future__ import annotations

import re

from .signal_models import MemorySignal


_RELATIONSHIP = re.compile(
    r"(?i)\bmy\s+"
    r"(wife|husband|partner|spouse|mother|mom|father|dad|son|daughter|"
    r"brother|sister|manager|boss|coworker|colleague|friend|client)\s+"
    r"is\s+([A-Za-z][A-Za-z' -]{0,80}?)(?=[.!?,;]|$)"
)
_WORK_AS = re.compile(
    r"(?i)\bi\s+(?:work|am working)\s+as\s+(?:an?\s+)?(.+?)(?=[.!?]|$)"
)
_SELF_ROLE = re.compile(
    r"(?i)\bi(?:'m| am)\s+(?:an?\s+)"
    r"((?:licensed\s+|certified\s+|senior\s+|lead\s+|professional\s+)?"
    r"[A-Za-z][A-Za-z' -]{1,80}?)(?=[.!?,;]|$)"
)
_EMPLOYER = re.compile(
    r"(?i)\bi\s+work\s+(?:at|for)\s+(.+?)(?=[.!?]|$)"
)
_BUSINESS = re.compile(
    r"(?i)\bi\s+(?:own|run|operate)\s+(?:a\s+|an\s+|the\s+)?(.+?)(?=[.!?]|$)"
)
_SKILLED_IN = re.compile(
    r"(?i)\bi(?:'m| am)\s+(?:skilled|experienced|proficient)\s+in\s+(.+?)(?=[.!?]|$)"
)
_KNOW_HOW = re.compile(
    r"(?i)\bi\s+know\s+how\s+to\s+(.+?)(?=[.!?]|$)"
)
_ROUTINE = re.compile(
    r"(?i)\bi\s+(usually|normally|typically)\s+(.+?)(?=[.!?]|$)"
)
_INTERESTED_IN = re.compile(
    r"(?i)\bi(?:'m| am)\s+interested\s+in\s+(.+?)(?=[.!?]|$)"
)
_FOLLOW = re.compile(
    r"(?i)\bi\s+(?:follow|track|watch)\s+(.+?)(?=[.!?]|$)"
)
_PROJECT = re.compile(
    r"(?i)\bi(?:'m| am)\s+(?:working on|building|developing)\s+(.+?)(?=[.!?]|$)"
)
_TRAVEL = re.compile(
    r"(?i)\bi(?:'m| am)\s+(?:planning\s+(?:a\s+)?trip|traveling|travelling|going)\s+"
    r"(?:to\s+)?(.+?)(?=[.!?]|$)"
)


_LOCATION_PATTERNS = (
    ("current_location", "current", re.compile(
        r"(?i)\b(?:i(?:'m| am)\s+(?:currently|right now)\s+in|"
        r"currently\s+i(?:'m| am)\s+in)\s+(.+?)(?=\s+(?:and|but)\s+(?:i\b|born\b)|[,.!?;]|$)"
    )),
    ("residence_location", "residence", re.compile(
        r"(?i)\bi\s+(?:live|reside)\s+in\s+(.+?)(?=\s+(?:and|but)\s+(?:i\b|born\b)|[,.!?;]|$)"
    )),
    ("residence_location", "residence", re.compile(
        r"(?i)\bi(?:'m| am)\s+based\s+in\s+(.+?)(?=\s+(?:and|but)\s+(?:i\b|born\b)|[,.!?;]|$)"
    )),
    ("birthplace", "birthplace", re.compile(
        r"(?i)\b(?:i\s+(?:was\s+)?born\s+in|born\s+in)\s+(.+?)(?=\s+(?:and|but)\s+(?:i\b|born\b)|[,.!?;]|$)"
    )),
    ("origin_location", "origin", re.compile(
        r"(?i)\bi(?:'m| am)\s+(?:originally\s+)?from\s+(.+?)(?=\s+(?:and|but)\s+(?:i\b|born\b)|[,.!?;]|$)"
    )),
)


def classify_general_user_facts(text: str) -> list[MemorySignal]:
    """Return high-confidence explicit facts without domain-specific persistence."""

    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return []

    signals: list[MemorySignal] = []

    for attribute, location_type, pattern in _LOCATION_PATTERNS:
        for match in pattern.finditer(normalized):
            value = _clean(match.group(1))
            if not value:
                continue
            signals.append(
                _profile_fact(
                    text=match.group(0),
                    category="location",
                    attribute=attribute,
                    value=value,
                    semantic_class="identity" if location_type in {"birthplace", "origin"} else "location",
                    confidence=0.98,
                    extra={
                        "location_type": location_type,
                        "stability": "short_term" if location_type == "current" else "long_term",
                    },
                )
            )

    relationship = _RELATIONSHIP.search(normalized)
    if relationship:
        role = _clean(relationship.group(1)).casefold()
        person = _clean(relationship.group(2))
        if person and _looks_like_person_name(person):
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="relationship",
                    attribute=f"relationship.{role}",
                    value=person,
                    semantic_class="relationship",
                    confidence=0.98,
                    extra={"relationship_type": role},
                )
            )

    work_as = _WORK_AS.search(normalized)
    if work_as:
        role = _clean(work_as.group(1))
        if role:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="work",
                    attribute="occupation",
                    value=role,
                    semantic_class="work",
                    confidence=0.97,
                )
            )
    else:
        self_role = _SELF_ROLE.search(normalized)
        if self_role:
            role = _clean(self_role.group(1))
            if _plausible_role(role):
                signals.append(
                    _profile_fact(
                        text=normalized,
                        category="work",
                        attribute="occupation",
                        value=role,
                        semantic_class="work",
                        confidence=0.92,
                    )
                )

    employer = _EMPLOYER.search(normalized)
    if employer:
        organization = _clean(employer.group(1))
        if organization:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="work",
                    attribute="employer",
                    value=organization,
                    semantic_class="work",
                    confidence=0.97,
                )
            )

    business = _BUSINESS.search(normalized)
    if business:
        value = _clean(business.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="work",
                    attribute=f"business.{_slug(value)}",
                    value=value,
                    semantic_class="business",
                    confidence=0.95,
                )
            )

    skill_match = _SKILLED_IN.search(normalized)
    if skill_match:
        value = _clean(skill_match.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="skill",
                    attribute=f"skill.{_slug(value)}",
                    value=value,
                    semantic_class="skill",
                    confidence=0.95,
                )
            )

    know_how = _KNOW_HOW.search(normalized)
    if know_how:
        value = _clean(know_how.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="skill",
                    attribute=f"skill.{_slug(value)}",
                    value=value,
                    semantic_class="skill",
                    confidence=0.93,
                )
            )

    routine = _ROUTINE.search(normalized)
    if routine:
        activity = _clean(routine.group(2))
        if activity:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="routine",
                    attribute=f"routine.{_slug(activity)}",
                    value=activity,
                    semantic_class="routine",
                    confidence=0.92,
                    extra={"frequency_word": routine.group(1).casefold()},
                )
            )

    interested = _INTERESTED_IN.search(normalized)
    if interested:
        value = _clean(interested.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="interest",
                    attribute=f"interest.{_slug(value)}",
                    value=value,
                    semantic_class="interest",
                    confidence=0.91,
                )
            )

    followed = _FOLLOW.search(normalized)
    if followed:
        value = _clean(followed.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="interest",
                    attribute=f"interest.{_slug(value)}",
                    value=value,
                    semantic_class="interest",
                    confidence=0.88,
                    extra={"interest_mode": "tracked"},
                )
            )

    project = _PROJECT.search(normalized)
    if project:
        value = _clean(project.group(1))
        if value:
            signals.append(
                _profile_fact(
                    text=normalized,
                    category="project",
                    attribute=f"project.{_slug(value)}",
                    value=value,
                    semantic_class="project",
                    confidence=0.94,
                    extra={"lifecycle_state": "active"},
                )
            )

    travel = _TRAVEL.search(normalized)
    if travel:
        detail = _clean(travel.group(1))
        if detail:
            signals.append(
                MemorySignal(
                    text=normalized,
                    signal_type="prospective_event",
                    confidence=0.94,
                    scope="user",
                    metadata={
                        "source": "explicit_general_fact_rule",
                        "explicit_user_statement": True,
                        "semantic_class": "prospective_event",
                        "event_type": "travel",
                        "attribute": "travel_plan",
                        "temporal_text": detail,
                        "retention_scope": "user_profile",
                        "lifecycle_state": "dormant",
                    },
                )
            )

    return _dedupe(signals)


def _profile_fact(
    *,
    text: str,
    category: str,
    attribute: str,
    value: str,
    semantic_class: str,
    confidence: float,
    extra: dict[str, object] | None = None,
) -> MemorySignal:
    metadata: dict[str, object] = {
        "source": "explicit_general_fact_rule",
        "explicit_user_statement": True,
        "semantic_class": semantic_class,
        "category": category,
        "attribute": attribute,
        "normalized_value": value,
        "retention_scope": "user_profile",
        "stability": "long_term",
    }
    if extra:
        metadata.update(extra)
    return MemorySignal(
        text=text,
        signal_type="profile_fact",
        confidence=confidence,
        scope="user",
        metadata=metadata,
    )


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip(" \t\n\r.,;:!?").split())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return normalized[:80] or "item"


def _plausible_role(value: str) -> bool:
    """Promote durable self-roles, not temporary descriptions."""

    lowered = value.casefold()
    role_terms = {
        "accountant",
        "analyst",
        "architect",
        "artist",
        "carpenter",
        "chef",
        "consultant",
        "contractor",
        "dad",
        "designer",
        "developer",
        "doctor",
        "driver",
        "electrician",
        "engineer",
        "entrepreneur",
        "father",
        "founder",
        "lawyer",
        "manager",
        "marketer",
        "mechanic",
        "mother",
        "nurse",
        "owner",
        "parent",
        "plumber",
        "researcher",
        "salesperson",
        "student",
        "teacher",
        "technician",
        "writer",
    }
    tokens = {
        token.strip(" ,./_-").casefold()
        for token in value.split()
        if token.strip(" ,./_-")
    }
    return bool(tokens & role_terms)


def _looks_like_person_name(value: str) -> bool:
    tokens = [token for token in value.split() if token]
    if not tokens or len(tokens) > 5:
        return False
    return all(token[0].isupper() for token in tokens if token[0].isalpha())


def _dedupe(signals: list[MemorySignal]) -> list[MemorySignal]:
    seen: set[tuple[str, str, str]] = set()
    result: list[MemorySignal] = []
    for signal in signals:
        key = (
            signal.signal_type,
            str(signal.metadata.get("attribute") or ""),
            str(signal.metadata.get("normalized_value") or signal.text).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result


__all__ = ["classify_general_user_facts"]
