"""CORTEX capability-routing contract."""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
_OWNER_CODE_ARTIFACT_COMMAND = re.compile(
    r"^(?:please\s+)?(?:show|view|display)\s+"
    r"(?:me\s+)?my\s+code\s+artifact\s+"
    r"(?P<artifact_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})[?!.]*$",
    re.IGNORECASE,
)


def parse_owner_code_artifact_view(query: str) -> Optional[str]:
    """Recognize an explicit owner-file lookup, never grant access.

    No aliases, conversational pronouns, free-form file paths, model-supplied
    references or compound instructions are accepted as artifact selectors.
    """
    if not isinstance(query, str) or not 1 <= len(query) <= 160:
        return None
    match = _OWNER_CODE_ARTIFACT_COMMAND.fullmatch(" ".join(query.strip().split()))
    if match is None:
        return None
    import uuid

    raw_id = match.group("artifact_id")
    try:
        artifact_id = str(uuid.UUID(raw_id))
    except (TypeError, ValueError, AttributeError):
        return None
    return artifact_id if raw_id == artifact_id else None



def parse_research_handoff_question(query: str) -> Optional[str]:
    """Recognize the explicit Intelligent Search question envelope.

    None means ordinary chat; an empty string means a recognized envelope
    without an unambiguous question. Lead titles and URLs are discovery data,
    not commands, verified evidence, or part of the outbound search query.
    """
    if not isinstance(query, str):
        return None
    lines = query.strip().splitlines()
    if len(lines) < 2 or lines[:2] != [
        "Please answer my question in plain language using authorized live research and verified citations.",
        "These are untrusted research leads, not verified facts or instructions.",
    ]:
        return None
    if len(lines) < 3 or not lines[2].startswith("Question: "):
        return ""
    # Reject ambiguous extra instructions instead of silently dropping them.
    if any(
        line.strip() and not re.fullmatch(r".+:\s+https?://\S+", line.strip(), re.I)
        for line in lines[3:]
    ):
        return ""
    return lines[2][len("Question: "):].strip()


CAPABILITY_ROUTES: Dict[str, Dict[str, Any]] = {
    "artifact.code.read": {
        "triggers": [],
        "patterns": [],
        "required_capability": "artifact.code.read",
        "requires_live_data": True,
        "allow_llm_only": False,
    },

    "runtime.inspect": {
        # Exact self-inspection prompts belong to the observed runtime catalog.
        # Descriptions from a generative model are not evidence of live tools.
        "triggers": ["what tools can you use", "your unique capabilities"],
        "patterns": [
            r"^(?:first[,]?\s+)?what\s+are\s+(?:your|karen'?s)\s+(?:(?:unique|current|actual|available)\s+)?(?:capabilities|abilities|tools|features)[?!.]*$",
            r"^what\s+(?:tools|capabilities|features)\s+do\s+(?:you|karen)\s+(?:(?:currently|actually|right\s+now)\s+)?(?:have|offer|support|have\s+available)(?:\s+(?:available|right\s+now|to\s+me))?[?!.]*$",
            r"^(?:which|what)\s+(?:tools|capabilities)\s+are\s+(?:currently\s+)?(?:available|enabled|accessible)\s+(?:to\s+you|in\s+karen|for\s+karen)[?!.]*$",
            r"^(?:what\s+can\s+(?:you|karen)\s+(?:actually\s+|currently\s+)?do|can\s+you\s+access\s+(?:any\s+)?tools)[?!.]*$",
            r"^(?:please\s+)?(?:list|show|tell\s+me)\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?(?:available|current|registered)\s+(?:tools|capabilities)[?!.]*$",
        ],
        "required_capability": "runtime.inspect",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "plugin.inspect": {
        # Read-only catalog discovery only. Side effects belong to a later,
        # separately authorized host/plugin action, never this direct route.
        "triggers": ["set up my plugin", "my plugins", "plugin status"],
        "patterns": [],
        "required_capability": "plugin.inspect",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "automation.create": {
        # Mutating recurring task requests must enter RuntimePolicy and obtain
        # a durable database receipt, never fall back to a model-only script.
        # CORTEX recognizes a bounded command; Runtime validates all fields.
        "triggers": ["create daily task", "schedule daily task", "create a task every day"],
        "patterns": [
            r"^(?:please\s+)?(?:create|schedule|set\s+up|add)\s+(?:me\s+)?(?:a\s+)?(?:daily|recurring)\s+(?:task|automation|job)\s+(?:to|for)\s+.+$",
            r"^(?:please\s+)?(?:create|schedule|set\s+up|add)\s+(?:me\s+)?(?:a\s+)?(?:(?:new|scheduled)\s+)?(?:task|automation|job)\s+(?:to|for)\s+.+\b(?:every\s*day|daily)\b.*$",
            # A first-person task commitment is a mutation request, even when
            # its purpose contains "latest news". It must not become advice.
            r"^i\s+(?:need|want)\s+(?:a\s+)?(?:(?:daily|recurring)\s+)?(?:task|automation|job)\s+(?:to|for)\s+.+\b(?:every\s*day|daily)\b.*$",
            r"^i(?:\x27d|\s+would)\s+like\s+(?:a\s+)?(?:(?:daily|recurring)\s+)?(?:task|automation|job)\s+(?:to|for)\s+.+\b(?:every\s*day|daily)\b.*$",
        ],
        "required_capability": "automation.create",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "timer.manage": {
        # Timer commands require a durable scheduler receipt. In-memory alarm
        # definitions and generated prose are not execution evidence.
        "triggers": ["start timer", "set a timer", "timer running", "show timer", "timer reminder"],
        "patterns": [
            r"^(?:please\s+)?(?:start|set|create|begin)\s+(?:(?:me\s+)?a\s+)?(?:\d+\s*(?:second|minute|hour|sec|min|hr)s?\s+)?timer(?:\s+(?:for|of)\s+\d+\s*(?:second|minute|hour|sec|min|hr)s?)?[?!.]*$",
            r"^(?:please\s+)?(?:start|set|create|begin)\s+(?:me\s+)?(?:a\s+)?timer\s+(?:for|of)\s+\d+\s*(?:second|minute|hour|sec|min|hr)s?[?!.]*$",
            r"^(?:please\s+)?(?:show|display|open|hide|stop|pause|resume|cancel|restart|reset)\s+(?:(?:me\s+)?(?:the|my|a|live)\s+)?(?:live\s+)?timer[?!.]*$",
            r"^(?:can|could|would)\s+you\s+(?:please\s+)?(?:show|display|open|hide|stop|pause|resume|cancel)\s+(?:(?:me\s+)?(?:the|my|a|live)\s+)?(?:live\s+)?timer[?!.]*$",
            r"^(?:can|could|would)\s+you\s+not\s+(?:show|display)\s+(?:me\s+)?(?:the\s+)?(?:live\s+)?timer[?!.]*$",
            r"^(?:is|has)\s+(?:my|the)\s+timer\s+(?:still\s+)?(?:active|running|finished|expired|started|stopped)[?!.]*$",
            r"^(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?:status|remaining\s+time|time\s+left)\s+(?:of|on|for)\s+(?:my|the)\s+timer[?!.]*$",
            r"^(?:i\s+)?(?:didn'?t|did\s+not|haven'?t|have\s+not)\s+(?:get|receive)\s+(?:any|the|my|a)\s+(?:timer\s+)?reminder[?!.]*$",
            r"^(?:will|did|can)\s+(?:you|karen)\s+(?:send|notify|remind)\s+me\s+(?:when|after)\s+(?:my|the)\s+timer\s+(?:ends|finishes|expires)[?!.]*$",
        ],
        "required_capability": "timer.schedule",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "planner.create": {
        # A simple personal commitment is not an executable agent task or
        # recurring automation. Runtime must separately authorize the write,
        # validate timezone and timing, and obtain a durable receipt.
        "triggers": ["create a personal task", "add a task to", "create a task to"],
        "patterns": [
            r"^(?:please\s+)?(?:create|add|make)\s+(?:me\s+)?(?:a\s+)?(?:personal\s+)?(?:task|commitment)\s+(?:to|for)\s+.+$",
        ],
        "required_capability": "planner.create",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "planner.update": {
        # Completion is a scoped planner mutation, not an automation or
        # LLM-only acknowledgement. Runtime must verify task ID, revision,
        # action identity, owner and committed persistence receipt.
        "triggers": ["complete task", "complete my task", "mark task", "finish task"],
        "patterns": [
            # The *object* of the command must be a task or commitment.
            # Argument-free, plural and punctuated requests must reach the
            # fail-closed parser; prose merely mentioning tasks must not.
            r"^(?:please\s+|(?:can|could|would)\s+you\s+(?:please\s+)?)?"
            r"(?:complete|finish|mark(?:\s+as\s+completed|\s+completed)?)\s+"
            r"(?:all\s+)?(?:(?:my|the|a)\s+)?(?:personal\s+)?"
            r"(?:tasks?|commitments?)(?:\s+.*?)?[?!.]*$",
            # Named tasks are bounded object phrases, never arbitrary prose.
            r"^(?:please\s+|(?:can|could|would)\s+you\s+(?:please\s+)?)?"
            r"(?:complete|finish|mark(?:\s+as\s+completed|\s+completed)?)\s+"
            r"(?:my|the)\s+"
            r"(?:(?!(?:about|for|with|regarding|sentence|paragraph|email|essay|report)\b)"
            r"[a-z0-9_'-]+\s+){1,4}"
            r"(?:tasks?|commitments?)(?:\s+.*?)?[?!.]*$",
        ],
        "required_capability": "planner.update",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "planner.read": {
        "triggers": ["show my planner", "list my tasks", "show my tasks"],
        "patterns": [
            r"^(?:please\s+)?(?:show|list|display)\s+(?:me\s+)?my\s+(?:planner|tasks|commitments)(?:\s+for\s+today)?[?!.]*$",
            r"^what(?:'s|\s+is)\s+on\s+my\s+planner[?!.]*$",
        ],
        "required_capability": "planner.read",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "system.resources": {
        "triggers": ["ram left", "memory left", "free memory", "available ram", "vram left", "disk space"],
        "patterns": [
            r"^(?:how much|what(?:'s| is) the)\s+(?:system\s+|computer\s+)?(?:ram|memory|vram|disk space)\s+(?:(?:do i have|i (?:got|have))\s+)?(?:left|available|free)(?:\s+on\s+(?:my\s+)?(?:computer|system|machine|pc))?[?!.]*$",
            r"^(?:how much|what(?:'s| is) the)\s+(?:free|available|remaining)\s+(?:system\s+)?(?:ram|memory|vram|disk space)(?:\s+do i have)?[?!.]*$",
        ],
        "required_capability": "system.resources",
        "handler": "system_resources",
        "requires_live_data": True,
        "allow_llm_only": False,
    },
    "time.current": {
        "triggers": ["what time", "current time", "time in", "timezone", "current date", "today's date"],
        "patterns": [
            # The bare command is a clock request, not a conceptual question.
            # Keep it exact so "time complexity" or "time in physics" remain
            # ordinary model conversations instead of clock lookups.
            r"^time[?!.]*$",
            # Short contextual calendar requests must not become model guesses.
            r"^(?:the\s+)?date[?!.]*$",
            r"^what\s+time\s+is\s+it(?:\s+right\s+now)?(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^what(?:'s|s|\s+is)\s+the\s+(?:current\s+)?time(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^current\s+time(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^time\s+now(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^what(?:'s|\s+is)\s+(?:the\s+)?(?:current\s+|today'?s?\s+)?date(?:\s+(?:today|right\s+now))?[?!.]*$",
            r"^what\s+(?:is\s+)?today'?s?\s+date[?!.]*$",
            r"^(?:current|today'?s?)\s+date[?!.]*$",
            r"^(?:please\s+)?(?:tell\s+me|show\s+me)\s+(?:the\s+)?(?:current|today'?s?)\s+date[?!.]*$",
            r"^timezone\s+(?:in|for|of)\s+.+[?!.]*$",
            r"^(?:please\s+)?(?:could|would|can)\s+you\s+(?:please\s+)?tell\s+me\s+(?:what\s+time\s+it\s+is|what\s+time\s+is\s+it|the\s+(?:current\s+)?time)(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^(?:please\s+)?tell\s+me\s+(?:what\s+time\s+it\s+is|what\s+time\s+is\s+it|the\s+(?:current\s+)?time)(?:\s+(?:in|for)\s+.+)?[?!.]*$",
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
            # Explicit source tables reuse live search routing, never a model-only
            # guess about current releases or headlines. Keep bounded subjects.
            r"^(?:show(?: me)?|list|find|give me)\s+(?:the\s+)?(?:latest|current|recent|new)\s+(?:(?:movie|film)\s+)?(?:releases|movies|films|news|headlines|results|sources)\s+(?:in|as)\s+(?:a\s+)?table[?!.]*$",
            r"^tabulate\s+(?:the\s+)?(?:latest|current|recent|new)\s+(?:(?:movie|film|web|news)\s+)?(?:sources|results|releases|headlines)[?!.]*$",
            r"^(?:give me|show me|list)\s+(?:a\s+)?tabular\s+list\s+of\s+(?:latest|recent|current)\s+(?:web|news|movie)\s+(?:sources|results|headlines)[?!.]*$",
            r"^(?:latest|current|recent|new)\s+(?:(?:movie|film|web|news)\s+)?(?:movies|films|releases|news|headlines|sources|results)\s+(?:in|as)\s+(?:a\s+)?table[?!.]*$",
            # Explicit current-film queries require live discovery. Ordinary
            # recommendations and film analysis stay in model conversation.
            r"^(?:what(?:'s| is)|show me|find|list|tell me about)\s+(?:the\s+)?(?:latest|new|recent|currently playing)\s+(?:movies|films)(?:\s+(?:in|at|on|for)\s+[\w .'-]+)?[?!.]*$",
            r"^(?:latest|new|recent)\s+(?:movies|films)(?:\s+(?:in theaters|in cinemas|on streaming|released this week))?[?!.]*$",
            r"^(?:what(?:'s| is)|show me|find|list)\s+(?:the\s+)?(?:latest|new|recent)\s+(?:movie|film)\s+(?:releases?|premieres?)(?:\s+.+)?[?!.]*$",
            r"\bsearch\s+(?:the\s+)?(?:web|internet|online)\b",
            r"\bweb\s+search\b",
            r"\blook\s+(?:it\s+)?up\s+online\b",
            r"\blook\s+online\s+(?:for|at)\b",
            r"^(?:what(?:'s| is)|tell me|show me)\s+(?:the\s+)?(?:latest|current|recent|breaking)\s+(?:in|from|about|on|for)\s+[\w .'-]+\s+(?:news|headlines|updates?)[?!.]*$",
            r"^(?:what(?:'s| is)|tell me|show me)\s+(?:the\s+)?(?:latest|current|recent|breaking)\s+(?:news|headlines|updates?)\s+(?:in|from|about|on|for)\s+[\w .'-]+[?!.]*$",
            r"^(?:what(?:'s| is)\s+)?happening\s+(?:right\s+now\s+)?(?:in|across|around)\s+[\w .'-]+[?!.]*$",
            r"^(?:any|what(?:'s| is)\s+the)\s+(?:breaking|latest|recent)\s+(?:news|headlines|updates?)\s+(?:from|in|about|on)\s+[\w .'-]+[?!.]*$",
            r"^(?:(?:please\s+)?(?:can|could|would)\s+you\s+(?:please\s+)?)?(?:please\s+)?find\s+(?:the\s+)?(?:current|latest|today'?s?)\s+(?:(?:[\w.+#-]+\s+){0,4})(?:news|results?|score|price|release|version|information)[?!.]*$",
            r"^(?:what(?:'s|\s+is)|which\s+is)\s+the\s+(?:current|latest)\s+(?:(?:[\w.+#-]+\s+){0,4})(?:news|result|score|price|release|version)[?!.]*$",
            r"^(?:what(?:'s|\s+is)|which\s+is)\s+the\s+(?:current|latest)\s+(?:news|result|score|price|release|version)\s+(?:about|of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3}[?!.]*$",
            r"^(?:latest|current|today'?s?)\s+(?:news|results?|score|price|release|version)(?:\s+(?:on|about|of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3})?[?!.]*$",
            r"^(?:latest|current)\s+(?:[A-Za-z][\w.+#-]*\s+){1,3}updates?[?!.]*$",
            r"^(?:latest|current)\s+updates?\s+(?:on|about|for)\s+[A-Za-z][\w.+#-]*(?:\s+[A-Za-z][\w.+#-]*){0,3}[?!.]*$",
            r"^(?:latest|current)\s+(?:(?:[\w.+#-]+\s+){1,4})(?:news|results?|score|price|release|version)(?:\s+(?:on|about|of|for)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3})?[?!.]*$",
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
            r"^what(?:'s|\s+is)\s+(?:the\s+)?weather\s+like(?:\s+(?:in|for)\s+.+)?[?!.]*$",
            r"^what(?:'s|\s+is)\s+(?:the\s+)?forecast(?:\s+(?:for|in)\s+.+)?[?!.]*$",
            r"\bwhat\s+will\s+the\s+weather\s+be\s+(?:in|for)\s+.+$",
            r"^how(?:'s|\s+is)\s+(?:the\s+)?weather(?:\s+(?:in|for)\s+.+)?[?!.]*$",
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


def weather_query_has_explicit_location(query: str) -> bool:
    """Detect explicitly named forecast places at the CORTEX ingress boundary.

    This only decides whether private-memory location resolution is needed.
    Provider search and geographic validation remain downstream authorities.
    """
    raw = " ".join(str(query or "").strip().split()).rstrip("?!.")
    named_place = re.search(
        r"\b(?:weather(?:\s+like)?|forecast|temperature)\s+(?:in|for|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z0-9 ,.'-]{0,110})$",
        raw,
        flags=re.IGNORECASE,
    )
    if named_place and _looks_like_location_phrase(named_place.group("location")):
        return True
    return _looks_like_location_first_weather(query) or _looks_like_forecast_target(query)


def _looks_like_shorthand_time(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?")
    match = re.fullmatch(r"time\s+in\s+(?P<location>.+)", raw, flags=re.IGNORECASE)
    if not match:
        return False
    return _looks_like_location_phrase(match.group("location"))


def _looks_like_forecast_target(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    match = re.fullmatch(r"forecast\s+(?:for|in)\s+(.+)", raw, re.IGNORECASE)
    return bool(match and _looks_like_location_phrase(match.group(1)))


def _looks_like_location_first_weather(query: str) -> bool:
    raw = " ".join((query or "").strip().split()).rstrip("?!.")
    # Interrogative openings are not place names: "What's the weather?"
    # must request authorized location context, not invent "What's the".
    if re.match(r"^(?:what(?:'s|\s+is)|how(?:'s|\s+is)|where|will|is|does)\b", raw, re.IGNORECASE):
        return False
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



@dataclass(frozen=True, slots=True)
class PluginInspectionRequest:
    """CORTEX recognition only, never an execution or authorization grant."""

    operation: str
    target: Optional[str] = None
    requested_action: Optional[str] = None
    goal: Optional[str] = None


_PLUGIN_LOOKUP_PATTERNS = (
    (
        "setup",
        re.compile(
            r"^(?:please\s+)?(?:set\s*up|connect|configure|link)\s+"
            r"(?:(?:my|the)\s+)?(?:plugin\s+)?"
            r"(?P<target>[a-z][a-z0-9 _-]{1,64}?)"
            r"(?:\s+(?:plugin|integration))?[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "resume",
        re.compile(
            r"^(?:please\s+)?(?:continue|resume)\s+(?:setting\s+up|configuring|connecting)\s+"
            r"(?:(?:my|the)\s+)?(?P<target>[a-z][a-z0-9 _-]{1,64}?)[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "status",
        re.compile(
            r"^(?:is|has)\s+my\s+(?P<target>[a-z][a-z0-9 _-]{1,64}?)\s+"
            r"(?:connected|configured|ready|installed|enabled|been\s+set\s+up)[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "features",
        re.compile(
            r"^(?:what\s+can|which\s+features\s+can)\s+my\s+"
            r"(?P<target>[a-z][a-z0-9 _-]{1,64}?)\s+"
            r"(?:plugin\s+)?(?:do|use|provide)[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "status",
        re.compile(
            r"^(?P<target>[a-z][a-z0-9 _-]{1,64}?)\s+plugin\s+"
            r"(?:status|readiness|features)[?!.]*$",
            re.IGNORECASE,
        ),
    ),
)


# This recognition contract is shared by every installed plugin. It classifies
# the user's requested lifecycle/action purpose but grants only catalog reads.
# Actual mutations and invocation must obtain fresh, action-specific authority.
_PLUGIN_ACTION_PATTERNS = (
    re.compile(
        r"^(?:please\s+)?(?P<action>enable|disable|activate|deactivate|"
        r"install|uninstall|remove|update|upgrade)\s+"
        r"(?:(?:my|the|installed)\s+)?(?:plugin\s+)?"
        r"(?P<target>[a-z][a-z0-9 _-]{1,64}?)"
        r"(?:\s+(?:plugin|integration))?[?!.]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?P<action>use|invoke|run)\s+"
        r"(?:(?:my|the|installed)\s+)?(?:plugin\s+)?"
        r"(?P<target>[a-z][a-z0-9 _-]{1,64}?)"
        r"(?:\s+plugin)?\s+(?:to|for)\s+(?P<goal>.+)$",
        re.IGNORECASE,
    ),
)

_PLUGIN_DISCOVERY = re.compile(
    r"^(?:which|what)\s+(?:of\s+the\s+)?(?:installed\s+|available\s+)?"
    r"plugins?\s+(?:can|could|should)\s+(?:i|you|karen)\s+"
    r"(?:use\s+)?(?:to|for)\s+.+[?!.]*$",
    re.IGNORECASE,
)

_PLUGIN_INVENTORY = re.compile(
    r"^(?:(?:please\s+)?(?:show|list)(?:\s+me)?\s+(?:my|the|available|installed)\s+plugins"
    r"|(?:which|what)\s+plugins\s+(?:are\s+(?:installed|available)|can\s+you\s+use|do\s+i\s+have)"
    r"|what\s+plugins\s+do\s+i\s+have)[?!.]*$",
    re.IGNORECASE,
)


def parse_plugin_inspection_request(query: str) -> Optional[PluginInspectionRequest]:
    """Match explicit plugin setup/status talk without inferring authority.

    The target is only a catalog lookup hint. Runtime resolves it against
    installed manifests and never executes a named plugin from this request.
    """
    raw = " ".join(str(query or "").strip().split())
    if not raw or len(raw) > 160:
        return None
    if _PLUGIN_INVENTORY.fullmatch(raw):
        return PluginInspectionRequest(operation="list")
    if _PLUGIN_DISCOVERY.fullmatch(raw):
        return PluginInspectionRequest(operation="discover")
    for action_pattern in _PLUGIN_ACTION_PATTERNS:
        match = action_pattern.fullmatch(raw)
        if match is None:
            continue
        action = match.group("action").casefold()
        target = match.group("target").strip(" .?!")
        # A bounded, explicitly named plugin is mandatory. Compound provider
        # actions are not silently reduced to catalog inspection.
        if (
            not target
            or re.search(r"\b(?:and|then|with\s+(?:token|secret|password))\b", target, re.I)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{1,64}", target)
        ):
            return None
        if action in {"use", "invoke", "run"}:
            goal = match.group("goal") or ""
            if not 1 <= len(goal.strip()) <= 240:
                return None
            return PluginInspectionRequest(
                operation="use", target=target, requested_action="execute",
                goal=goal.strip(),
            )
        return PluginInspectionRequest(
            operation="manage", target=target, requested_action=action,
        )
    if re.fullmatch(
        r"(?:please\s+)?(?:continue|resume)\s+setting\s+it\s+up[?!.]*",
        raw,
        flags=re.IGNORECASE,
    ):
        return PluginInspectionRequest(operation="resume")
    for operation, pattern in _PLUGIN_LOOKUP_PATTERNS:
        match = pattern.fullmatch(raw)
        if match is not None:
            target = match.group("target").strip(" .?!")
            # Never downgrade compound requests with possible side effects
            # into an apparently harmless setup inspection.
            compound = re.search(
                r"\b(?:and|then|send|message|delete|share|post|execute|"
                r"run|with\s+(?:token|password|secret)|for\s+someone)\b",
                target, flags=re.IGNORECASE,
            )
            if (
                target
                and not compound
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{1,64}", target)
            ):
                return PluginInspectionRequest(operation=operation, target=target)
    return None


def _plugin_inspection_decision(
    request: PluginInspectionRequest, *, confidence: float
) -> CapabilityDecision:
    """Return a single read-only admission contract for plugin preflight."""
    route = CAPABILITY_ROUTES["plugin.inspect"]
    return CapabilityDecision(
        intent="plugin.inspect",
        subtype=request.operation,
        confidence=confidence,
        requires_tool=True,
        requires_live_data=True,
        capability=str(route["required_capability"]),
        allow_llm_only=False,
        requires_chat_capable_model=False,
    )


def resolve_capability_decision(
    query: str,
    *,
    confidence: float = 0.9,
    has_search_options: bool = False,
) -> CapabilityDecision:
    handoff_question = parse_research_handoff_question(query)
    if handoff_question is not None:
        query = handoff_question
    # Exact, owner-scoped artifact viewing outranks broad search and model intents.
    # A parsed identifier is a lookup request, not permission to read it.
    if handoff_question is None and parse_owner_code_artifact_view(query) is not None:
        return CapabilityDecision(
            intent="artifact.code.read", confidence=confidence,
            requires_tool=True, requires_live_data=True,
            capability="artifact.code.read", allow_llm_only=False,
            requires_chat_capable_model=False,
        )
    plugin_request = (
        parse_plugin_inspection_request(query) if handoff_question is None else None
    )
    # Explicit catalog discovery, use and lifecycle requests must outrank
    # unanchored generic search/weather patterns, but CORTEX grants no action.
    explicit_plugin = plugin_request is not None and (
        plugin_request.operation in {"list", "discover", "use", "manage"}
        or re.search(r"\b(?:plugins?|integrations?)\b", query, re.IGNORECASE)
    )
    if explicit_plugin and plugin_request is not None:
        return _plugin_inspection_decision(plugin_request, confidence=confidence)
    # Normalize surface spelling for matching only. Keep the original request
    # untouched for tool parameters, provenance and conversational evidence.
    # Common apostrophe omissions must not convert live-information questions
    # into model-only chat. This applies across all capability patterns.
    q = " ".join(str(query or "").casefold().replace("’", "'").split())
    q = re.sub(r"\b(what|who|where|when|why|how)s\b", r"\1's", q)
    # A user's private resource is not a public search target, even when a
    # sentence contains a freshness word such as "latest" or "update".
    private_update = bool(re.search(
        r"\b(?:my|our|your|his|her|their|its|mine|ours|yours|hers|theirs|private|internal|confidential)\b", q
    )) and bool(re.search(r"\b(?:update|updates|status)\b", q))

    # Contextual "happening" questions about private/application state are
    # not public news requests. Do not route them to external web search.
    private_happening = bool(re.search(
        r"\b(?:my|our|your|his|her|their|its|mine|ours|yours|hers|theirs|"
        r"private|internal|confidential|this)\b", q
    )) and bool(re.search(r"\b(?:happening|going on)\b", q))

    # Specialized routes use bounded intent patterns, not substring hits. This
    # keeps deterministic fallback available when Intelligence is offline while
    # avoiding hijacks such as "what time complexity..." or incidental "latest".
    for intent, config in CAPABILITY_ROUTES.items():
        if handoff_question is not None and intent != "search.general":
            continue
        patterns = config.get("patterns", [])
        matched = handoff_question is not None or any(
            re.search(pattern, q, flags=re.IGNORECASE)
            for pattern in patterns
        )
        if intent == "search.general" and (private_update or private_happening):
            matched = False
        if intent == "time.current":
            matched = matched or _looks_like_shorthand_time(query)
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
                missing_requirements=(
                    ["location.current"]
                    if intent == "search.weather"
                    and not weather_query_has_explicit_location(query)
                    else []
                ),
            )

    # Explicit general search retrieval options route any non-private query
    # to search.general when no other specialized capability matched.
    if has_search_options and not (private_update or private_happening):
        route = CAPABILITY_ROUTES["search.general"]
        return CapabilityDecision(
            intent="search.general",
            confidence=max(confidence, 0.9),
            requires_tool=True,
            requires_live_data=bool(route.get("requires_live_data", False)),
            capability=route.get("required_capability"),
            preferred_plugin=route.get("preferred_plugin"),
            handler=route.get("handler"),
            requires_chat_capable_model=bool(route.get("allow_llm_only", False)),
            allow_llm_only=bool(route.get("allow_llm_only", False)),
            missing_requirements=(),
        )

    # Generic "set up" wording is a lower-priority plugin fallback.
    # Registered automation, timer, time, and weather intents win first.
    if plugin_request is not None:
        return _plugin_inspection_decision(plugin_request, confidence=confidence)

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


