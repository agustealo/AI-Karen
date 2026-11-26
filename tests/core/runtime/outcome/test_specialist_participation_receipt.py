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


def test_store_accepts_canonical_observation_without_reward():
    from ai_karen_engine.core.runtime.outcome.store import PostgresOutcomeStore

    payload = receipt().to_evidence_payload()
    assert PostgresOutcomeStore._validated_identity(payload) == (
        "tenant-a", "runtime.execution"
    )
    assert not {"status", "reward", "execution_outcome", "user_outcome"} & payload.keys()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outcome_id", "forged"),
        ("tenant_id", "foreign"),
        ("user_id", "foreign"),
        ("trajectory_id", "foreign"),
        ("recorded_at", "2026-11-25T00:00:00"),
        ("recorded_at", "invalid"),
        ("source", "intelligence.ml"),
        ("status", "success"),
        ("reward", 1),
    ],
)
def test_store_rejects_tampered_envelope(field, value):
    from ai_karen_engine.core.runtime.outcome.store import (
        OutcomeStoreError,
        PostgresOutcomeStore,
    )

    payload = receipt().to_evidence_payload()
    payload[field] = value
    with pytest.raises(OutcomeStoreError):
        PostgresOutcomeStore._validated_identity(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "unknown"),
        ("phase", "completed"),
        ("step_id", "foreign"),
        ("specialist_id", ""),
        ("event_type", "agent.tool.execution"),
        ("receipt_version", "unknown"),
        ("reward", 1),
    ],
)
def test_store_rejects_tampered_metadata(field, value):
    from ai_karen_engine.core.runtime.outcome.store import (
        OutcomeStoreError,
        PostgresOutcomeStore,
    )

    payload = receipt().to_evidence_payload()
    payload["metadata"][field] = value
    with pytest.raises(OutcomeStoreError):
        PostgresOutcomeStore._validated_identity(payload)


@pytest.mark.asyncio
async def test_participation_rejects_non_strict_writes_before_io(monkeypatch):
    from ai_karen_engine.core.runtime.outcome import store as module

    def unexpected_io(*args, **kwargs):
        pytest.fail("non-strict participation write reached database")

    monkeypatch.setattr(module, "transaction_scope", unexpected_io)
    monkeypatch.setattr(module, "async_transaction_scope", unexpected_io)
    store = module.PostgresOutcomeStore()
    payload = receipt().to_evidence_payload()
    with pytest.raises(module.OutcomeStoreError, match="requires strict append"):
        store.save_outcome(payload)
    with pytest.raises(module.OutcomeStoreError, match="requires strict append"):
        await store.save_outcome_async(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, 1])
async def test_transactional_append_requires_new_row(rowcount):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.outcome.store import (
        OutcomeStoreError,
        PostgresOutcomeStore,
    )

    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=rowcount))
    )
    payload = receipt().to_evidence_payload()
    if rowcount == 0:
        with pytest.raises(OutcomeStoreError, match="not appended"):
            await PostgresOutcomeStore.append_in_transaction(session, payload)
    else:
        await PostgresOutcomeStore.append_in_transaction(session, payload)
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_store_cannot_acknowledge_specialist_receipt():
    from ai_karen_engine.core.runtime.outcome.store import (
        InMemoryOutcomeStore,
        OutcomeStoreError,
    )

    store = InMemoryOutcomeStore()
    payload = receipt().to_evidence_payload()
    with pytest.raises(OutcomeStoreError, match="requires durable persistence"):
        store.save_outcome(payload)
    with pytest.raises(OutcomeStoreError, match="requires durable persistence"):
        await store.save_outcome_async(payload)
    with pytest.raises(OutcomeStoreError, match="requires durable persistence"):
        await store.save_unique_outcome_async(payload)
    assert store.get_for_trajectory("run-a") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["empty", "recorded", "truncated", "foreign", "bad_phase", "duplicate", "outage"]
)
async def test_specialist_participation_read_is_scoped_and_validated(monkeypatch, mode):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.outcome import store as module

    original = receipt()
    newer = replace(original, phase=SpecialistParticipationPhase.COMPLETED)
    payload = original.to_evidence_payload()
    rows = [{"outcome_id": payload["outcome_id"], "payload": payload}]
    if mode == "empty":
        rows = []
    elif mode == "truncated":
        latest = newer.to_evidence_payload()
        rows.insert(0, {"outcome_id": latest["outcome_id"], "payload": latest})
    elif mode == "foreign":
        foreign = replace(original, user_id="other-owner").to_evidence_payload()
        rows = [{"outcome_id": foreign["outcome_id"], "payload": foreign}]
    elif mode == "bad_phase":
        payload["metadata"]["phase"] = "made-up"
    elif mode == "duplicate":
        rows.append(dict(rows[0]))
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: rows)
        ))
    )
    if mode == "outage":
        session.execute.side_effect = RuntimeError("private database failure")

    @asynccontextmanager
    async def scope(tenant):
        assert tenant == original.tenant_id
        yield session

    monkeypatch.setattr(module, "async_transaction_scope", scope)
    store = module.PostgresOutcomeStore()
    kwargs = dict(
        trajectory_id=original.trajectory_id, correlation_id=original.correlation_id,
        tenant_id=original.tenant_id, user_id=original.user_id, limit=1,
    )
    if mode in {"foreign", "bad_phase", "duplicate", "outage"}:
        with pytest.raises(module.OutcomeStoreError):
            await store.list_specialist_participation_async(**kwargs)
    else:
        result, truncated = await store.list_specialist_participation_async(**kwargs)
        assert truncated is (mode == "truncated")
        assert result == (
            [] if mode == "empty" else
            [newer.to_evidence_payload()] if mode == "truncated" else
            [original.to_evidence_payload()]
        )
    statement, params = session.execute.await_args.args
    assert params == {**kwargs, "limit": 2}
    for predicate in (
        "tenant_id = CAST(:tenant_id AS uuid)", "user_id = CAST(:user_id AS uuid)",
        "trajectory_id = :trajectory_id", "correlation_id = :correlation_id",
        "source = 'runtime.execution'", "agent.specialist.participation",
        "specialist-participation.v1",
    ):
        assert str(statement).index(predicate) < str(statement).index("LIMIT :limit")


@pytest.mark.asyncio
async def test_memory_store_cannot_claim_empty_durable_participation():
    from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore, OutcomeStoreError

    with pytest.raises(OutcomeStoreError):
        await InMemoryOutcomeStore().list_specialist_participation_async(
            trajectory_id="run", correlation_id="corr", tenant_id="tenant", user_id="owner",
        )
