"""KCR-04E: fail-closed owner isolation for the in-process memory claim store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_karen_engine.core.memory.claims import MemoryClaimStore
from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim

TENANT_A = "00000000-0000-0000-0000-000000000001"
TENANT_B = "00000000-0000-0000-0000-000000000099"
USER_A = "00000000-0000-0000-0000-000000000002"
USER_B = "00000000-0000-0000-0000-000000000098"
START = datetime(2026, 1, 1, tzinfo=UTC)
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


@pytest.mark.parametrize(
    "tenant_id",
    ["", " ", "default", " default", "default ", "DEFAULT", "\tteam-a", "team-a\n"],
)
def test_claim_store_rejects_missing_or_default_tenant(tenant_id: str) -> None:
    with pytest.raises(ValueError, match="explicit tenant"):
        MemoryClaimStore(tenant_id=tenant_id, user_id=USER_A)


def test_claim_store_requires_explicit_owner_and_rejects_blank_user() -> None:
    with pytest.raises(TypeError):
        MemoryClaimStore()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="user scope"):
        MemoryClaimStore(tenant_id=TENANT_A, user_id="")


@pytest.mark.parametrize("user_id", [" ", "\tuser-a", "user-a\n"])
def test_claim_store_rejects_ambiguous_user_scope(user_id: str) -> None:
    with pytest.raises(ValueError, match="user scope"):
        MemoryClaimStore(tenant_id=TENANT_A, user_id=user_id)


def test_identical_claim_values_have_distinct_owner_scoped_keys() -> None:
    first = MemoryClaimStore(**SCOPE_A)
    second = MemoryClaimStore(**SCOPE_B)
    first_claim = _claim()
    second_claim = _claim(tenant_id=TENANT_B, user_id=USER_B)

    first_key = first.add(first_claim)
    second_key = second.add(second_claim)
    assert first_key != second_key

    with pytest.raises(ValueError, match="scope mismatch"):
        first.add(second_claim)

    assert first.get(first_key, **SCOPE_A) is first_claim
    assert second.get(second_key, **SCOPE_B) is second_claim
    assert first.get_by_subject("user", **SCOPE_A) == [first_claim]



def test_delimiter_alias_does_not_overwrite_a_different_subject() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    first = _claim()
    first.subject, first.predicate = "topic:family", "preferred"
    second = _claim()
    second.subject, second.predicate = "topic", "family:preferred"

    # These distinct triples collided under subject:predicate:object IDs.
    assert (
        f"{first.subject}:{first.predicate}:{first.object}"
        == f"{second.subject}:{second.predicate}:{second.object}"
    )
    first_id = store.add(first)
    second_id = store.add(second)
    assert first_id != second_id
    assert store.get(first_id, **SCOPE_A) is first
    assert store.get(second_id, **SCOPE_A) is second
    assert store.get_by_subject("topic:family", **SCOPE_A) == [first]
    assert store.get_by_subject("topic", **SCOPE_A) == [second]


def test_distinct_claim_version_timestamps_have_distinct_keys() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    earlier = _claim()
    later = _claim()
    later.asserted_at = START + timedelta(days=1)
    earlier_id = store.add(earlier)
    later_id = store.add(later)
    assert earlier_id.startswith("claim:")
    assert later_id.startswith("claim:")
    assert earlier_id != later_id
    assert store.get_by_subject("user", **SCOPE_A) == [earlier, later]


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



def test_evolve_replacement_denial_is_atomic() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim(value="vim")
    original_id = store.add(original)
    changed_at = START + timedelta(days=1)
    incoming = _claim(value="vscode")
    incoming.asserted_at = changed_at
    incoming.event_time = changed_at
    incoming.valid_from = changed_at
    blocked = _claim(value="vscode")
    blocked.asserted_at = changed_at
    blocked.event_time = changed_at
    blocked.valid_from = changed_at
    blocked_id = store.add(blocked)
    blocked.user_id = USER_B

    with pytest.raises(ValueError, match="scope mismatch"):
        store.evolve(original_id, incoming, recorded_at=changed_at)

    assert store.get(original_id, **SCOPE_A) is original
    assert original.status is ClaimStatus.OBSERVED
    assert original.valid_until is None
    assert store._claims[blocked_id] is blocked


def test_supersede_replacement_denial_is_atomic() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim(value="vim")
    original_id = store.add(original)
    changed_at = START + timedelta(days=1)
    incoming = _claim(value="vscode")
    incoming.asserted_at = changed_at
    incoming.event_time = changed_at
    incoming.valid_from = changed_at
    blocked = _claim(value="vscode")
    blocked.asserted_at = changed_at
    blocked.event_time = changed_at
    blocked.valid_from = changed_at
    blocked_id = store.add(blocked)
    blocked.user_id = USER_B

    with pytest.raises(ValueError, match="scope mismatch"):
        store.supersede(original_id, incoming)

    assert store.get(original_id, **SCOPE_A) is original
    assert original.status is ClaimStatus.OBSERVED
    assert original.superseded_at is None
    assert original.valid_until is None
    assert incoming.supersedes is None
    assert store._claims[blocked_id] is blocked


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



@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject", "different-subject"),
        ("predicate", "different-predicate"),
        ("object", "different-object"),
        ("asserted_at", START + timedelta(days=1)),
    ],
)

def test_add_cannot_replace_existing_canonical_claim_version() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    original.confidence = 0.95
    original.provenance = ["conversation:verified"]
    claim_id = store.add(original)

    # Re-registering the same object is safe and does not duplicate the index.
    assert store.add(original) == claim_id

    competing = _claim()
    competing.confidence = 0.1
    competing.provenance = ["conversation:unverified"]
    with pytest.raises(ValueError, match="version already exists"):
        store.add(competing)

    assert store.get(claim_id, **SCOPE_A) is original
    assert original.confidence == 0.95
    assert original.provenance == ["conversation:verified"]
    assert store.get_by_subject("user", **SCOPE_A) == [original]


def test_same_owner_identity_mutation_fails_closed(
    field: str, value: object
) -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    setattr(original, field, value)
    incoming = _claim(value="vscode")

    operations = (
        lambda: store.get(claim_id, **SCOPE_A),
        lambda: store.get_by_subject("user", **SCOPE_A),
        lambda: store.get_valid_claims(START, **SCOPE_A),
        lambda: store.get_claims_by_status(ClaimStatus.OBSERVED, **SCOPE_A),
        lambda: store.update_confidence(claim_id, 1.0, **SCOPE_A),
        lambda: store.evolve(claim_id, incoming),
        lambda: store.supersede(claim_id, incoming),
        lambda: store.detect_contradictions(claim_id, **SCOPE_A),
    )
    for operation in operations:
        with pytest.raises(ValueError, match="identity mismatch"):
            operation()

    assert original.status is ClaimStatus.OBSERVED
    assert original.valid_until is None
    assert original.superseded_at is None


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


def test_contradiction_scan_prevalidates_all_records_before_mutation() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    target = _claim(value="vim")
    target_id = store.add(target)
    overlapping = _claim(value="emacs")
    overlapping.valid_from = START + timedelta(days=2)
    overlapping.event_time = overlapping.valid_from
    other_id = store.add(overlapping)
    foreign = _claim(value="vscode")
    store.add(foreign)
    foreign.user_id = USER_B

    with pytest.raises(ValueError, match="scope mismatch"):
        store.detect_contradictions(target_id, **SCOPE_A)

    assert store.get(target_id, **SCOPE_A) is target
    assert store.get(other_id, **SCOPE_A) is overlapping
    assert target.status is ClaimStatus.OBSERVED
    assert overlapping.status is ClaimStatus.OBSERVED
    assert target.contradiction_refs == []
    assert overlapping.contradiction_refs == []


def test_add_rejects_mutated_owner_in_existing_logical_slot() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim()
    claim_id = store.add(original)
    original.user_id = USER_B

    with pytest.raises(ValueError, match="scope mismatch"):
        store.add(_claim())

    original.user_id = USER_A
    assert store.get(claim_id, **SCOPE_A) is original


def test_evolve_rejects_foreign_existing_destination_before_writes() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim(value="vim")
    original_id = store.add(original)
    destination = _claim(value="vscode")
    destination_id = store.add(destination)
    destination.tenant_id = TENANT_B
    incoming = _claim(value="vscode")

    with pytest.raises(ValueError, match="scope mismatch"):
        store.evolve(
            original_id,
            incoming,
            recorded_at=START + timedelta(days=1),
        )

    destination.tenant_id = TENANT_A
    assert store.get(original_id, **SCOPE_A) is original
    assert store.get(destination_id, **SCOPE_A) is destination
    assert original.status is ClaimStatus.OBSERVED
    assert original.valid_until is None
    assert incoming.supersedes is None


def test_supersede_rejects_foreign_existing_destination_before_writes() -> None:
    store = MemoryClaimStore(**SCOPE_A)
    original = _claim(value="vim")
    original_id = store.add(original)
    destination = _claim(value="vscode")
    destination_id = store.add(destination)
    destination.user_id = USER_B
    incoming = _claim(value="vscode")

    with pytest.raises(ValueError, match="scope mismatch"):
        store.supersede(original_id, incoming)

    destination.user_id = USER_A
    assert store.get(original_id, **SCOPE_A) is original
    assert store.get(destination_id, **SCOPE_A) is destination
    assert original.status is ClaimStatus.OBSERVED
    assert original.superseded_at is None
    assert original.valid_until is None
    assert incoming.supersedes is None
