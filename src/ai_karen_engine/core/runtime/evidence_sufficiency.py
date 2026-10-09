"""Runtime-owned evidence sufficiency for personal facts.

Consumes only RuntimePolicy-authorized CognitiveContext. This module never
retrieves evidence, chooses a provider, or authorizes a memory operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ai_karen_engine.core.context.contracts import (
    CognitiveContext, EvidenceContradictionStatus, EvidenceSource,
)


class EvidenceSufficiencyStatus(str, Enum):
    SUPPORTED = "supported"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class EvidenceSufficiency:
    status: EvidenceSufficiencyStatus
    attribute: str | None
    value: str | None = None
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""

    @property
    def may_assert(self) -> bool:
        return self.status is EvidenceSufficiencyStatus.SUPPORTED


def evaluate_personal_evidence(
    context: CognitiveContext | None,
    *,
    tenant_id: str,
    user_id: str,
    attribute: str | None,
    now: datetime | None = None,
) -> EvidenceSufficiency:
    """Return a fact only if authorized, attributable, current and unopposed.

    A missing/ambiguous attribute never maps to a convenient neighbor such as
    upbringing when the question asks about birthplace or origin.
    """
    if not attribute:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.AMBIGUOUS, None, reason="attribute_unresolved"
        )
    if (
        context is None
        or context.tenant_id != tenant_id
        or context.user_id != user_id
        or EvidenceSource.MEMORY.value not in context.authorized_sources
        or EvidenceSource.MEMORY.value in context.denied_sources
        or EvidenceSource.MEMORY.value in context.unresolved_sources
    ):
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.MISSING, attribute, reason="memory_not_authorized_or_resolved"
        )

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    prefix = f"{attribute}: "
    live: list[tuple[str, str]] = []
    expired_ids: list[str] = []
    conflict_ids: list[str] = []

    for evidence in context.evidence:
        if (
            evidence.source is not EvidenceSource.MEMORY
            or evidence.scope is None
            or evidence.scope.tenant_id != tenant_id
            or evidence.scope.user_id != user_id
            or not evidence.content.startswith(prefix)
        ):
            continue
        value = evidence.content[len(prefix):].strip()
        if not value or len(value) > 120 or "\n" in value:
            continue
        expired = False
        for deadline in (evidence.temporal.expires_at, evidence.temporal.effective_until):
            if deadline is not None:
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if deadline <= current:
                    expired = True
                    break
        if expired:
            expired_ids.append(evidence.evidence_id)
            continue
        if evidence.contradiction.status in {
            EvidenceContradictionStatus.CONFIRMED,
            EvidenceContradictionStatus.POSSIBLE,
        }:
            conflict_ids.append(evidence.evidence_id)
            continue
        live.append((evidence.evidence_id, value))

    if conflict_ids:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.CONTRADICTORY, attribute,
            evidence_ids=tuple(conflict_ids), reason="flagged_contradiction",
        )
    if live:
        values = {value.casefold() for _, value in live}
        if len(values) > 1:
            return EvidenceSufficiency(
                EvidenceSufficiencyStatus.CONTRADICTORY, attribute,
                evidence_ids=tuple(item[0] for item in live), reason="conflicting_values",
            )
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.SUPPORTED, attribute,
            value=live[0][1],
            evidence_ids=tuple(item[0] for item in live),
            reason="authorized_memory_evidence",
        )
    if expired_ids:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.EXPIRED, attribute,
            evidence_ids=tuple(expired_ids), reason="no_current_evidence",
        )
    return EvidenceSufficiency(
        EvidenceSufficiencyStatus.MISSING, attribute, reason="no_matching_evidence",
    )
