"""CORTEX capability-routing contract."""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
CAPABILITY_ROUTES: Dict[str, Dict[str, Any]] = {
    "time.current": {
        "triggers": ["what time", "current time", "time in", "timezone"],
        "patterns": [
            r"^what\s+time\s+is\s+it(?:\s+right\s+now)?(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^what(?:'s|\s+is)\s+the\s+(?:current\s+)?time(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^current\s+time(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^time\s+now(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^timezone\s+(?:in|for|of)\s+.+[?!.]*$",
        ],
        "required_capability": "time_query",
        "preferred_plugin": "time-query",
        "handler": "time_tool",
        "fallback_tool": "time",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "search.general": {
        "triggers": ["search the internet", "look online", "find current", "latest", "web search"],
        "patterns": [
            r"\bsearch\s+(?:the\s+)?(?:web|internet|online)\b",
            r"\bweb\s+search\b",
            r"\blook\s+(?:it\s+)?up\s+online\b",
            r"\blook\s+online\s+(?:for|at)\b",
            r"^find\s+(?:the\s+)?(?:current|latest|today'?s?)\s+(?:(?:[\w.+#-]+\s+){0,4})(?:news|updates?|results?|score|price|release|version|status|information)[?!.]*$",
            r"^(?:what(?:'s|\s+is)|which\s+is)\s+the\s+(?:current|latest)\s+(?:(?:[\w.+#-]+\s+){0,4})(?:news|update|result|score|price|release|version|status)[?!.]*$",
            r"^(?:what(?:'s|\s+is)|which\s+is)\s+the\s+(?:current|latest)\s+(?:news|update|result|score|price|release|version|status)\s+(?:about|of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3}[?!.]*$",
            r"^(?:latest|current|today'?s?)\s+(?:news|updates?|results?|score|price|release|version|status)(?:\s+(?:about|of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3})?[?!.]*$",
        ],
        "required_capability": "web.search",
        "preferred_plugin": "intelligent-search",
        "handler": "web_search",
        "plugin_mode": "general",
        "fallback_tool": "search",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "search.weather": {
        "triggers": ["weather", "forecast", "temperature", "rain today"],
        "patterns": [
            r"^what(?:'s|\s+is)\s+(?:the\s+)?weather(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"\bwhat\s+will\s+the\s+weather\s+be\s+(?:in|for)\s+.+$",
            r"^how(?:'s|\s+is)\s+(?:the\s+)?weather(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^what(?:\x27s|\\s+is)\\s+(?:the\\s+)?weather\\s+forecast(?:\\s+(?:in|for)\\s+.+)?[?!.]*$",
            r"^weather[?!.]*$",
            r"\bweather\s+(?:in|for|today|tonight|tomorrow|this\s+week)\b",
            r"^forecast\s+(?:today|tonight|tomorrow|this\s+week)[?!.]*$",
            r"\b(?:current|today'?s?|tonight'?s?|tomorrow'?s?)\s+(?:weather|forecast|temperature)\b",
            r"\btemperature\s+(?:in|at|outside|today|tonight|tomorrow)\b",
            r"\b(?:will|is|does)\s+it\s+(?:rain|snow)\b",
            r"\b(?:rain|snow|storm|precipitation)\s+(?:today|tonight|tomorrow|this\s+week)\b",
        ],
        "required_capability": "web.search",
        "preferred_plugin": "intelligent-search",
        "handler": "web_search",
        "plugin_mode": "weather",
        "fallback_tool": "search",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
}


_CONCEPTUAL_TIME_SUBJECTS = {
    "literature",
    "mechanics",
    "physics",
    "systems",
    "computing",
    "philosophy",
    "music",
    "history",
    "theory",
}


_NON_LOCATION_LEADERS = {
    "a",
    "an",
    "my",
    "our",
    "the",
    "their",
    "this",
    "that",
    "your",
}


_LOCATION_CONNECTORS = {
    "al",
    "bin",
    "da",
    "das",
    "de",
    "del",
    "do",
    "dos",
    "du",
    "la",
    "las",
    "le",
    "los",
    "of",
    "the",
    "van",
    "von",
}


def _looks_like_location_phrase(value: str) -> bool:
    raw = " ".join((value or "").strip().split()).strip(" ,")
    if not raw or len(raw) > 160:
        return False

    # IANA timezone and common UTC/GMT offset forms are explicit clock targets.
    if re.fullmatch(r"[A-Za-z_]+/[A-Za-z_+-]+", raw):
        return True
    if re.fullmatch(r"(?:UTC|GMT)(?:[+-]\d{1,2}(?::\d{2})?)?", raw, re.IGNORECASE):
        return True

    tokens = [
        token.strip(".'’_-")
        for token in re.split(r"[\s,]+", raw)
        if token.strip(".'’_-")
    ]
    if not tokens or any(not token[0].isalpha() for token in tokens):
        return False

    if re.fullmatch(r"(?:Q[1-4]|FY\d{2,4})", raw, flags=re.IGNORECASE):
        return False

    lowered = [token.lower() for token in tokens]
    if lowered[0] in _NON_LOCATION_LEADERS:
        # An article may belong to a place name. Explicit "in" and weather
        # forms are case-insensitive; ambiguous "for" requests are validated
        # separately by _clock_target_is_location.
        article_led_place = lowered[0] == "the" and len(tokens) > 1
        if not article_led_place:
            return False
    if len(tokens) == 1:
        return lowered[0] not in _CONCEPTUAL_TIME_SUBJECTS

    if any(token in _CONCEPTUAL_TIME_SUBJECTS for token in lowered):
        return False
    return True


def _explicit_location_target(query: str) -> Optional[str]:
    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    match = re.search(
        r"\b(?:in|for|of)\s+(?P<location>.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    location = re.sub(
        r"[,\s]+right\s+now$",
        "",
        match.group("location"),
        flags=re.IGNORECASE,
    ).strip(" ,")
    return location or None


def _clock_target_is_location(query: str, target: str) -> bool:
    if not _looks_like_location_phrase(target):
        return False

    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    relation = re.search(
        r"\b(?P<relation>in|for|of)\s+.+$",
        raw,
        flags=re.IGNORECASE,
    )
    if not relation or relation.group("relation").lower() != "for":
        return True

    # "for" is ambiguous in ordinary English ("for lunch", "for work").
    # Keep explicit zone forms, multi-word place names, and title-cased
    # one-word place names; lowercase shorthand remains supported via "in".
    if re.fullmatch(r"[A-Za-z_]+/[A-Za-z_+-]+", target):
        return True
    if re.fullmatch(
        r"(?:UTC|GMT)(?:[+-]\d{1,2}(?::\d{2})?)?",
        target,
        re.IGNORECASE,
    ):
        return True
    tokens = [token for token in re.split(r"[\s,]+", target) if token]
    if not tokens:
        return False

    # For the ambiguous "for" relation, require a positively shaped place
    # name instead of accepting arbitrary multi-word phrases such as
    # "lunch today" or "team meeting". Lowercase shorthand remains available
    # through the unambiguous "in <location>" grammar above.
    return all(
        token.lower() in _LOCATION_CONNECTORS
        or token[:1].isupper()
        or token.isupper()
        for token in tokens
    )


def _looks_like_shorthand_time(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?")
    match = re.fullmatch(r"time\s+in\s+(?P<location>.+)", raw, flags=re.IGNORECASE)
    if not match:
        return False
    return _looks_like_location_phrase(match.group("location"))


def _looks_like_forecast_target(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    match = re.fullmatch(r"forecast\s+(?:for|in)\s+(.+)", raw, re.IGNORECASE)
    if not match:
        return False
    location = match.group(1).strip()
    # "forecast for" is ambiguous. Require a resolvable IANA zone or
    # positively shaped proper place name rather than guessing from prose.
    if not _looks_like_location_phrase(location):
        return False
    if re.fullmatch(r"[A-Za-z_]+/[A-Za-z_+-]+", location):
        return True
    tokens = location.split()
    return bool(tokens and all(
        token.lower() in _LOCATION_CONNECTORS or token[:1].isupper()
        for token in tokens
    ))


def _looks_like_location_first_weather(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    match = re.fullmatch(
        r"(?P<location>.+?)\s+(?:weather|forecast)",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    location = match.group("location")
    suffix = raw[match.end("location"):].strip().lower()
    # A bare forecast is ambiguous (finance, elections, demand). Require a
    # preposition or explicit weather noun before using the weather executor.
    if suffix == "forecast":
        return False
    return _looks_like_location_phrase(location)


@dataclass(slots=True)
class CapabilityDecision:
    intent: str
    confidence: float
    requires_tool: bool
    requires_live_data: bool
    subtype: Optional[str] = None
    capability: Optional[str] = None
    preferred_plugin: Optional[str] = None
    handler: Optional[str] = None
    allow_llm_only: bool = True
    requires_chat_capable_model: bool = True
    missing_requirements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_capability_decision(query: str, *, confidence: float = 0.9) -> CapabilityDecision:
    q = " ".join(query.lower().split())

    # Specialized routes use bounded intent patterns, not substring hits. This
    # keeps deterministic fallback available when Intelligence is offline while
    # avoiding hijacks such as "what time complexity..." or incidental "latest".
    for intent, config in CAPABILITY_ROUTES.items():
        patterns = config.get("patterns", [])
        matched = any(
            re.search(pattern, q, flags=re.IGNORECASE)
            for pattern in patterns
        )
        if intent == "time.current":
            matched = matched or _looks_like_shorthand_time(query)
            target = _explicit_location_target(query)
            if matched and target is not None:
                matched = _clock_target_is_location(query, target)
        if intent == "search.weather":
            matched = (
                matched
                or _looks_like_location_first_weather(query)
                or _looks_like_forecast_target(query)
            )
        if matched:
            return CapabilityDecision(
                intent=intent,
                confidence=confidence,
                requires_tool=True,
                requires_live_data=bool(config.get("requires_live_data", False)),
                capability=config.get("required_capability"),
                preferred_plugin=config.get("preferred_plugin"),
                handler=config.get("handler"),
                requires_chat_capable_model=bool(config.get("allow_llm_only", False)),
                allow_llm_only=bool(config.get("allow_llm_only", False)),
            )

    # Detect broad conversational subtypes
    subtype = None
    if any(keyword in q for keyword in ["joke", "humor", "laugh", "funny", "comedy"]):
        subtype = "humor_request"
    elif any(keyword in q for keyword in ["fun fact", "trivia", "interesting fact"]):
        subtype = "trivia_request"

    return CapabilityDecision(
        intent="general.chat",
        subtype=subtype,
        confidence=confidence,
        requires_tool=False,
        requires_live_data=False,
        allow_llm_only=True,
        requires_chat_capable_model=True,
    )


