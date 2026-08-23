"""
Kari CORTEX Intent Resolution Core
- Stateless, pluggable, prompt-first intent classifier
- Plugs into predictors/NLP if available, otherwise falls back to basic matching
- Pure backend, no UI dependencies
"""

from typing import Tuple, Dict, Any

BASIC_INTENT_MAP = {
    "hello": "greeting",
    "hi": "greeting",
    "log out": "logout",
    "audit": "audit_log",
    "search": "search",
    "status": "system_status",
    "memory": "memory",
    "diagnose": "diagnostics",
    "admin": "admin_panel",
    # Routing shorthand patterns (KIRE)
    "route": "routing.select",
    "use provider": "routing.select",
    "switch model": "routing.select",
    "routing profile": "routing.profile",
    "model selection": "routing.select",
    # Extend as needed for coverage
}

def resolve_intent(query: str, user_ctx: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Resolves user query to an intent string and optional meta.
    Pluggable with ML/NLP if available, else uses fallback rules.
    Args:
        query: Raw user query string.
        user_ctx: Dict with user/session context.
    Returns:
        (intent, meta) where meta can be model confidence, etc.
    """
    q = query.lower().strip()

    for key, intent in BASIC_INTENT_MAP.items():
        if key in q:
            return intent, {"match": "fallback", "pattern": key}

    # 3. Default
    return "unknown", {"match": "default"}

__all__ = ["resolve_intent"]
