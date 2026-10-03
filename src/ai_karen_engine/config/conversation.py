"""Canonical configuration for durable conversation context behavior."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ConversationContextSettings:
    """Configuration governing durable transcript context assembly."""

    history_limit: int = 24

    def validate(self) -> None:
        if self.history_limit < 0:
            raise ValueError("conversation history_limit must not be negative")
        if self.history_limit > 500:
            raise ValueError("conversation history_limit must not exceed 500")


_settings: Optional[ConversationContextSettings] = None


def get_conversation_context_settings() -> ConversationContextSettings:
    """Return validated conversation-context settings with env override."""
    global _settings
    if _settings is not None:
        return _settings

    raw_limit = os.getenv("KARI_CONVERSATION_HISTORY_LIMIT", "24").strip()
    try:
        history_limit = int(raw_limit)
    except ValueError as exc:
        raise RuntimeError(
            "KARI_CONVERSATION_HISTORY_LIMIT must be an integer"
        ) from exc

    settings = ConversationContextSettings(history_limit=history_limit)
    try:
        settings.validate()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    _settings = settings
    return settings


def reset_conversation_context_settings() -> None:
    """Reset cached settings for deterministic tests and config reloads."""
    global _settings
    _settings = None


__all__ = [
    "ConversationContextSettings",
    "get_conversation_context_settings",
    "reset_conversation_context_settings",
]
