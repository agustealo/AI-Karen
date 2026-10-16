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
class ProfileBeliefEvidence:
    """Adapter for a committed, user-scoped ProfileFact projection.

    The persisted projection key supplies exact scope/cardinality identity.
    Source event ID and value are taken from committed evidence, not invented
    semantic provenance or a fabricated SemanticAssertion.
    """

    tenant_id: str
    user_id: str
    category: str
    attribute: str
    projection_key: str
    scope_key: str
    source_event_id: str
    value: str
    cardinality: FactCardinality
    modality: AssertionModality = AssertionModality.ASSERTED

    @property
    def fact_key(self) -> str:
        return self.projection_key


BeliefCandidate = SemanticAssertion | ProfileBeliefEvidence


def _source_event_id(item: BeliefCandidate) -> str:
    return (
        item.source_event_id if isinstance(item, ProfileBeliefEvidence)
        else item.provenance.source_event_id
    )


def _relation(item: BeliefCandidate) -> tuple[str, ...]:
    if isinstance(item, ProfileBeliefEvidence):
        return ("profile", item.category.casefold(), item.attribute.casefold())
    return (
        "semantic", item.subject.kind.value,
        item.subject.entity_id or item.user_id,
        item.predicate.namespace, item.predicate.relation,
    )


def _scope(item: BeliefCandidate) -> object:
    return item.scope_key if isinstance(item, ProfileBeliefEvidence) else item.qualifiers.scope()


def _object(item: BeliefCandidate) -> tuple[str, str]:
    if isinstance(item, ProfileBeliefEvidence):
        return ("profile_scalar", item.value.casefold())
    return (item.object.type, item.object.canonical_value.casefold())


def resolve_belief(
    incoming: BeliefCandidate,
    current: Sequence[BeliefCandidate],
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
            source_event_ids=(_source_event_id(incoming),),
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
        [_source_event_id(incoming)] +
        [_source_event_id(item) for item in matches]
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
            _relation(item) == _relation(incoming)
            and _scope(item) == _scope(incoming)
            for item in current
        ):
            reason = BeliefResolutionReason.COEXISTING_MEMBER
        elif any(
            _relation(item) == _relation(incoming)
            for item in current
        ):
            reason = BeliefResolutionReason.DISTINCT_CONTEXT
        else:
            reason = BeliefResolutionReason.NEW_IDENTITY
        return BeliefResolution(
            MemoryOperation.CREATE, reason, incoming.fact_key, source_ids,
        )

    same_value = all(_object(item) == _object(incoming) for item in matches)
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
    "ProfileBeliefEvidence",
    "resolve_belief",
]
