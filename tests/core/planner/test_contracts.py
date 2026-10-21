"""Personal planner contracts must not become executable automation definitions."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_karen_engine.core.planner.contracts import (
    CommitmentMutation,
    CommitmentStatus,
    PersonalCommitment,
    PersistedCommitmentReceipt,
)


def commitment(**changes):
    now = datetime.now(timezone.utc)
    data = dict(
        id=uuid4(), tenant_id=uuid4(), owner_id=uuid4(),
        title="Pay electricity bill", timezone="America/Detroit",
        created_at=now, updated_at=now, revision=1,
    )
    data.update(changes)
    return PersonalCommitment(**data)


def test_personal_commitment_is_not_an_agent_execution():
    task = commitment()
    assert task.status is CommitmentStatus.TODO
    assert not hasattr(task, "primary_agent")
    assert not hasattr(task, "execution_id")
    with pytest.raises(ValidationError):
        commitment(primary_agent="unapproved")


def test_planner_requires_timezone_and_aware_datetimes():
    with pytest.raises(ValidationError):
        commitment(timezone="Not/A_Real_Zone")
    with pytest.raises(ValidationError):
        commitment(due_at=datetime(2026, 10, 20, 9, 0))


def test_mutation_requires_idempotency_and_positive_revision():
    request = CommitmentMutation(idempotency_key=uuid4(), expected_revision=1)
    assert request.expected_revision == 1
    with pytest.raises(ValidationError):
        CommitmentMutation(expected_revision=1)
    with pytest.raises(ValidationError):
        CommitmentMutation(idempotency_key=uuid4(), expected_revision=0)


def test_receipt_requires_backend_truth_fields():
    with pytest.raises(ValidationError):
        PersistedCommitmentReceipt(
            commitment_id=uuid4(), tenant_id=uuid4(), revision=1,
            idempotency_key=uuid4(), persisted_at=datetime.now(timezone.utc),
        )
