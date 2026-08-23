"""Suggestion contracts.

Canonical contracts for user-facing suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SuggestionFeedbackType(str, Enum):
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    ACTED_ON = "acted_on"
    CORRECTED = "corrected"


@dataclass(slots=True)
class SuggestionCandidate:
    """Canonical suggestion candidate for user-facing advice."""

    suggestion_id: str
    suggestion_type: str
    subject: str
    utility: float = 0.0
    confidence: float = 0.0
    interruption_cost: float = 0.0
    urgency: str = "normal"
    evidence: dict[str, Any] = field(default_factory=dict)
    expires_at: str | None = None
    dedupe_key: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SuggestionRecord:
    """Persisted suggestion record with feedback."""

    suggestion_id: str
    user_id: str
    tenant_id: str
    candidate: SuggestionCandidate
    feedback: SuggestionFeedbackType | None = None
    feedback_at: str | None = None
    superseded_by: str | None = None
    resolved_at: str | None = None
    dismissed_at: str | None = None
