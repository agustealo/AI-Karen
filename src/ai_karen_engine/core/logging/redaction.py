from __future__ import annotations

import logging
import re
from typing import Any

# Standard redaction patterns
_REDACTION_PATTERNS = [
    # Signed HTTP URLs carry bearer tokens in their query strings.
    # Redact short as well as long tokens, including percent-encoded values.
    (re.compile(r"(?i)([?&]token=)[^&#\\s\\\"']+"), r"\\1[REDACTED]"),
    # JWT (most specific)
    (re.compile(r"(?i)eyJ[a-z0-9_-]*\.eyJ[a-z0-9_-]*\.[a-z0-9_-]*"), "[JWT_REDACTED]"),
    # API Keys & Tokens with labels
    (re.compile(r"(?i)(api[_-]?key|access[_-]?key|secret[_-]?key|auth[_-]?token|bearer)\s*[:= ]\s*([a-z0-9+/=._-]{16,})"), "[REDACTED]"),
    # Password variants with labels
    (re.compile(r"(?i)(password|passwd|pwd)(\s+is)?\s*[:= ]\s*([^\s,{}]+)"), r"\1=[REDACTED]"),
    # Headers
    (re.compile(r"(?i)(authorization|x-api-key|cookie|set-cookie)\s*:\s*([^\r\n]+)"), r"\1: [REDACTED]"),
    # DB URLs with credentials
    (re.compile(r"([a-z0-9+]+://)[^:]+:[^@]+@"), r"\1[REDACTED]:[REDACTED]@"),
    # Generic secret/token/key matches
    (re.compile(r"(?i)(token|key|secret|credential)\s*[:= ]\s*([a-z0-9+/=._-]{16,})"), r"\1=[REDACTED]"),
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
        # Redact by key first
        sensitive_keys = {"password", "secret", "token", "key", "credential", "auth", "api_key"}
        new_dict = {}
        for k, v in data.items():
            if isinstance(k, str) and any(sk in k.lower() for sk in sensitive_keys):
                 new_dict[k] = "[REDACTED]"
            else:
                 new_dict[k] = redact_data(v)
        return new_dict
    if isinstance(data, list):
        return [redact_data(item) for item in data]
    return data


class SignedStorageURLLogFilter(logging.Filter):
    """Sanitize HTTPX's signed-object request log before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "httpx":
            message = record.getMessage()
            if "/storage/v1/object/sign/" in message and "token=" in message.lower():
                record.msg = redact_text(message)
                record.args = ()
        return True


def install_signed_storage_httpx_log_filter() -> None:
    """Idempotent installation at the canonical transport/logging boundary."""
    logger = logging.getLogger("httpx")
    if not any(isinstance(item, SignedStorageURLLogFilter) for item in logger.filters):
        logger.addFilter(SignedStorageURLLogFilter())
