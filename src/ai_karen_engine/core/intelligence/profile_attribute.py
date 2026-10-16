"""Canonical profile attribute interpretation without modifying user language.

This identifies the requested fact only. It never changes user text, grants recall,
infers a fact, or bypasses tenant/consent/validity checks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .preference_relation import requested_favorite_attribute


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
        rf"my\s+{_GAP}name\s+is\s+(?:what|who)",
        rf"what\s+{_GAP}am\s+i\s+{_GAP}called",
        rf"what\s+{_GAP}do\s+(?:you|people|they)\s+call\s+me",
    )),
    ("upbringing_location", (
        rf"where\s+{_GAP}do\s+i\s+{_GAP}grow\s+up",
        rf"where\s+{_GAP}i\s+{_GAP}grew\s+up",
        rf"where\s+{_GAP}did\s+i\s+{_GAP}grow\s+up",
        rf"(?:what(?:\s+is|'s|s))\s+{_GAP}my\s+{_GAP}upbringing",
    )),
    ("origin_location", (
        rf"where\s+{_GAP}(?:am\s+i|i'm|im)\s+from",
        rf"where\s+did\s+i\s+{_GAP}say\s+(?:i'm|i\s+am|im)\s+from",
    )),
    ("birthplace", (
        rf"where\s+{_GAP}was\s+i\s+born(?:\s+at)?",
        rf"(?:what(?:\s+is|'s|s)|tell\s+me)\s+{_GAP}my\s+birthplace",
    )),
    ("residence_location", (rf"where\s+{_GAP}do\s+i\s+{_GAP}live", rf"where\s+{_GAP}am\s+i\s+based")),
    ("work_location", (rf"where\s+{_GAP}do\s+i\s+{_GAP}work", rf"(?:what(?:\s+is|'s|s))\s+{_GAP}my\s+workplace")),
    ("current_location", (rf"where\s+{_GAP}am\s+i\s+(?:currently|right\s+now)",)),
)


_PROFILE_SUMMARY = re.compile(
    r"\b(?:who\s+am\s+i|(?:tell|describe|remind)\s+me\s+(?:more\s+)?about\s+myself|"
    r"what\s+do\s+you\s+(?:know|remember)\s+about\s+me)\b"
)


def is_profile_summary_request(text: str) -> bool:
    """Detect explicit user-profile summary intent, including mixed requests."""
    return bool(_PROFILE_SUMMARY.search(normalize_personal_query(text)))


def requested_profile_attribute(text: str) -> str | None:
    """Resolve one unambiguous attribute, independent of expressive wording."""
    if is_profile_summary_request(text):
        return None
    favorite = requested_favorite_attribute(text)
    if favorite:
        return favorite
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
    if is_profile_summary_request(text):
        return None
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
            previous = normalize_personal_query(str(item.get("content") or "")).strip(" ?.!")
            if previous == "my name":
                return "preferred_name"
            return requested_profile_attribute(previous)
    return None


@dataclass(frozen=True, slots=True)
class ProfileQueryIntent:
    """CORTEX/Intelligence-owned meaning of a personal recall question.

    A qualifier names an exact persisted projection ID, never a guessed
    project-name-to-ID relationship. Unsupported temporal/contextual requests
    must not be silently rewritten into a global/current profile question.
    """

    attribute: str | None
    qualifiers: tuple[tuple[str, str], ...] = ()
    unsupported_context: str | None = None


_EXPLICIT_PROFILE_SCOPE = re.compile(
    r"^(?P<base>.+?)\s+(?:for|in)\s+(?P<kind>project|task)\s+"
    r"(?P<identity>[a-z0-9][a-z0-9_-]{0,63})$"
)
_HISTORICAL_PROFILE_SUFFIX = re.compile(
    r"\s+(?:last\s+(?:year|month|week)|yesterday|previously|in\s+(?:19|20)\d{2})$"
)
_CONTEXTUAL_PROFILE_SUFFIX = re.compile(r"\s+(?:for|in|on)\s+\S.+$")


def requested_profile_query(text: str) -> ProfileQueryIntent:
    """Interpret exact ID scope while explicitly refusing ambiguous references.

    This is a narrow deterministic contract. Free-form named project
    disambiguation and historical recall require governed source resolution;
    neither can be fabricated by a chat request or an inference heuristic.
    """
    query = normalize_personal_query(text).strip(" ?.!")
    if not query or is_profile_summary_request(query):
        return ProfileQueryIntent(None)

    historical = _HISTORICAL_PROFILE_SUFFIX.search(query)
    if historical:
        base = query[:historical.start()]
        attribute = requested_profile_attribute(base)
        return ProfileQueryIntent(
            attribute=attribute,
            unsupported_context="historical" if attribute else None,
        )

    scoped = _EXPLICIT_PROFILE_SCOPE.fullmatch(query)
    if scoped:
        attribute = requested_profile_attribute(scoped.group("base"))
        if attribute:
            key = "project_id" if scoped.group("kind") == "project" else "task_id"
            return ProfileQueryIntent(
                attribute=attribute,
                qualifiers=((key, scoped.group("identity")),),
            )

    residual = _CONTEXTUAL_PROFILE_SUFFIX.search(query)
    if residual:
        base = query[:residual.start()]
        attribute = requested_profile_attribute(base)
        if attribute:
            return ProfileQueryIntent(
                attribute=attribute, unsupported_context="unresolved_scope",
            )

    return ProfileQueryIntent(requested_profile_attribute(query))


__all__ = ["normalize_personal_query", "requested_profile_attribute", "referenced_profile_attribute", "is_profile_summary_request", "ProfileQueryIntent", "requested_profile_query"]
