"""CORTEX capability-routing contract."""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
CAPABILITY_ROUTES: Dict[str, Dict[str, Any]] = {
    "time.current": {
        "triggers": ["what time", "current time", "time in", "timezone"],
        "patterns": [
            r"\bwhat\s+time\s+is\s+it\b",
            r"\bwhat(?:'s|\s+is)\s+the\s+time\b",
            r"\bcurrent\s+time\b",
            r"\btime\s+(?:is\s+it\s+)?in\s+[\w\s,./+-]+$",
            r"\btime\s+now\b",
            r"\btimezone\s+(?:in|for|of)\b",
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
            r"\bfind\s+(?:the\s+)?(?:current|latest|today'?s?)\b",
            r"\b(?:what|which)\s+is\s+the\s+(?:current|latest)\b",
            r"\b(?:latest|current|today'?s?)\s+(?:news|updates?|results?|score|price|release|version)\b",
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
        if any(re.search(pattern, q, flags=re.IGNORECASE) for pattern in patterns):
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


