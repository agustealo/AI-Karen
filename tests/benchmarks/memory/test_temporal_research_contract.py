"""KCR-02B: research-only temporal contracts against KAREN's actual policy.

This suite tests in-process semantics, not live Postgres as-of retrieval,
RLS, authorization, or persisted consent. The labeled clock oracle is only
an independent research specification, not a KAREN runtime implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim
from ai_karen_engine.core.memory.temporal import (
    MemoryTemporalEvolutionService,
    TemporalEvolutionKind,
    TemporalInterval,
)

UTC = timezone.utc
TENANT_A = "00000000-0000-0000-0000-000000000001"
USER_A = "00000000-0000-0000-0000-000000000002"
TENANT_B = "00000000-0000-0000-0000-000000000003"
USER_B = "00000000-0000-0000-0000-000000000004"


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, 12, tzinfo=UTC)


def _claim(
    content: str,
    *,
    valid_from: datetime,
    asserted_at: datetime,
    tenant_id: str = TENANT_A,
    user_id: str = USER_A,
    valid_until: datetime | None = None,
    metadata: dict | None = None,
) -> MemoryClaim:
    return MemoryClaim(
        subject="user",
        predicate="preferred_editor",
        object=content,
        tenant_id=tenant_id,
        user_id=user_id,
        valid_from=valid_from,
        valid_until=valid_until,
        event_time=valid_from,
        asserted_at=asserted_at,
        metadata=dict(metadata or {}),
    )


@dataclass(frozen=True)
class _Evidence:
    source_event_id: str
    tenant_id: str
    user_id: str
    value: str
    valid_from: datetime
    valid_to: datetime | None
    known_from: datetime
    known_to: datetime | None


def _oracle_as_of(
    evidence: tuple[_Evidence, ...],
    *,
    tenant_id: str,
    user_id: str,
    valid_at: datetime,
    known_at: datetime,
    currently_authorized_source_ids: frozenset[str],
) -> tuple[str, ...]:
    """Synthetic, explicitly authorized two-clock selection specification.

    Authorization is a provided *external* truth. This never calls a real
    ACL/RLS authorizer and must never be used in a runtime retrieval path.
    """
    if not tenant_id or tenant_id == "default" or not user_id:
        raise ValueError("explicit principal required")
    if valid_at.tzinfo is None or known_at.tzinfo is None:
        raise ValueError("time coordinates must be timezone-aware")
    return tuple(
        e.value
        for e in evidence
        if e.tenant_id == tenant_id
        and e.user_id == user_id
        and e.source_event_id in currently_authorized_source_ids
        and e.valid_from <= valid_at
        and (e.valid_to is None or valid_at < e.valid_to)
        and e.known_from <= known_at
        and (e.known_to is None or known_at < e.known_to)
    )


def test_karen_temporal_version_preserves_valid_vs_recorded_clock() -> None:
    claim = _claim(
        "vim",
        valid_from=_dt(1),
        asserted_at=_dt(6),
        metadata={"recorded_at": _dt(8).isoformat()},
    )
    service = MemoryTemporalEvolutionService()
    derived = service.version(claim)
    assert derived.valid_time == TemporalInterval(start=_dt(1), end=None)
    assert derived.event_time == _dt(1)
    assert derived.recorded_at == _dt(8)

    explicit = service.version(claim, recorded_at=_dt(10))
    assert explicit.recorded_at == _dt(10)
    assert explicit.valid_time == derived.valid_time


def test_karen_backdated_conflict_keeps_source_versions_and_record_time() -> None:
    service = MemoryTemporalEvolutionService()
    current = _claim("vscode", valid_from=_dt(6), asserted_at=_dt(6))
    backdated = _claim("vim", valid_from=_dt(2), asserted_at=_dt(16))
    decision = service.evolve(current, backdated, recorded_at=_dt(18))

    assert decision.kind is TemporalEvolutionKind.CONTRADICT
    assert decision.recorded_at == _dt(18)
    assert decision.previous.status is ClaimStatus.CONTRADICTED
    assert decision.incoming.status is ClaimStatus.DISPUTED
    assert decision.previous_ref in decision.incoming.contradiction_refs
    assert decision.incoming_ref in decision.previous.contradiction_refs
    assert decision.previous.valid_from == _dt(6)
    assert decision.incoming.valid_from == _dt(2)


def test_utc_and_half_open_interval_boundary_are_explicit() -> None:
    earlier = TemporalInterval(start=_dt(1), end=_dt(10))
    later = TemporalInterval(start=_dt(10))
    assert earlier.overlaps(later) is False
    assert earlier.end == later.start


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known KCR-02B gap: MemoryClaim.is_valid treats valid_until as "
        "inclusive, unlike TemporalInterval and PostgreSQL half-open predicates"
    ),
)
def test_known_gap_claim_valid_until_should_be_exclusive() -> None:
    # Deliberately expected to fail on current KAREN code. Do not hide or
    # normalize the mismatch by asserting the current incorrect behavior.
    claim = _claim(
        "vim", valid_from=_dt(1), asserted_at=_dt(1), valid_until=_dt(10)
    )
    assert claim.is_valid(_dt(9)) is True
    assert claim.is_valid(_dt(10)) is False


def test_oracle_distinguishes_known_at_from_valid_at() -> None:
    history = (
        _Evidence(
            "source-1", TENANT_A, USER_A, "vim",
            _dt(1), None, _dt(5), _dt(20),
        ),
        _Evidence(
            "source-2", TENANT_A, USER_A, "vscode",
            _dt(1), None, _dt(20), None,
        ),
    )
    first = _oracle_as_of(
        history,
        tenant_id=TENANT_A,
        user_id=USER_A,
        valid_at=_dt(3),
        known_at=_dt(12),
        currently_authorized_source_ids=frozenset({"source-1", "source-2"}),
    )
    corrected = _oracle_as_of(
        history,
        tenant_id=TENANT_A,
        user_id=USER_A,
        valid_at=_dt(3),
        known_at=_dt(24),
        currently_authorized_source_ids=frozenset({"source-1", "source-2"}),
    )
    assert first == ("vim",)
    assert corrected == ("vscode",)
    # These results specify desired history, not an existing KAREN query API.


def test_oracle_scope_and_revocation_remove_all_derived_access() -> None:
    evidence = (
        _Evidence("source-1", TENANT_A, USER_A, "authorized", _dt(1), None, _dt(2), None),
        _Evidence("source-2", TENANT_A, USER_A, "revoked", _dt(1), None, _dt(2), None),
        _Evidence("source-3", TENANT_B, USER_A, "cross-tenant", _dt(1), None, _dt(2), None),
        _Evidence("source-4", TENANT_A, USER_B, "cross-user", _dt(1), None, _dt(2), None),
    )
    query = dict(
        tenant_id=TENANT_A, user_id=USER_A,
        valid_at=_dt(10), known_at=_dt(11),
    )
    before = _oracle_as_of(
        evidence, **query,
        currently_authorized_source_ids=frozenset(
            {"source-1", "source-2", "source-3", "source-4"}
        ),
    )
    after = _oracle_as_of(
        evidence, **query,
        currently_authorized_source_ids=frozenset({"source-1"}),
    )
    assert before == ("authorized", "revoked")
    assert after == ("authorized",)


def test_karen_claim_evolution_rejects_cross_user_even_with_same_fact_key() -> None:
    service = MemoryTemporalEvolutionService()
    a = _claim("vim", valid_from=_dt(1), asserted_at=_dt(1))
    b = _claim(
        "vscode", valid_from=_dt(2), asserted_at=_dt(2), user_id=USER_B
    )
    with pytest.raises(ValueError, match="user"):
        service.evolve(a, b)
