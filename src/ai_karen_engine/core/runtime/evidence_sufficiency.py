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
    CognitiveContext, EvidenceContradictionStatus, EvidenceFactSemantics,
    EvidenceSource,
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
    cardinality: FactCardinality | None = None,
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
    live: list[tuple[str, str, EvidenceFactSemantics | None]] = []
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
        semantics = getattr(evidence, "fact_semantics", None)
        live.append((
            evidence.evidence_id, value,
            semantics if isinstance(semantics, EvidenceFactSemantics) else None,
        ))

    if conflict_ids:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.CONTRADICTORY, attribute,
            evidence_ids=tuple(conflict_ids), reason="flagged_contradiction",
        )
    if live:
        if cardinality is None:
            # Only typed, source-validated profile projections can teach
            # runtime about SET or scoped cardinality. Ordinary snippets
            # and legacy rows retain the conservative singleton behavior.
            projected = [item[2] for item in live if item[2] is not None]
            if projected:
                if (
                    len(projected) != len(live)
                    or any(item.attribute != attribute for item in projected)
                    or len({item.cardinality for item in projected}) != 1
                    or len({item.semantic_scope for item in projected}) != 1
                ):
                    return EvidenceSufficiency(
                        EvidenceSufficiencyStatus.AMBIGUOUS, attribute,
                        evidence_ids=tuple(item[0] for item in live),
                        reason="mixed_or_unverified_profile_semantics",
                    )
                cardinality = projected[0].cardinality
                # A scoped fact cannot answer a global question merely
                # because it was the only value retrieved. Query-scope
                # matching needs a separately governed, typed query intent.
                # Until available, never globalize project/task/location
                # preferences or scoped singletons.
                scope = dict(projected[0].semantic_scope)
                if (
                    cardinality is FactCardinality.SCOPED_SINGLETON
                    or any(
                        scope.get(key) and scope[key] not in {"global", "user"}
                        for key in ("scope", "project_id", "task_id", "task_type", "location")
                    )
                ):
                    return EvidenceSufficiency(
                        EvidenceSufficiencyStatus.AMBIGUOUS, attribute,
                        evidence_ids=tuple(item[0] for item in live),
                        reason="scoped_fact_requires_query_scope",
                    )
            else:
                cardinality = FactCardinality.SINGLETON
        if cardinality is FactCardinality.SET:
            distinct: dict[str, str] = {}
            for _evidence_id, value, _semantics in live:
                distinct.setdefault(value.casefold(), value)
            return EvidenceSufficiency(
                EvidenceSufficiencyStatus.SUPPORTED_SET, attribute,
                evidence_ids=tuple(item[0] for item in live),
                values=tuple(distinct.values()),
                reason="authorized_set_memory_evidence",
            )
        values = {value.casefold() for _, value, _semantics in live}
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
    cardinality: FactCardinality = FactCardinality.SINGLETON,
) -> EvidenceSufficiency:
    """Evaluate authorized conversation facts with trusted expected cardinality.

    The caller may provide SET only after current saved evidence independently
    proves that cardinality. Conversation text never grants itself SET policy.
    """
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
    facts: list[tuple[str, str, bool]] = []
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
        if len(user_text) > 500 or (
            not user_text.casefold().startswith(
                ("my ", "i ", "i'm ", "i’ve ", "i've ", "call me ")
            )
            and not attribute.startswith("favorite_")
        ):
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
                facts.append((
                    item.evidence_id,
                    value.strip(),
                    signal.metadata.get("explicit_correction") is True
                    and signal.metadata.get("source") in {
                        "explicit_semantic_rule", "explicit_general_fact_rule",
                    },
                ))
    if not facts:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.MISSING, attribute,
            reason="no_user_assertion_in_conversation",
        )
    # Only a directly classified, explicit self-correction may supersede
    # older conversation assertions. Recency alone is not reconciliation.
    # Preserve the raw conversation; this merely selects sufficient evidence.
    last_correction = max(
        (index for index, fact in enumerate(facts) if fact[2]),
        default=0,
    )
    current_facts = facts[last_correction:]
    if cardinality is FactCardinality.SET and any(fact[2] for fact in facts):
        # A direct correction can replace or narrow a set, not merely add a
        # compatible value. Only governed belief projection may settle this.
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.AMBIGUOUS, attribute,
            evidence_ids=tuple(fid for fid, _, _ in facts),
            reason="set_correction_requires_reconciliation",
        )
    if cardinality is FactCardinality.SET:
        distinct: dict[str, str] = {}
        for _fid, value, _correction in current_facts:
            distinct.setdefault(value.casefold(), value)
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.SUPPORTED_SET, attribute,
            evidence_ids=tuple(fid for fid, _, _ in current_facts),
            values=tuple(distinct.values()),
            reason="authorized_conversation_set_not_durable",
        )
    if len({value.casefold() for _, value, _ in current_facts}) > 1:
        return EvidenceSufficiency(
            EvidenceSufficiencyStatus.CONTRADICTORY, attribute,
            evidence_ids=tuple(fid for fid, _, _ in current_facts),
            reason="unresolved_conversation_conflict",
        )
    return EvidenceSufficiency(
        EvidenceSufficiencyStatus.SUPPORTED, attribute,
        value=current_facts[-1][1],
        evidence_ids=tuple(fid for fid, _, _ in current_facts),
        reason="authorized_conversation_assertion_not_durable",
    )
