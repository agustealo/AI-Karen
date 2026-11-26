"""Shape and scoped identity tests for specialist participation observations."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.runtime.outcome.contracts import (
    SpecialistParticipationPhase,
    SpecialistParticipationReceipt,
)


def receipt():
    return SpecialistParticipationReceipt(
        tenant_id="tenant-a",
        user_id="user-a",
        trajectory_id="run-a",
        correlation_id="corr-a",
        step_id="step-a",
        specialist_id="researcher",
        phase=SpecialistParticipationPhase.STARTED,
        observed_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "field", ["tenant_id", "user_id", "trajectory_id", "step_id"]
)
def test_identity_changes_with_scope(field):
    original = receipt()
    assert replace(original, **{field: "different"}).receipt_id != original.receipt_id


def test_phase_identity_and_retry_stability():
    original = receipt()
    ids = {replace(original, phase=phase).receipt_id for phase in SpecialistParticipationPhase}
    assert len(ids) == len(SpecialistParticipationPhase)
    assert replace(
        original, observed_at=datetime(2026, 11, 26, tzinfo=timezone.utc)
    ).receipt_id == original.receipt_id


def test_delimiter_ambiguity_does_not_alias_identity():
    original = receipt()
    assert replace(original, tenant_id="a:b", user_id="c").receipt_id != replace(
        original, tenant_id="a", user_id="b:c"
    ).receipt_id


@pytest.mark.parametrize(
    "field",
    ["tenant_id", "user_id", "trajectory_id", "correlation_id", "step_id", "specialist_id"],
)
@pytest.mark.parametrize("invalid", ["", " padded ", "a\n", "a\x7f", "x" * 257, None, 12])
def test_rejects_invalid_identity_fields(field, invalid):
    with pytest.raises(ValueError):
        replace(receipt(), **{field: invalid})


def test_requires_typed_phase_and_aware_timestamp():
    with pytest.raises(ValueError):
        replace(receipt(), phase="started")
    with pytest.raises(ValueError):
        replace(receipt(), observed_at=datetime(2026, 11, 25))
    with pytest.raises(ValueError):
        replace(receipt(), observed_at=None)


def test_receipt_is_immutable():
    original = receipt()
    with pytest.raises(FrozenInstanceError):
        original.tenant_id = "foreign"


def test_conflicting_provenance_cannot_create_another_phase_identity():
    original = receipt()
    assert replace(original, specialist_id="different").receipt_id == original.receipt_id
    assert replace(original, correlation_id="different").receipt_id == original.receipt_id
