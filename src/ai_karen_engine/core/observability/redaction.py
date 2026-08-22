from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "key",
    "credential",
    "auth",
    "api_key",
    "authorization",
    "cookie",
    "set_cookie",
    "x_api_key",
    "bearer",
    "private_key",
    "access_token",
    "refresh_token",
    "client_secret",
}

_REDACTION_PATTERNS = [
    (re.compile(r"(?i)eyJ[a-z0-9_-]*\.eyJ[a-z0-9_-]*\.[a-z0-9_-]*"), "[JWT_REDACTED]"),
    (
        re.compile(
            r"(?i)(api[_-]?key|access[_-]?key|secret[_-]?key|auth[_-]?token|bearer)\s*[:= ]\s*([a-z0-9+/=._-]{16,})"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(r"(?i)(password|passwd|pwd)(\s+is)?\s*[:= ]\s*([^\s,{}]+)"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)(authorization|x-api-key|cookie|set-cookie)\s*:\s*([^\r\n]+)"),
        r"\1: [REDACTED]",
    ),
    (re.compile(r"([a-z0-9+]+://)[^:]+:[^@]+@"), r"\1[REDACTED]:[REDACTED]@"),
    (
        re.compile(r"(?i)(token|key|secret|credential)\s*[:= ]\s*([a-z0-9+/=._-]{16,})"),
        r"\1=[REDACTED]",
    ),
]


def redact_text(text: str) -> str:
    """Redact secrets from a string using regex patterns."""
    if not text:
        return text
    redacted = text
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_data(data: Any) -> Any:
    """Recursively redact secrets from dicts, lists, or strings."""
    if isinstance(data, str):
        return redact_text(data)
    if isinstance(data, dict):
        new_dict: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and any(sk in k.lower() for sk in _SENSITIVE_KEYS):
                new_dict[k] = "[REDACTED]"
            else:
                new_dict[k] = redact_data(v)
        return new_dict
    if isinstance(data, list):
        return [redact_data(item) for item in data]
    return data


class RedactionError(Exception):
    """Raised when redaction fails on an event payload."""
