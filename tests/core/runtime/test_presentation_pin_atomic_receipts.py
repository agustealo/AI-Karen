"""KUI-002D3B2: deterministic receipt-aware mutation unit contracts.

Mocked SQL responses test repository sequencing only; the independent live
PostgreSQL workflow is required for RLS, atomicity and concurrency proof.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import Mock

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
        Result(), Result(), Result({"pin_id": PIN, "revision": 4}), Result(row),
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
    assert "INSERT INTO public.conversation_presentation_pin_mutation_receipts" in fake.queries[3]


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
        RuntimeError("receipt insert unavailable"),
    ])
    with pytest.raises(PresentationPinUnavailable):
        await PresentationPinRepository().mutate_with_receipt(**request())
    assert state == {"committed": False, "rolled_back": True}
    assert len(fake.queries) == 4


@pytest.mark.asyncio
async def test_missing_unpin_still_records_truthful_absent_receipt(monkeypatch):
    absent = receipt_row(outcome="already_absent")
    fake, state, _ = wire(monkeypatch, [
        Result(), Result(), Result(), Result(absent),
    ])
    result = await PresentationPinRepository().mutate_with_receipt(**request())
    assert result.outcome == "already_absent"
    assert result.pin_id is None
    assert fake.params[-1]["outcome"] == "already_absent"
    assert state["committed"]


@pytest.mark.asyncio
async def test_stale_reorder_rejects_without_receipt(monkeypatch):
    fake, state, _ = wire(monkeypatch, [Result(), Result(), Result()])
    with pytest.raises(PresentationPinConflict, match="revision"):
        await PresentationPinRepository().mutate_with_receipt(**request(
            operation="reorder", expected_revision=2, position=5,
        ))
    assert len(fake.queries) == 3
    assert state["rolled_back"]


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
