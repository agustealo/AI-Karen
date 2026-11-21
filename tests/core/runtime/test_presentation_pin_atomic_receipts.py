"""KUI-002D3B2: deterministic receipt-aware mutation unit contracts.

Mocked SQL responses test repository sequencing only; the independent live
PostgreSQL workflow is required for RLS, atomicity and concurrency proof.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from ai_karen_engine.persistence.repositories import presentation_pin_repository as module
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    PresentationPinConflict,
    PresentationPinRepository,
    PresentationPinUnavailable,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
PIN = "88888888-8888-4888-8888-888888888888"
KEY = "99999999-9999-4999-8999-999999999999"
RECEIPT = "77777777-7777-4777-8777-777777777777"


class Result:
    def __init__(self, first=None):
        self._first = first

    def mappings(self):
        return self

    def first(self):
        return self._first

    def one(self):
        assert self._first is not None
        return self._first

    def all(self):
        return self._first if isinstance(self._first, list) else []

    def scalar_one(self):
        assert self._first is not None
        return self._first


class FakeSession:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.queries = []
        self.params = []

    async def execute(self, statement, params=None):
        self.queries.append(str(statement))
        self.params.append(params)
        response = next(self.outputs)
        if isinstance(response, Exception):
            raise response
        return response


def wire(monkeypatch, outputs):
    fake = FakeSession(outputs)
    states = {"committed": False, "rolled_back": False}
    scopes = []

    @asynccontextmanager
    async def scoped(tenant, *, user_id):
        scopes.append((tenant, user_id))
        try:
            yield fake
            states["committed"] = True
        except Exception:
            states["rolled_back"] = True
            raise

    monkeypatch.setattr(module, "async_transaction_scope", scoped)
    return fake, states, scopes


def receipt_row(*, outcome="unpinned", digest=None, key=KEY, revision=4):
    payload = {
        "schema_version": 1, "operation": "unpin",
        "tenant_id": TENANT, "user_id": USER, "pin_id": PIN,
        "expected_revision": None, "position": None, "reference": None,
    }
    expected_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return {
        "receipt_id": RECEIPT,
        "tenant_id": TENANT,
        "user_id": USER,
        "idempotency_key": key,
        "request_id": "first-request",
        "correlation_id": "first-correlation",
        "request_digest": digest or expected_digest,
        "operation": "unpin",
        "outcome": outcome,
        "pin_id": PIN if outcome != "already_absent" else None,
        "expected_revision": None,
        "committed_revision": revision if outcome == "unpinned" else None,
    }


def request(**updates):
    defaults = {
        "authenticated_tenant_id": TENANT,
        "authenticated_user_id": USER,
        "idempotency_key": KEY,
        "request_id": "first-request",
        "correlation_id": "first-correlation",
        "operation": "unpin",
        "pin_id": PIN,
    }
    defaults.update(updates)
    return defaults


@pytest.mark.asyncio
async def test_unpin_receipt_and_delete_share_single_scoped_commit(monkeypatch):
    row = receipt_row()
    fake, state, scopes = wire(monkeypatch, [
        Result(), Result(), Result({"pin_id": PIN, "revision": 4}),
        Result([]), Result(row),
    ])
    result = await PresentationPinRepository().mutate_with_receipt(**request())
    assert result.receipt_id == RECEIPT
    assert result.outcome == "unpinned"
    assert result.committed_revision == 4
    assert state == {"committed": True, "rolled_back": False}
    assert scopes == [(TENANT, USER)]
    assert "pg_advisory_xact_lock" in fake.queries[0]
    assert "SELECT receipt_id" in fake.queries[1]
    assert "DELETE FROM public.conversation_presentation_pins" in fake.queries[2]
    assert "SELECT pin_id, position, revision" in fake.queries[3]
    assert "INSERT INTO public.conversation_presentation_pin_mutation_receipts" in fake.queries[4]


@pytest.mark.asyncio
async def test_identical_retry_returns_first_receipt_without_a_second_mutation(monkeypatch):
    prior = receipt_row()
    fake, state, _ = wire(monkeypatch, [Result(), Result(prior)])
    result = await PresentationPinRepository().mutate_with_receipt(
        **request(request_id="retry-request", correlation_id="retry-correlation")
    )
    assert result.receipt_id == RECEIPT
    assert result.request_id == "first-request"
    assert len(fake.queries) == 2
    assert state["committed"]


@pytest.mark.asyncio
async def test_different_request_with_same_key_conflicts_before_any_mutation(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(receipt_row(digest="f" * 64)),
    ])
    with pytest.raises(PresentationPinConflict, match="Idempotency"):
        await PresentationPinRepository().mutate_with_receipt(**request())
    assert len(fake.queries) == 2
    assert state["rolled_back"]


@pytest.mark.asyncio
async def test_receipt_insert_failure_rolls_back_the_deleted_pin(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result({"pin_id": PIN, "revision": 4}),
        Result([]), RuntimeError("receipt insert unavailable"),
    ])
    with pytest.raises(PresentationPinUnavailable):
        await PresentationPinRepository().mutate_with_receipt(**request())
    assert state == {"committed": False, "rolled_back": True}
    assert len(fake.queries) == 5


@pytest.mark.asyncio
async def test_missing_unpin_still_records_truthful_absent_receipt(monkeypatch):
    absent = receipt_row(outcome="already_absent")
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result(), Result([]), Result(absent),
    ])
    result = await PresentationPinRepository().mutate_with_receipt(**request())
    assert result.outcome == "already_absent"
    assert result.pin_id is None
    assert fake.params[-1]["outcome"] == "already_absent"
    assert state["committed"]


@pytest.mark.asyncio
async def test_stale_reorder_rejects_without_receipt(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(),
        Result([{"pin_id": PIN, "position": 0, "revision": 3}]),
    ])
    with pytest.raises(PresentationPinConflict, match="revision"):
        await PresentationPinRepository().mutate_with_receipt(**request(
            operation="reorder", expected_revision=2, position=0,
        ))
    assert len(fake.queries) == 3
    assert state["rolled_back"]


SECOND_PIN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
THIRD_PIN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def reorder_receipt(*, pin_id=PIN, expected_revision=2, position=1):
    digest = module._mutation_digest(
        operation="reorder", tenant=TENANT, user=USER,
        pin_id=pin_id, expected_revision=expected_revision,
        position=position, source=None,
    )
    return {
        **receipt_row(digest=digest),
        "operation": "reorder", "outcome": "reordered",
        "pin_id": pin_id, "expected_revision": expected_revision,
        "committed_revision": expected_revision + 1,
    }


@pytest.mark.asyncio
async def test_reorder_atomically_moves_two_pins_and_records_selected_receipt(monkeypatch):
    rows = [
        {"pin_id": PIN, "position": 0, "revision": 2},
        {"pin_id": SECOND_PIN, "position": 1, "revision": 7},
    ]
    updated = [
        {"pin_id": PIN, "revision": 3},
        {"pin_id": SECOND_PIN, "revision": 8},
    ]
    fake, state, scopes = wire(monkeypatch, [
        Result(), Result(), Result(rows), Result(updated),
        Result(reorder_receipt()),
    ])
    receipt = await PresentationPinRepository().mutate_with_receipt(
        **request(operation="reorder", expected_revision=2, position=1),
    )
    assert receipt.outcome == "reordered"
    assert receipt.committed_revision == 3
    assert state == {"committed": True, "rolled_back": False}
    assert scopes == [(TENANT, USER)]
    assert "pg_advisory_xact_lock" in fake.queries[0]
    assert "FOR UPDATE" in fake.queries[2]
    assert "jsonb_to_recordset" in fake.queries[3]
    moves = json.loads(fake.params[3]["move_rows"])
    assert moves == [
        {"pin_id": SECOND_PIN, "position": 0, "expected_revision": 7},
        {"pin_id": PIN, "position": 1, "expected_revision": 2},
    ]
    assert "INSERT INTO public.conversation_presentation_pin_mutation_receipts" in fake.queries[4]


@pytest.mark.asyncio
async def test_reorder_normalizes_legacy_gaps_and_duplicate_positions(monkeypatch):
    rows = [
        {"pin_id": PIN, "position": 0, "revision": 2},
        {"pin_id": SECOND_PIN, "position": 0, "revision": 4},
        {"pin_id": THIRD_PIN, "position": 9, "revision": 3},
    ]
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result(rows),
        Result([{"pin_id": PIN, "revision": 3},
                {"pin_id": THIRD_PIN, "revision": 4}]),
        Result(reorder_receipt(position=2)),
    ])
    await PresentationPinRepository().mutate_with_receipt(
        **request(operation="reorder", expected_revision=2, position=2),
    )
    assert state["committed"]
    assert {
        move["pin_id"]: move["position"]
        for move in json.loads(fake.params[3]["move_rows"])
    } == {THIRD_PIN: 1, PIN: 2}


@pytest.mark.asyncio
async def test_reorder_refuses_out_of_range_destination_before_update(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(),
        Result([{"pin_id": PIN, "position": 0, "revision": 2}]),
    ])
    with pytest.raises(PresentationPinConflict, match="destination"):
        await PresentationPinRepository().mutate_with_receipt(
            **request(operation="reorder", expected_revision=2, position=1),
        )
    assert len(fake.queries) == 3
    assert state["rolled_back"]


@pytest.mark.asyncio
async def test_reorder_missing_bulk_cas_row_rolls_back_without_receipt(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(),
        Result([{"pin_id": PIN, "position": 0, "revision": 2}]),
        Result([]),
    ])
    with pytest.raises(PresentationPinConflict, match="revision"):
        await PresentationPinRepository().mutate_with_receipt(
            **request(operation="reorder", expected_revision=2, position=0),
        )
    assert len(fake.queries) == 4
    assert state == {"committed": False, "rolled_back": True}


@pytest.mark.asyncio
async def test_reorder_receipt_insert_failure_rolls_back_all_moved_rows(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(),
        Result([{"pin_id": PIN, "position": 0, "revision": 2}]),
        Result([{"pin_id": PIN, "revision": 3}]),
        RuntimeError("receipt insert failure"),
    ])
    with pytest.raises(PresentationPinUnavailable):
        await PresentationPinRepository().mutate_with_receipt(
            **request(operation="reorder", expected_revision=2, position=0),
        )
    assert state == {"committed": False, "rolled_back": True}
    assert len(fake.queries) == 5


@pytest.mark.asyncio
async def test_reorder_replayed_receipt_skips_all_row_updates(monkeypatch):
    first = reorder_receipt()
    fake, state, _ = wire(monkeypatch, [Result(), Result(first)])
    replay = await PresentationPinRepository().mutate_with_receipt(
        **request(
            operation="reorder", expected_revision=2, position=1,
            request_id="later-request", correlation_id="later-trace",
        ),
    )
    assert replay.receipt_id == RECEIPT
    assert len(fake.queries) == 2
    assert state["committed"]


@pytest.mark.asyncio
async def test_owner_normalization_closes_unpin_hole_without_touching_other_owner(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result([
            {"pin_id": SECOND_PIN, "position": 0, "revision": 2},
            {"pin_id": THIRD_PIN, "position": 3, "revision": 7},
        ]),
        Result([{"pin_id": THIRD_PIN, "revision": 8}]),
    ])
    async with module.async_transaction_scope(TENANT, user_id=USER) as session:
        result = await module._reposition_owner_pins(
            session, {"tenant": TENANT, "user": USER},
        )
    assert result is None
    assert state["committed"]
    assert len(fake.queries) == 2
    assert "FOR UPDATE" in fake.queries[0]
    assert "p.tenant_id = :tenant AND p.user_id = :user" in fake.queries[1]
    assert json.loads(fake.params[1]["move_rows"]) == [
        {"pin_id": THIRD_PIN, "position": 1, "expected_revision": 7},
    ]


@pytest.mark.asyncio
async def test_owner_normalization_insert_at_occupied_ordinal_shifts_neighbors(monkeypatch):
    inserted = THIRD_PIN
    fake, state, _ = wire(monkeypatch, [
        Result([
            {"pin_id": PIN, "position": 0, "revision": 2},
            {"pin_id": SECOND_PIN, "position": 1, "revision": 4},
            {"pin_id": inserted, "position": 0, "revision": 1},
        ]),
        Result([
            {"pin_id": SECOND_PIN, "revision": 5},
            {"pin_id": inserted, "revision": 2},
        ]),
    ])
    async with module.async_transaction_scope(TENANT, user_id=USER) as session:
        result = await module._reposition_owner_pins(
            session, {"tenant": TENANT, "user": USER},
            selected_pin=inserted, destination=1,
        )
    assert result == 2
    assert state["committed"]
    moves = json.loads(fake.params[1]["move_rows"])
    assert moves == [
        {"pin_id": inserted, "position": 1, "expected_revision": 1},
        {"pin_id": SECOND_PIN, "position": 2, "expected_revision": 4},
    ]


@pytest.mark.asyncio
async def test_normalization_update_cardinality_failure_rolls_back_unpin_and_receipt(monkeypatch):
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result({"pin_id": PIN, "revision": 3}),
        Result([
            {"pin_id": SECOND_PIN, "position": 2, "revision": 1},
        ]),
        Result([]),
    ])
    with pytest.raises(PresentationPinConflict, match="revision"):
        await PresentationPinRepository().mutate_with_receipt(**request())
    assert len(fake.queries) == 5
    assert state == {"committed": False, "rolled_back": True}


@pytest.mark.asyncio
async def test_untrusted_pin_admission_is_denied_before_sql(monkeypatch):
    scope = Mock(side_effect=AssertionError("SQL must not run"))
    monkeypatch.setattr(module, "async_transaction_scope", scope)
    with pytest.raises(ValueError, match="trusted source"):
        await PresentationPinRepository().mutate_with_receipt(**request(
            operation="pin", pin_id=None,
        ))
    scope.assert_not_called()


@pytest.mark.parametrize("mutations", [
    {"idempotency_key": "not-a-uuid"},
    {"request_id": ""},
    {"correlation_id": " "},
    {"operation": "overwrite"},
    {"operation": "unpin", "position": 1},
    {"operation": "reorder", "expected_revision": 0, "position": 1},
])
@pytest.mark.asyncio
async def test_invalid_mutation_contract_never_enters_transaction(monkeypatch, mutations):
    scope = Mock(side_effect=AssertionError("SQL must not run"))
    monkeypatch.setattr(module, "async_transaction_scope", scope)
    with pytest.raises(ValueError):
        await PresentationPinRepository().mutate_with_receipt(**request(**mutations))
    scope.assert_not_called()


@pytest.mark.asyncio
async def test_pin_requires_source_admission_and_receipts_existing_pin(monkeypatch):
    from ai_karen_engine.core.runtime.presentation_pin_admission import PresentationPinReference

    reference = PresentationPinReference(
        conversation_id="44444444-4444-4444-8444-444444444444",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
        presentation_id="verified-clock",
        evidence_ref="verified-evidence",
    )
    admission = Mock(return_value=SimpleNamespace(reference=reference))
    monkeypatch.setattr(module, "admit_presentation_pin_reference", admission)
    pin_row = {
        "pin_id": PIN, "tenant_id": TENANT, "user_id": USER,
        "conversation_id": reference.conversation_id,
        "assistant_message_id": reference.assistant_message_id,
        "presentation_id": reference.presentation_id,
        "evidence_ref": reference.evidence_ref,
        "position": 2, "revision": 3,
    }
    result_row = {
        **receipt_row(outcome="unpinned"),
        "operation": "pin", "outcome": "pinned",
        "expected_revision": None, "committed_revision": 3,
    }
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result(pin_row), Result([]), Result(result_row),
    ])
    receipt = await PresentationPinRepository().mutate_with_receipt(
        **request(
            operation="pin", pin_id=None, position=2,
            reference=reference,
            owned_snapshot=Mock(),
            completed_run_attestations={},
        )
    )
    admission.assert_called_once()
    assert receipt.outcome == "pinned"
    assert state["committed"]
    assert len(fake.queries) == 5
    assert "SELECT" in fake.queries[2]
    assert "INSERT INTO public.conversation_presentation_pin_mutation_receipts" in fake.queries[4]


@pytest.mark.asyncio
async def test_evidence_drift_does_not_write_a_receipt(monkeypatch):
    from ai_karen_engine.core.runtime.presentation_pin_admission import PresentationPinReference

    reference = PresentationPinReference(
        conversation_id="44444444-4444-4444-8444-444444444444",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
        presentation_id="verified-clock",
        evidence_ref="new-evidence",
    )
    monkeypatch.setattr(
        module, "admit_presentation_pin_reference",
        Mock(return_value=SimpleNamespace(reference=reference)),
    )
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result({
            "pin_id": PIN, "evidence_ref": "old-evidence",
        }),
    ])
    with pytest.raises(PresentationPinConflict, match="source has changed"):
        await PresentationPinRepository().mutate_with_receipt(**request(
            operation="pin", pin_id=None, reference=reference,
            owned_snapshot=Mock(), completed_run_attestations={},
        ))
    assert len(fake.queries) == 3
    assert state["rolled_back"]



@pytest.mark.asyncio
async def test_pre_admission_replay_reads_committed_pin_receipt(monkeypatch):
    from ai_karen_engine.core.runtime.presentation_pin_admission import PresentationPinReference

    reference = PresentationPinReference(
        conversation_id="44444444-4444-4444-8444-444444444444",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
        presentation_id="verified-clock",
        evidence_ref="verified-evidence",
    )
    expected = module._mutation_digest(
        operation="pin", tenant=TENANT, user=USER, pin_id=None,
        expected_revision=None, position=2, source=reference,
    )
    committed = {
        **receipt_row(digest=expected),
        "operation": "pin", "outcome": "pinned",
        "expected_revision": None, "committed_revision": 1,
    }
    fake, state, scopes = wire(monkeypatch, [Result(committed)])
    replay = await PresentationPinRepository().replay_committed_pin_receipt(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=USER,
        idempotency_key=KEY,
        reference=reference,
        position=2,
    )
    assert replay is not None and replay.receipt_id == RECEIPT
    assert replay.outcome == "pinned"
    assert len(fake.queries) == 1
    assert "conversation_presentation_pin_mutation_receipts" in fake.queries[0]
    assert fake.params[0]["key"] == KEY
    assert scopes == [(TENANT, USER)]
    assert state["committed"]


@pytest.mark.asyncio
async def test_pre_admission_replay_mismatch_fails_closed(monkeypatch):
    from ai_karen_engine.core.runtime.presentation_pin_admission import PresentationPinReference

    reference = PresentationPinReference(
        conversation_id="44444444-4444-4444-8444-444444444444",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
        presentation_id="verified-clock",
        evidence_ref="verified-evidence",
    )
    fake, state, _ = wire(monkeypatch, [Result(receipt_row())])
    with pytest.raises(PresentationPinConflict, match="Idempotency"):
        await PresentationPinRepository().replay_committed_pin_receipt(
            authenticated_tenant_id=TENANT,
            authenticated_user_id=USER,
            idempotency_key=KEY,
            reference=reference,
            position=2,
        )
    assert len(fake.queries) == 1
    assert state["rolled_back"]


@pytest.mark.asyncio
async def test_pre_admission_replay_missing_receipt_is_not_write_authority(monkeypatch):
    from ai_karen_engine.core.runtime.presentation_pin_admission import PresentationPinReference

    reference = PresentationPinReference(
        conversation_id="44444444-4444-4444-8444-444444444444",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
        presentation_id="verified-clock",
        evidence_ref="verified-evidence",
    )
    fake, _, _ = wire(monkeypatch, [Result()])
    assert await PresentationPinRepository().replay_committed_pin_receipt(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=USER,
        idempotency_key=KEY,
        reference=reference,
    ) is None
    assert len(fake.queries) == 1
