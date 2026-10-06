"""Proactive continuity intelligence contracts.

Intelligence may rank likely next needs from canonical evidence. It cannot
execute actions, create automations, mutate memory, or bypass RuntimePolicy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuityEvidence:
    source_type: str
    source_id: str
    subject: str
    state: str
    confidence: float
    target_at: datetime | None = None
    domain: str | None = None
    observation_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NextNeedCandidate:
    candidate_id: str
    source_type: str
    source_id: str
    subject: str
    utility: float
    confidence: float
    urgency: str
    interruption_cost: float
    target_at: datetime | None
    reason_codes: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContinuityAgenda:
    """Read-only organization of likely next work.

    This is not an execution plan. It only states whether one continuity item is
    clearly ahead of alternatives or whether the current evidence is ambiguous.
    """

    candidates: tuple[NextNeedCandidate, ...]
    primary_candidate_id: str | None
    ambiguous: bool
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False


class ProactiveContinuityRepository(ABC):
    """Read-only evidence port. Canonical persistence remains outside Intelligence."""

    @abstractmethod
    async def load_evidence(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[ContinuityEvidence]:
        """Load current tenant/user-scoped continuity evidence."""


__all__ = [
    "ContinuityAgenda",
    "ContinuityEvidence",
    "NextNeedCandidate",
    "ProactiveContinuityRepository",
]
