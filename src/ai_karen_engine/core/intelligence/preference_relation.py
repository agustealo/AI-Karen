"""Open-vocabulary interpretation of first-person favorite relationships.

This intelligence-owned, side-effect-free grammar recognizes the *relation*
"favorite" rather than maintaining a catalog of favorite categories. It
does not create memories, authorize retention, or infer implicit preferences.
More complex claims are left for the governed semantic/model extraction path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FAVORITE = r"fav(?:ou?rite)?"
_DOMAIN = r"[a-z][a-z0-9'/-]*(?:\s+[a-z][a-z0-9'/-]*){0,4}?"
_PERIOD = r"this\s+(?:week|month|season|year)|today|right\s+now|at\s+the\s+moment"
_FORWARD = re.compile(
    rf"\bmy\s+{_FAVORITE}\s+(?P<domain>{_DOMAIN})"
    rf"(?:\s+(?P<period>{_PERIOD}))?\s+(?:is|are)\s+"
    r"(?P<value>[^\n.!?;,]{1,120})", re.IGNORECASE,
)
_REVERSE = re.compile(
    rf"(?P<value>[^\n.!?;,]{{1,120}}?)\s+(?:is|are)\s+my\s+{_FAVORITE}\s+"
    rf"(?P<domain>{_DOMAIN})(?:\s+(?P<period>{_PERIOD}))?"
    r"(?=\s+now\b|[\n.!?;,]|$)", re.IGNORECASE,
)
# Resolve an *explicit* anaphoric favorite assertion only when the same user
# has supplied the referent in the preceding clause. No arbitrary pronoun
# resolution or category-specific vocabulary is used.
_DEICTIC = re.compile(
    rf"\bi\s+(?:just\s+|really\s+)?(?:love|like|adore)\s+"
    r"(?:the\s+\w+\s+)?(?P<value>[^\n.!?;,]{1,70}?)\s*[,;]\s*"
    r"(?P<hedge>i\s+(?:think|guess|feel)\s+)?"
    r"(?:it\s+is|it's|its|that\s+is|that's)\s+"
    rf"my\s+{_FAVORITE}\s+(?P<domain>{_DOMAIN})"
    rf"(?:\s+(?P<period>{_PERIOD}))?"
    r"(?=\s+now\b|[\n.!?;,]|$)", re.IGNORECASE,
)
_QUESTION = re.compile(
    rf"^(?:(?:what(?:\s+is|'s|s)?|which|who(?:\s+is|'s|s)?)\s+"
    rf"(?:is\s+)?my|do\s+you\s+remember\s+my)\s+{_FAVORITE}\s+"
    r"(?P<domain>[a-z][a-z0-9'/-]*(?:\s+[a-z][a-z0-9'/-]*){0,4})\s*$",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(r"^(?:not\b|never\b|no\s+longer\b|none\b)", re.I)
_HEDGE = re.compile(r"\bi\s+(?:think|guess|feel|suspect)\b|\b(?:maybe|perhaps|might|possibly)\b", re.I)
_REPORTED = re.compile(
    r"\b(?:he|she|they|someone|my\s+\w+)\s+(?:said|says|thinks|claims)\b",
    re.I,
)
_LEADING = re.compile(r"^(?:(?:actually|no|well|now)\b\s*[,;]?\s*)+", re.I)
_UNSUPPORTED_DOMAIN = frozenset({"what", "who", "where", "when", "why", "how", "thing"})


@dataclass(frozen=True, slots=True)
class FavoriteAssertion:
    attribute: str
    domain: str
    value: str
    modality: str
    temporal_scope: str | None
    explicit_correction: bool
    evidence_text: str


def favorite_attribute(domain: str) -> str | None:
    """One canonical attribute per *open-ended* favorite domain."""
    cleaned = " ".join(str(domain).casefold().replace("colour", "color").split())
    terms = cleaned.split()
    if not terms or len(terms) > 5 or any(
        token in _UNSUPPORTED_DOMAIN or token in {"my", "your", "their", "and", "or"}
        for token in terms
    ):
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return f"favorite_{slug}" if slug and len(slug) <= 100 else None


def requested_favorite_attribute(text: str) -> str | None:
    """Resolve only a single explicit user-owned favorite question."""
    q = " ".join(str(text or "").replace("’", "'").strip().split()).strip(" ?.!")
    match = _QUESTION.fullmatch(q)
    if not match:
        return None
    return favorite_attribute(match.group("domain"))


def extract_favorite_assertion(text: str) -> FavoriteAssertion | None:
    """Extract only clearly attributable assertions, without granting writes.

    Tentative and explicitly time-bounded statements are marked so formation
    cannot promote them into unrestricted long-term profile facts.
    """
    utterance = " ".join(str(text or "").replace("’", "'").strip().split())
    if not utterance or len(utterance) > 500 or any(
        quote in utterance for quote in ('"', "“", "”", "‘", "’")
    ):
        return None
    # Our bounded clause grammar stops at periods. Refuse email and dotted
    # address-like values rather than silently extracting a truncated secret
    # that the existing formation privacy detector can no longer recognize.
    if re.search(r"\b[\w.+-]+@[\w.-]+\b|\b\d{1,3}(?:\.\d{1,3}){2,}\b", utterance):
        return None

    for pattern in (_DEICTIC, _FORWARD, _REVERSE):
        match = pattern.search(utterance)
        if not match:
            continue
        prefix = utterance[:match.start()]
        if _REPORTED.search(prefix) or re.search(r"\b(?:used to|not|never)\s*$", prefix, re.I):
            continue
        # A plain occurrence of "my favorite..." embedded in someone's
        # story must not be converted to the current user's own assertion.
        if pattern is _FORWARD and prefix.strip() and not re.search(
            r"(?:^|[,;.!?]\s*)(?:i\s+(?:think|guess|feel)\s+|actually\s*[,;]?\s*|no\s*[,;]?\s*|i\s+.*?[,;]\s*(?:i\s+(?:think|guess|feel)\s+)?)$",
            prefix, re.I,
        ):
            continue

        domain = " ".join(match.group("domain").split())
        attribute = favorite_attribute(domain)
        if not attribute:
            continue
        value = " ".join(match.group("value").strip().split())
        # Negated values must be rejected *before* trimming discourse markers.
        # Otherwise "no longer" could be mistaken for a leading "no".
        if _NEGATIVE.match(value):
            continue
        value = _LEADING.sub("", value).strip()
        # An uncertainty marker inside a reverse-form value describes
        # modality, not the object.
        value_hedged = bool(re.match(r"^i\s+(?:think|guess|feel|suspect)\s+", value, re.I))
        if value_hedged:
            value = re.sub(r"^i\s+(?:think|guess|feel|suspect)\s+", "", value, flags=re.I)
        if not value or _NEGATIVE.match(value):
            continue
        if value.casefold() in {"it", "its", "this", "that", "they", "them", "my", "your"}:
            continue
        if _REPORTED.search(value) or " is my " in value.casefold():
            continue
        if attribute == "favorite_color":
            value = value.casefold()  # Keep existing persisted color normalization.
        if len(value) > 120:
            continue

        temporal = match.groupdict().get("period")
        if temporal:
            temporal = " ".join(temporal.casefold().split())
        # A deictic "I think it's my favorite" remains uncertain, even
        # when the user explicitly names the object in the prior clause.
        preceding = utterance[:match.start()] if pattern is not _DEICTIC else ""
        uncertain = bool(value_hedged or match.groupdict().get("hedge") or _HEDGE.search(preceding))
        correction = bool(
            re.search(r"\bactually\b", utterance[:match.end()], re.I)
            or re.search(r"\bnow\b", utterance[match.start():match.end()+5], re.I)
        )
        return FavoriteAssertion(
            attribute=attribute,
            domain=domain.casefold().replace("colour", "color"),
            value=value,
            modality="uncertain" if uncertain else "asserted",
            temporal_scope=temporal,
            explicit_correction=correction,
            evidence_text=match.group(0),
        )
    return None


__all__ = [
    "FavoriteAssertion", "favorite_attribute", "requested_favorite_attribute",
    "extract_favorite_assertion",
]
