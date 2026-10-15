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

    same_value = all(
        item.object.type == incoming.object.type
        and item.object.canonical_value.casefold()
        == incoming.object.canonical_value.casefold()
        for item in matches
    )
    if same_value:
        return BeliefResolution(
            MemoryOperation.REINFORCE,
            BeliefResolutionReason.REINFORCEMENT,
            incoming.fact_key,
            source_ids,
        )

    if incoming.cardinality is FactCardinality.SET:
        # A SET member includes its value in fact_key; reaching this branch
        # means a hash collision or incompatible assertion contract.
        return BeliefResolution(
            MemoryOperation.QUARANTINE,
            BeliefResolutionReason.UNRESOLVED_CONFLICT,
            incoming.fact_key,
            source_ids,
        )

    if explicit_correction:
        return BeliefResolution(
            MemoryOperation.SUPERSEDE,
            BeliefResolutionReason.SINGLETON_CORRECTION,
            incoming.fact_key,
            source_ids,
            affected_fact_keys=(incoming.fact_key,),
        )

    return BeliefResolution(
        MemoryOperation.QUARANTINE,
        BeliefResolutionReason.UNRESOLVED_CONFLICT,
        incoming.fact_key,
        source_ids,
    )


__all__ = [
    "BeliefResolution",
    "BeliefResolutionReason",
    "resolve_belief",
]
