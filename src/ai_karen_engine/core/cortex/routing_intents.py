"""CORTEX capability-routing contract."""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
CAPABILITY_ROUTES: Dict[str, Dict[str, Any]] = {
    "time.current": {
        "triggers": ["what time", "current time", "time in", "timezone"],
        "patterns": [
            r"^what\s+time\s+is\s+it(?:\s+(?:in|for)\s+.+)?[?!.]*$",
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
            r"^(?:what|which)\s+is\s+the\s+(?:current|latest)\s+(?:(?:[\w.+#-]+\s+){0,4})(?:news|update|result|score|price|release|version|status)[?!.]*$",
            r"^(?:what|which)\s+is\s+the\s+(?:current|latest)\s+(?:news|update|result|score|price|release|version|status)\s+(?:of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3}[?!.]*$",
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
            r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?weather\b",
            r"\bwhat\s+will\s+the\s+weather\s+be\s+(?:in|for)\s+.+$",
            r"\bhow(?:'s|\s+is)\s+(?:the\s+)?weather\b",
            r"^weather\b",
            r"\bweather\s+(?:in|for|today|tonight|tomorrow|this\s+week)\b",
            r"\bforecast\s+(?:for|in|today|tonight|tomorrow|this\s+week)\b",
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

    # A one-token shorthand must look like a proper place name. This keeps
    # "Detroit weather" while rejecting conceptual subjects such as
    # "election forecast" or "time in literature".
    if len(tokens) == 1:
        return (
            tokens[0].lower() not in _CONCEPTUAL_TIME_SUBJECTS
            and (
                tokens[0][:1].isupper()
                or tokens[0][:1].lower() == tokens[0][:1].upper()
            )
        )

    # Comma-delimited place strings and title-cased proper names are positive
    # location shapes. Lowercase conceptual phrases are deliberately rejected.
    if "," in raw:
        return True
    return all(
        token[:1].isupper()
        or token[:1].lower() == token[:1].upper()
        or (index > 0 and token.lower() in _LOCATION_CONNECTORS)
        for index, token in enumerate(tokens)
    )


def _looks_like_shorthand_time(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?")
    match = re.fullmatch(r"time\s+in\s+(?P<location>.+)", raw, flags=re.IGNORECASE)
    if not match:
        return False
    return _looks_like_location_phrase(match.group("location"))


def _looks_like_location_first_weather(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?")
    match = re.fullmatch(
        r"(?P<location>.+?)\s+(?:weather|forecast)",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    return _looks_like_location_phrase(match.group("location"))


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
        if intent == "search.weather":
            matched = matched or _looks_like_location_first_weather(query)
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


