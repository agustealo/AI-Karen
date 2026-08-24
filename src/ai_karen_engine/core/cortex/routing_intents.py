"""CORTEX capability-routing contract."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
CAPABILITY_ROUTES: Dict[str, Dict[str, Any]] = {
    "time.current": {
        "triggers": ["what time", "current time", "time in", "timezone"],
        "required_capability": "time_query",
        "preferred_plugin": "time-query",
        "handler": "time_tool",
        "fallback_tool": "time",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "search.general": {
        "triggers": ["search the internet", "look online", "find current", "latest", "web search"],
        "required_capability": "internet_search",
        "preferred_plugin": "intelligent-search",
        "handler": "web_search",
        "plugin_mode": "general",
        "fallback_tool": "search",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "search.weather": {
        "triggers": ["weather", "forecast", "temperature", "rain today"],
        "required_capability": "internet_search",
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
    q = query.lower().strip()
    
    # Check specialized capability routes first
    for intent, config in CAPABILITY_ROUTES.items():
        if any(trigger in q for trigger in config.get("triggers", [])):
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


