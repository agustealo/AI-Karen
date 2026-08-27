"""Architecture and semantic contracts for temporal memory evolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.core.memory.claims import MemoryClaimStore
from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim
from ai_karen_engine.core.memory.graph.models import GraphEdge
from ai_karen_engine.core.memory.temporal import (
    MemoryTemporalEvolutionService,
    TemporalEvolutionKind,
    TemporalInterval,
)


UTC = timezone.utc
TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000002"


def _claim(
    value: str,
    *,
    valid_from: datetime,
    valid_until: datetime | None = None,
    asserted_at: datetime | None = None,
    confidence: float = 0.8,
) -> MemoryClaim:
    return MemoryClaim(
        subject="user",
        predicate="preferred_editor",
        object=value,
        tenant_id=TENANT,
        user_id=USER,
        confidence=confidence,
        asserted_at=asserted_at or valid_from,
        event_time=valid_from,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_temporal_interval_is_half_open() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    boundary = start + timedelta(days=10)
    first = TemporalInterval(start=start, end=boundary)
    second = TemporalInterval(start=boundary, end=None)
    assert first.overlaps(second) is False


def test_newer_overlapping_value_supersedes_without_deleting_history() -> None:
    service = MemoryTemporalEvolutionService()
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    second_time = datetime(2026, 6, 1, tzinfo=UTC)

    decision = service.evolve(
        _claim("vim", valid_from=first_time),
        _claim("vscode", valid_from=second_time),
        recorded_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert decision.kind is TemporalEvolutionKind.SUPERSEDE
    assert decision.previous.status is ClaimStatus.SUPERSEDED
    assert decision.previous.valid_until == second_time
    assert decision.incoming.supersedes == decision.previous_ref
    assert decision.incoming.object == "vscode"


def test_non_overlapping_historical_values_coexist() -> None:
    service = MemoryTemporalEvolutionService()
    first_start = datetime(2025, 1, 1, tzinfo=UTC)
    first_end = datetime(2025, 6, 1, tzinfo=UTC)
    second_start = datetime(2026, 1, 1, tzinfo=UTC)

    decision = service.evolve(
        _claim("vim", valid_from=first_start, valid_until=first_end),
        _claim("vscode", valid_from=second_start),
    )

    assert decision.kind is TemporalEvolutionKind.COEXIST
    assert decision.previous.status is ClaimStatus.OBSERVED
    assert decision.incoming.status is ClaimStatus.OBSERVED


def test_backdated_overlap_is_a_contradiction_not_silent_supersession() -> None:
    service = MemoryTemporalEvolutionService()
    current = _claim(
        "vscode",
        valid_from=datetime(2026, 6, 1, tzinfo=UTC),
        asserted_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    backdated = _claim(
        "vim",
        valid_from=datetime(2026, 5, 1, tzinfo=UTC),
        asserted_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    decision = service.evolve(current, backdated)

    assert decision.kind is TemporalEvolutionKind.CONTRADICT
    assert decision.previous.status is ClaimStatus.CONTRADICTED
    assert decision.incoming.status is ClaimStatus.DISPUTED
    assert decision.incoming_ref in decision.previous.contradiction_refs
    assert decision.previous_ref in decision.incoming.contradiction_refs


def test_reobservation_reinforces_provenance_and_confidence() -> None:
    service = MemoryTemporalEvolutionService()
    when = datetime(2026, 1, 1, tzinfo=UTC)
    previous = _claim("vscode", valid_from=when, confidence=0.6)
    previous.provenance = ["conversation:1"]
    incoming = _claim("vscode", valid_from=when, confidence=0.9)
    incoming.provenance = ["conversation:2"]

    decision = service.evolve(previous, incoming)

    assert decision.kind is TemporalEvolutionKind.REINFORCE
    assert decision.previous.confidence == 0.9
    assert decision.previous.provenance == ["conversation:1", "conversation:2"]


def test_temporal_evolution_fails_closed_across_tenants() -> None:
    service = MemoryTemporalEvolutionService()
    when = datetime(2026, 1, 1, tzinfo=UTC)
    previous = _claim("vim", valid_from=when)
    incoming = _claim("vscode", valid_from=when + timedelta(days=1))
    incoming.tenant_id = "00000000-0000-0000-0000-000000000099"

    with pytest.raises(ValueError, match="tenant"):
        service.evolve(previous, incoming)


def test_claim_store_uses_temporal_evolution_for_change() -> None:
    store = MemoryClaimStore()
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    second_time = datetime(2026, 2, 1, tzinfo=UTC)
    claim_id = store.add(_claim("vim", valid_from=first_time))

    decision = store.evolve(claim_id, _claim("vscode", valid_from=second_time))

    assert decision.kind is TemporalEvolutionKind.SUPERSEDE
    assert store.get(claim_id) is not None
    assert store.get(claim_id).valid_until == second_time


def test_graph_edge_contract_carries_temporal_projection_fields() -> None:
    now = datetime(2026, 8, 27, tzinfo=UTC)
    edge = GraphEdge(
        from_id="00000000-0000-0000-0000-000000000010",
        to_id="00000000-0000-0000-0000-000000000011",
        relationship="PREFERS",
        tenant_id=TENANT,
        user_id=USER,
        valid_from=now,
        observed_at=now,
        recorded_at=now,
        source_event_id="00000000-0000-0000-0000-000000000012",
        schema_version=1,
    )

    assert edge.valid_from == now
    assert edge.observed_at == now
    assert edge.recorded_at == now
    assert edge.lifecycle_state == "active"
    assert edge.schema_version == 1
