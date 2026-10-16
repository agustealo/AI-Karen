"""Pure projection-state reconciliation for governed semantic memory assertions.

No persistence or authorization is performed here. NeuroVault owns mutation.
This policy reconciles only evidence that has already passed admission; it
retains independent assertions and returns a proposed projection operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .semantic_contract import (
    AssertionModality,
    FactCardinality,
    MemoryOperation,
    SemanticAssertion,
)


class BeliefResolutionReason(str, Enum):
    NEW_IDENTITY = "new_identity"
    REINFORCEMENT = "reinforcement"
    COEXISTING_MEMBER = "coexisting_member"
    SINGLETON_CORRECTION = "singleton_correction"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    NON_ASSERTED_EVIDENCE = "non_asserted_evidence"
    DISTINCT_CONTEXT = "distinct_context"
    EVENT_OBSERVATION = "event_observation"


@dataclass(frozen=True, slots=True)
class BeliefResolution:
    operation: MemoryOperation
    reason: BeliefResolutionReason
    fact_key: str
    source_event_ids: tuple[str, ...]
    affected_fact_keys: tuple[str, ...] = ()



@dataclass(frozen=True, slots=True)
class ProfileProjectionEvidence:
    """Canonical profile-slot adapter, not a fabricated SemanticAssertion.

    Projection rows lack the complete typed assertion provenance contract.
    Only use real scoped event IDs, the verified slot key and actual values.
    """

    tenant_id: str
    user_id: str
    fact_key: str
    value: str
    source_event_id: str
    cardinality: FactCardinality = FactCardinality.SINGLETON
    modality: AssertionModality = AssertionModality.ASSERTED


def _resolve_competing_values(
    *,
    fact_key: str,
    incoming_value: tuple[str, str],
    current_values: Sequence[tuple[str, str]],
    cardinality: FactCardinality,
    source_ids: tuple[str, ...],
    explicit_correction: bool,
) -> BeliefResolution:
    """One conflict policy shared by semantic and legacy profile projections."""
    same_value = all(
        kind == incoming_value[0]
        and value.casefold() == incoming_value[1].casefold()
        for kind, value in current_values
    )
    if same_value:
        return BeliefResolution(
            MemoryOperation.REINFORCE,
            BeliefResolutionReason.REINFORCEMENT,
            fact_key,
            source_ids,
        )
    if cardinality is FactCardinality.SET:
        return BeliefResolution(
            MemoryOperation.QUARANTINE,
            BeliefResolutionReason.UNRESOLVED_CONFLICT,
            fact_key,
            source_ids,
        )
    if explicit_correction:
        return BeliefResolution(
            MemoryOperation.SUPERSEDE,
            BeliefResolutionReason.SINGLETON_CORRECTION,
            fact_key,
            source_ids,
            affected_fact_keys=(fact_key,),
        )
    return BeliefResolution(
        MemoryOperation.QUARANTINE,
        BeliefResolutionReason.UNRESOLVED_CONFLICT,
        fact_key,
        source_ids,
    )


def is_trusted_profile_correction(
    *,
    source_type: str,
    signal_metadata: dict,
    merged_metadata: dict,
) -> bool:
    """Recognize user-authorized corrections without trusting transport hints.

    Classified assertions may correct current beliefs through either ordinary
    chat with an explicit linguistic correction or the dedicated authenticated
    profile-correction ingress. Neither route metadata nor source recency can
    manufacture classifier-owned facts. Admission and authorization remain
    upstream of this pure decision policy.
    """
    if (
        signal_metadata.get("source") not in {
            "explicit_semantic_rule", "explicit_general_fact_rule",
            "explicit_open_relation"
        }
        or signal_metadata.get("explicit_user_statement") is not True
    ):
        return False
    if source_type == "profile_correction":
        return True
    return (
        source_type in {"chat_user", "chat"}
        and signal_metadata.get("explicit_correction") is True
        and merged_metadata.get("explicit_correction") is True
    )


def resolve_profile_projection(
    incoming: ProfileProjectionEvidence,
    current: Sequence[ProfileProjectionEvidence],
    *,
    explicit_correction: bool = False,
) -> BeliefResolution:
    """Apply existing belief authority to the evidence available in SQL views.

    The caller identifies matching profile slots with profile_projection_key;
    this function cannot decide consent, admission or execute any SQL.
    """
    if incoming.modality is not AssertionModality.ASSERTED:
        return BeliefResolution(
            MemoryOperation.QUARANTINE,
            BeliefResolutionReason.NON_ASSERTED_EVIDENCE,
            incoming.fact_key,
            (incoming.source_event_id,),
        )
    for item in current:
        if item.tenant_id != incoming.tenant_id or item.user_id != incoming.user_id:
            raise ValueError("cross-scope belief comparison is forbidden")
        if item.fact_key != incoming.fact_key:
            raise ValueError("profile projection comparison must share a verified slot")
        if item.cardinality != incoming.cardinality:
            raise ValueError("profile projection cardinality mismatch")
    source_ids = tuple(dict.fromkeys(
        [incoming.source_event_id, *(item.source_event_id for item in current)]
    ))
    if not current:
        return BeliefResolution(
            MemoryOperation.CREATE, BeliefResolutionReason.NEW_IDENTITY,
            incoming.fact_key, source_ids,
        )
    return _resolve_competing_values(
        fact_key=incoming.fact_key,
        incoming_value=("string", incoming.value),
        current_values=[("string", item.value) for item in current],
        cardinality=incoming.cardinality,
        source_ids=source_ids,
        explicit_correction=explicit_correction,
    )

def resolve_belief(
    incoming: SemanticAssertion,
    current: Sequence[SemanticAssertion],
    *,
    explicit_correction: bool = False,
) -> BeliefResolution:
    """Propose a state operation without mutating any underlying assertion.

    Corrections are a validated upstream semantic decision, not inferred from
    source order, recency, or a model-generated confidence score.
    """
    if incoming.modality is not AssertionModality.ASSERTED:
        return BeliefResolution(
            operation=MemoryOperation.QUARANTINE,
            reason=BeliefResolutionReason.NON_ASSERTED_EVIDENCE,
            fact_key=incoming.fact_key,
            source_event_ids=(incoming.provenance.source_event_id,),
        )

    for item in current:
        if item.tenant_id != incoming.tenant_id or item.user_id != incoming.user_id:
            raise ValueError("cross-scope belief comparison is forbidden")

    matches = [
        item for item in current
        if item.fact_key == incoming.fact_key
        and item.modality is AssertionModality.ASSERTED
    ]
    source_ids = tuple(dict.fromkeys(
        [incoming.provenance.source_event_id] +
        [item.provenance.source_event_id for item in matches]
    ))

    if incoming.cardinality in (
        FactCardinality.EVENT, FactCardinality.TEMPORAL_SERIES
    ):
        if matches:
            return BeliefResolution(
                MemoryOperation.REINFORCE,
                BeliefResolutionReason.REINFORCEMENT,
                incoming.fact_key,
                source_ids,
            )
        return BeliefResolution(
            MemoryOperation.CREATE,
            BeliefResolutionReason.EVENT_OBSERVATION,
            incoming.fact_key,
            source_ids,
        )

    if not matches:
        if incoming.cardinality is FactCardinality.SET and any(
            item.subject == incoming.subject
            and item.predicate == incoming.predicate
            and item.qualifiers.scope() == incoming.qualifiers.scope()
            for item in current
        ):
            reason = BeliefResolutionReason.COEXISTING_MEMBER
        elif any(
            item.subject == incoming.subject
            and item.predicate == incoming.predicate
            for item in current
        ):
            reason = BeliefResolutionReason.DISTINCT_CONTEXT
        else:
            reason = BeliefResolutionReason.NEW_IDENTITY
        return BeliefResolution(
            MemoryOperation.CREATE, reason, incoming.fact_key, source_ids,
        )

    return _resolve_competing_values(
        fact_key=incoming.fact_key,
        incoming_value=(incoming.object.type, incoming.object.canonical_value),
        current_values=[
            (item.object.type, item.object.canonical_value) for item in matches
        ],
        cardinality=incoming.cardinality,
        source_ids=source_ids,
        explicit_correction=explicit_correction,
    )


__all__ = [
    "BeliefResolution",
    "BeliefResolutionReason",
    "resolve_belief",
    "ProfileProjectionEvidence",
    "resolve_profile_projection",
    "is_trusted_profile_correction",
]
