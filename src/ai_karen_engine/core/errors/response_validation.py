"""Response text validation — blocks prompt leakage and raw tool JSON.

This function was migrated from core/response/response_validator.py during
CORE-PRUNE-1. It validates that generated response text does not contain
prompt-leakage patterns or raw tool-call JSON that should have been processed
by the tool-use pipeline instead.
"""
from __future__ import annotations

import json
import re

_BLOCKED_PATTERNS = [
    r"^assistant:\s*",
    r"answer only the user",
    r"you are karen",
    r"\[transformers:auto\]",
    r"\(joke provider\)",
    # Whole-response planning narration is not a conversational answer.
    # Anchor to the opening so ordinary references to "the user" remain valid.
    r"^(?:alright,?\s+)?the user (?:just )?(?:said|says|asked|asks|is asking|wants|is testing)\b",
    r"^when (?:asked|responding) .{0,100}\bit(?:'s| is) important to\b",
    r"^(?:i should|i need to|let me) (?:explain how|acknowledge that|respond by|craft a response)\b",
    # Generated meta-narration about answering the user is not an answer.
    r"^(?:karen|the assistant)\s+(?:responds?|should respond|would respond)\s+to\s+the\s+user\b",
    r"^to determine who ['\"]?i am['\"]? and what my name is\b",


]


def _looks_like_raw_tool_json(text: str) -> bool:
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        payload = json.loads(stripped)
    except Exception:
        return False
    return any(k in payload for k in ("tool", "tool_name", "tool_call", "arguments"))


def validate_response_text(text: str, *, allow_tool_json: bool = False) -> bool:
    """Return True if *text* is a safe, user-facing response.

    Returns False for empty strings, prompt-leakage patterns, or raw
    tool-call JSON (unless *allow_tool_json* is True).
    """
    if not text or not text.strip():
        return False
    low = text.lower().strip()
    if any(re.search(p, low) for p in _BLOCKED_PATTERNS):
        return False
    if not allow_tool_json and _looks_like_raw_tool_json(text):
        return False
    return True
