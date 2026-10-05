"""Contracts for predictive user continuity.

Continuity planning derives suggestions from already-governed durable user state.
It never authorizes execution, mutates memory, or creates automations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ContinuityStateItem:
    """One current goal, open loop, or prospective event."""

    item_id: str
    source_type: str
    description: str
    confidence: float
    lifecycle_state: str
    source_event_id: str
    target_at: datetime | None = None
    domain: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContinuitySuggestion:
    """Decision-only recommendation for what may deserve attention next."""

    suggestion_id: str
    source_type: str
    source_ref: str
    description: str
    score: float
    confidence: float
    reason_codes: tuple[str, ...]
    target_at: datetime | None = None
    domain: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "suggestion_id": self.suggestion_id,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "description": self.description,
            "score": self.score,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "target_at": self.target_at.isoformat() if self.target_at else None,
            "domain": self.domain,
        }


@dataclass(frozen=True)
class ContinuityPlan:
    """Ranked continuity suggestions for one user request."""

    suggestions: tuple[ContinuitySuggestion, ...] = ()
    reason_codes: tuple[str, ...] = ()
    considered_count: int = 0

    @property
    def has_suggestions(self) -> bool:
        return bool(self.suggestions)

    def to_dict(self) -> dict[str, object]:
        return {
            "suggestions": [item.to_dict() for item in self.suggestions],
            "reason_codes": list(self.reason_codes),
            "considered_count": self.considered_count,
            "execution_authorized": False,
        }


class ContinuityStatePort(Protocol):
    """Backend-neutral reader for current user continuity state."""

    async def list_current_state(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[ContinuityStateItem]:
        """Return current governed state only."""


__all__ = [
    "ContinuityPlan",
    "ContinuityStateItem",
    "ContinuityStatePort",
    "ContinuitySuggestion",
]
