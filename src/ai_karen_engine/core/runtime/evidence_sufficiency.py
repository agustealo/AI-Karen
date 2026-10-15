"""Runtime-owned evidence sufficiency for personal facts.

Consumes only RuntimePolicy-authorized CognitiveContext. This module never
retrieves evidence, chooses a provider, or authorizes a memory operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ai_karen_engine.core.memory.semantic_contract import FactCardinality

from ai_karen_engine.core.context.contracts import (
    CognitiveContext, EvidenceContradictionStatus, EvidenceSource,
)


class EvidenceSufficiencyStatus(str, Enum):
    SUPPORTED = "supported"
    SUPPORTED_SET = "supported_set"
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
    values: tuple[str, ...] = ()
    reason: str = ""

    @property
    def may_assert(self) -> bool:
        return self.status in {EvidenceSufficiencyStatus.SUPPORTED, EvidenceSufficiencyStatus.SUPPORTED_SET}


def evaluate_personal_evidence(
    context: CognitiveContext | None,
    *,
    tenant_id: str,
    user_id: str,
    attribute: str | None,
    now: datetime | None = None,
    cardinality: FactCardinality = FactCardinality.SINGLETON,
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
        if cardinality is FactCardinality.SET:
            distinct: dict[str, str] = {}
            for _evidence_id, value in live:
                distinct.setdefault(value.casefold(), value)
            return EvidenceSufficiency(
                EvidenceSufficiencyStatus.SUPPORTED_SET, attribute,
                evidence_ids=tuple(item[0] for item in live),
                values=tuple(distinct.values()),
                reason="authorized_set_memory_evidence",
            )
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


def evaluate_conversation_personal_evidence(
    context: CognitiveContext | None, *, tenant_id: str, user_id: str,
    attribute: str | None,
) -> EvidenceSufficiency:
    """Evaluate attributed user statements from authorized conversation history."""
    if not attribute:
        return EvidenceSufficiency(EvidenceSufficiencyStatus.AMBIGUOUS, None)
    if (
        context is None or context.tenant_id != tenant_id or context.user_id != user_id
        or EvidenceSource.CONVERSATION.value not in context.authorized_sources
        or EvidenceSource.CONVERSATION.value in context.denied_sources
        or EvidenceSource.CONVERSATION.value in context.unresolved_sources
    ):
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.MISSING, attribute, reason="conversation_unavailable",
        )
    from ai_karen_engine.core.memory.signals.semantic_classifier import (
        classify_explicit_user_memory,
    )
    facts: list[tuple[str, str]] = []
    for item in context.evidence:
        if (
            item.source is not EvidenceSource.CONVERSATION
            or item.scope is None or item.scope.tenant_id != tenant_id
            or item.scope.user_id != user_id
            or item.scope.conversation_id != context.requirements.conversation_id
            or item.metadata.get("role") != "user"
        ):
            continue
        user_text = item.content.strip()
        # Classification, not a first-token guess, establishes first-person
        # attribution. This also admits "Black is my favorite color" while
        # rejecting reported speech and quotes via the shared interpreter.
        if len(user_text) > 500:
            continue
        for signal in classify_explicit_user_memory(user_text):
            value = signal.metadata.get("normalized_value")
            if (
                signal.metadata.get("attribute") == attribute
                and signal.metadata.get("explicit_user_statement") is True
                and signal.metadata.get("assertion_modality", "asserted") == "asserted"
                and signal.metadata.get("retention_scope") != "session"
                and isinstance(value, str) and 0 < len(value.strip()) <= 120
            ):
                facts.append((item.evidence_id, value.strip()))
    if not facts:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.MISSING, attribute,
            reason="no_user_assertion_in_conversation",
        )
    if len({value.casefold() for _, value in facts}) > 1:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.CONTRADICTORY, attribute,
            evidence_ids=tuple(fid for fid, _ in facts),
            reason="unresolved_conversation_conflict",
        )
    return EvidenceSufficiency(
        EvidenceSufficiencyStatus.SUPPORTED, attribute, value=facts[-1][1],
        evidence_ids=tuple(fid for fid, _ in facts),
        reason="authorized_conversation_assertion_not_durable",
    )
