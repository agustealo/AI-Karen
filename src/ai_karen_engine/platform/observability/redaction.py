from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_JWT_REDACTED = "[JWT_REDACTED]"

# Field-name fragments (lowercased) whose value must always be redacted.
_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "auth_token",
    "token",
    "authorization",
    "cookie",
    "credential",
    "client_secret",
    "private_key",
    "privatekey",
    "two_factor_secret",
    "session_id",
    "set_cookie",
    "x_api_key",
)

# Query-string keys that must be stripped/redacted from URLs.
_SENSITIVE_QUERY_KEYS: tuple[str, ...] = (
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "pwd",
    "client_secret",
    "private_key",
    "authorization",
    "code",
    "state",
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


_TEXT_PATTERNS: tuple[
    tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...
] = (
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), _JWT_REDACTED),
    (
        re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9_\-.]{16,})"),
        lambda m: m.group(1) + " " + _REDACTED,
    ),
    (
        re.compile(
            r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|"
            r"auth[_-]?token|private[_-]?key|password|passwd|pwd|credential|token)"
            r"\s*[:= ]\s*[A-Za-z0-9_\-.]{16,}"
        ),
        _REDACTED,
    ),
)


def redact_text(text: str) -> str:
    """Redact secrets embedded in a string."""
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    for pattern, replacement in _TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_url(url: str) -> str:
    """Redact credentials and sensitive query parameters from a URL."""
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
    except Exception:  # noqa: BLE001 - malformed URLs should yield the input unchanged
        return url

    # userinfo (user:pass@host)
    if parts.username or parts.password:
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        parts = parts._replace(netloc=netloc)

    if parts.query:
        params = parse_qsl(parts.query, keep_blank_values=True)
        cleaned = [
            (k, _REDACTED) if k.lower() in _SENSITIVE_QUERY_KEYS else (k, v)
            for k, v in params
        ]
        parts = parts._replace(query=urlencode(cleaned, doseq=True))

    return urlunsplit(parts)


def redact_data(data: Any) -> Any:
    """Recursively redact secrets from dicts, lists, or strings.

    Sensitive field values are replaced before the value is inspected further,
    so nested secret-looking values inside structured metadata are caught.
    """
    if isinstance(data, str):
        return redact_url(redact_text(data))
    if isinstance(data, dict):
        new_dict: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                new_dict[key] = _REDACTED
            else:
                new_dict[key] = redact_data(value)
        return new_dict
    if isinstance(data, list):
        return [redact_data(item) for item in data]
    if isinstance(data, tuple):
        return tuple(redact_data(item) for item in data)
    return data
