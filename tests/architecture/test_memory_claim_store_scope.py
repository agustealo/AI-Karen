"""KCR-04E: fail-closed owner isolation for the in-process memory claim store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.core.memory.claims import MemoryClaimStore
from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim


TENANT_A = "00000000-0000-0000-0000-000000000001"
TENANT_B = "00000000-0000-0000-0000-000000000099"
USER_A = "00000000-0000-0000-0000-000000000002"
USER_B = "00000000-0000-0000-0000-000000000098"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
SCOPE_A = {"tenant_id": TENANT_A, "user_id": USER_A}
SCOPE_B = {"tenant_id": TENANT_B, "user_id": USER_B}


def _claim(
    *,
    tenant_id: str = TENANT_A,
    user_id: str | None = USER_A,
    value: str = "vim",
) -> MemoryClaim:
    return MemoryClaim(
        subject="user",
        predicate="preferred_editor",
        object=value,
        tenant_id=tenant_id,
        user_id=user_id,
        asserted_at=START,
        event_time=START,
        valid_from=START,
    )


@pytest.mark.parametrize("tenant_id", ["", " ", "default"])
def test_claim_store_rejects_missing_or_default_tenant(tenant_id: str) -> None:
    with pytest.raises(ValueError, match="explicit tenant"):
        MemoryClaimStore(tenant_id=tenant_id, user_id=USER_A)


def test_claim_store_requires_explicit_owner_and_rejects_blank_user() -> None:
    with pytest.raises(TypeError):
        MemoryClaimStore()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="user scope"):
        MemoryClaimStore(tenant_id=TENANT_A, user_id="")


def test_identical_claim_keys_are_isolated_by_store_owner() -> None:
    first = MemoryClaimStore(**SCOPE_A)
    second = MemoryClaimStore(**SCOPE_B)
    first_claim = _claim()
    second_claim = _claim(tenant_id=TENANT_B, user_id=USER_B)

    first_key = first.add(first_claim)
    second_key = second.add(second_claim)
    assert first_key == second_key

    with pytest.raises(ValueError, match="scope mismatch"):
        first.add(second_claim)

    assert first.get(first_key, **SCOPE_A) is first_claim
    assert second.get(second_key, **SCOPE_B) is second_claim
    assert first.get_by_subject("user", **SCOPE_A) == [first_claim]


@pytest.mark.parametrize(
    ("foreign_tenant", "foreign_user"),
    [
        (TENANT_B, USER_A),
        (TENANT_A, USER_B),
    ],
)
def test_all_claim_read_entrypoints_deny_foreign_scope(
    foreign_tenant: str, foreign_user: str
) -> None:
    store = MemoryClaimStore(**SCOPE_A)
    claim_id = store.add(_claim())
    foreign = {"tenant_id": foreign_tenant, "user_id": foreign_user}

    reads = (
        lambda: store.get(claim_id, **foreign),
        lambda: store.get_by_subject("user", **foreign),
        lambda: store.get_valid_claims(START, **foreign),
        lambda: store.get_claims_by_status(ClaimStatus.OBSERVED, **foreign),
        lambda: store.detect_contradictions(claim_id, **foreign),
    )
    for read in reads:
        with pytest.raises(ValueError, match="scope mismatch"):
            read()


def test_missing_read_scope_fails_closed() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    store.add(_claim())
    with pytest.raises(TypeError):
        store.get_valid_claims(START)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        store.get_by_subject("user")  # type: ignore[call-arg]


def test_cross_user_claim_cannot_enter_existing_tenant_store() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    with pytest.raises(ValueError, match="scope mismatch"):
        store.add(_claim(user_id=USER_B))
    assert store.get(claim_id, **SCOPE_A) is original


def test_foreign_evolution_and_supersession_do_not_mutate_existing_claim() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    foreign = _claim(tenant_id=TENANT_B, user_id=USER_B, value="vscode")

    with pytest.raises(ValueError, match="scope mismatch"):
        store.evolve(claim_id, foreign, recorded_at=START + timedelta(days=1))
    with pytest.raises(ValueError, match="scope mismatch"):
        store.supersede(claim_id, foreign)

    assert original.status is ClaimStatus.OBSERVED
    assert original.valid_until is None
    assert store.get(claim_id, **SCOPE_A) is original


def test_foreign_confidence_update_is_rejected_before_mutation() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    original_confidence = original.confidence
    with pytest.raises(ValueError, match="scope mismatch"):
        store.update_confidence(
            claim_id,
            1.0,
            tenant_id=TENANT_B,
            user_id=USER_A,
        )
    assert store.get(claim_id, **SCOPE_A).confidence == original_confidence


def test_mutated_record_scope_fails_closed_on_all_read_paths() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    original.user_id = USER_B

    with pytest.raises(ValueError, match="scope mismatch"):
        store.get(claim_id, **SCOPE_A)
    with pytest.raises(ValueError, match="scope mismatch"):
        store.get_by_subject("user", **SCOPE_A)
    with pytest.raises(ValueError, match="scope mismatch"):
        store.get_valid_claims(START, **SCOPE_A)
    with pytest.raises(ValueError, match="scope mismatch"):
        store.get_claims_by_status(ClaimStatus.OBSERVED, **SCOPE_A)


def test_tenant_level_scope_is_distinct_from_user_level_scope() -> None:
    store = MemoryClaimStore(tenant_id=TENANT_A, user_id=None)
    claim = _claim(user_id=None)
    key = store.add(claim)
    assert store.get(key, tenant_id=TENANT_A, user_id=None) is claim
    with pytest.raises(ValueError, match="scope mismatch"):
        store.get(key, **SCOPE_A)
