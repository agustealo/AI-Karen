"""KUI-002D2: contract and fail-closed unit tests for pin-reference storage.

Database mocks exist only in these tests. A real PostgreSQL/RLS integration
test is still required before any API/UI pinning capability may be enabled.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.conversation_runtime_gateway import ConversationSnapshot
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PinSourceUnavailable,
    PresentationPinReference,
)
from ai_karen_engine.persistence.repositories import presentation_pin_repository as module
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    PresentationPinConflict,
    PresentationPinRepository,
    StoredPresentationPin,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation, Message, canonical_message_digest,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE = "22222222-2222-5222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
PIN = "88888888-8888-4888-8888-888888888888"


def ref():
    return PresentationPinReference(
        conversation_id=THREAD,
        assistant_message_id=MESSAGE,
        presentation_id="verified-clock",
        evidence_ref="canonical-clock",
    )


def snapshot():
    return ConversationSnapshot(
        conversation=Conversation(
            id=THREAD, user_id=USER, tenant_id=TENANT, session_id="test-session"
        ),
        messages=(
            Message(
                id=MESSAGE, conversation_id=THREAD, tenant_id=TENANT,
                role="assistant", content="Time verified",
                metadata={
                    "source": "chat_runtime",
                    "request_id": RUN,
                    "response_source": "local_inference",
                    "actual_provider": "local",
                    "actual_model": "verified-model",
                    "verified_presentations_v1": [{
                        "schema_version": 1,
                        "presentation_id": "verified-clock",
                        "component_type": "time.observation",
                        "data": {"formatted": "10:42 PM"},
                        "evidence_ref": "canonical-clock",
                    }],
                },
            ),
        ),
    )


def attestations(snap):
    return {MESSAGE: (RUN, canonical_message_digest(snap.messages[0]))}


def row(*, revision=1, evidence="canonical-clock", position=0):
    return {
        "pin_id": PIN,
        "tenant_id": TENANT,
        "user_id": USER,
        "conversation_id": THREAD,
        "assistant_message_id": MESSAGE,
        "presentation_id": "verified-clock",
        "evidence_ref": evidence,
        "position": position,
        "revision": revision,
    }


class Result:
    def __init__(self, *, first=None, all_rows=None, scalar=None):
        self.first_row = first
        self.all_rows = all_rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.first_row

    def one(self):
        assert self.first_row is not None
        return self.first_row

    def all(self):
        return self.all_rows

    def scalar_one(self):
        return self.scalar


class FakeSession:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.statements = []
        self.params = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return self.outputs.pop(0)


def session_scope(monkeypatch, outputs):
    fake = FakeSession(outputs)
    recorded = []

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id):
        recorded.append((tenant_id, user_id))
        yield fake

    monkeypatch.setattr(module, "async_transaction_scope", transaction)
    return fake, recorded


@pytest.mark.asyncio
async def test_pin_admission_precedes_database_access(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(module, "async_transaction_scope", called)
    snap = snapshot()
    with pytest.raises(PinSourceUnavailable):
        await PresentationPinRepository().pin(
            authenticated_tenant_id=TENANT,
            authenticated_user_id=USER,
            owned_snapshot=snap,
            reference=replace(ref(), evidence_ref="forged"),
            completed_run_attestations=attestations(snap),
        )
    called.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_pin_is_idempotent_and_does_not_change_revision(monkeypatch):
    fake, scopes = session_scope(monkeypatch, [
        Result(), Result(first=row(revision=4, position=5))
    ])
    snap = snapshot()
    result = await PresentationPinRepository().pin(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=USER,
        owned_snapshot=snap,
        reference=ref(),
        completed_run_attestations=attestations(snap),
        position=1,
    )
    assert isinstance(result, StoredPresentationPin)
    assert result.revision == 4 and result.position == 5
    assert len(fake.statements) == 2
    assert scopes == [(TENANT, USER)]
    assert "pg_advisory_xact_lock" in fake.statements[0]


@pytest.mark.asyncio
async def test_changed_source_rejects_duplicate_pin(monkeypatch):
    session_scope(monkeypatch, [Result(), Result(first=row(evidence="other"))])
    snap = snapshot()
    with pytest.raises(PresentationPinConflict):
        await PresentationPinRepository().pin(
            authenticated_tenant_id=TENANT,
            authenticated_user_id=USER,
            owned_snapshot=snap,
            reference=ref(),
            completed_run_attestations=attestations(snap),
        )


@pytest.mark.asyncio
async def test_successful_pin_is_single_transaction_and_bounded(monkeypatch):
    fake, scopes = session_scope(monkeypatch, [
        Result(), Result(first=None), Result(scalar=9),
        Result(first=row()),
    ])
    snap = snapshot()
    created = await PresentationPinRepository().pin(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=USER,
        owned_snapshot=snap,
        reference=ref(),
        completed_run_attestations=attestations(snap),
    )
    assert created.pin_id == PIN
    assert len(fake.statements) == 4
    assert "INSERT INTO public.conversation_presentation_pins" in fake.statements[3]
    assert scopes == [(TENANT, USER)]


@pytest.mark.asyncio
async def test_capacity_is_closed_before_insert(monkeypatch):
    fake, _ = session_scope(monkeypatch, [
        Result(), Result(first=None), Result(scalar=100),
    ])
    snap = snapshot()
    with pytest.raises(PresentationPinConflict, match="capacity"):
        await PresentationPinRepository().pin(
            authenticated_tenant_id=TENANT,
            authenticated_user_id=USER,
            owned_snapshot=snap,
            reference=ref(),
            completed_run_attestations=attestations(snap),
        )
    assert len(fake.statements) == 3


@pytest.mark.asyncio
async def test_reorder_is_revision_cas_and_does_not_hide_stale_conflict(monkeypatch):
    fake, scopes = session_scope(monkeypatch, [Result(first=row(revision=5, position=2))])
    updated = await PresentationPinRepository().reorder_one(
        authenticated_tenant_id=TENANT, authenticated_user_id=USER,
        pin_id=PIN, expected_revision=4, position=2,
    )
    assert updated.revision == 5
    assert "revision = :revision" in fake.statements[0]
    assert fake.params[0]["revision"] == 4
    assert scopes == [(TENANT, USER)]
    session_scope(monkeypatch, [Result(first=None)])
    with pytest.raises(PresentationPinConflict):
        await PresentationPinRepository().reorder_one(
            authenticated_tenant_id=TENANT, authenticated_user_id=USER,
            pin_id=PIN, expected_revision=4, position=2,
        )


@pytest.mark.asyncio
async def test_unpin_is_idempotent_and_scoped(monkeypatch):
    fake, scopes = session_scope(monkeypatch, [Result(first=(PIN,))])
    assert await PresentationPinRepository().unpin(
        authenticated_tenant_id=TENANT, authenticated_user_id=USER, pin_id=PIN
    )
    assert "DELETE FROM public.conversation_presentation_pins" in fake.statements[0]
    assert scopes == [(TENANT, USER)]
    session_scope(monkeypatch, [Result(first=None)])
    assert not await PresentationPinRepository().unpin(
        authenticated_tenant_id=TENANT, authenticated_user_id=USER, pin_id=PIN
    )


@pytest.mark.asyncio
async def test_unverified_internal_list_is_bounded_and_owner_scoped(monkeypatch):
    fake, scopes = session_scope(monkeypatch, [Result(all_rows=[row()])])
    listed = await PresentationPinRepository().read_unverified_references(
        authenticated_tenant_id=TENANT, authenticated_user_id=USER
    )
    assert len(listed) == 1
    assert listed[0].reference == ref()
    assert "LIMIT :maximum" in fake.statements[0]
    assert fake.params[0]["maximum"] == 100
    assert scopes == [(TENANT, USER)]


@pytest.mark.parametrize("invalid", ["", "not-a-uuid", OTHER.upper()])
def test_canonical_scope_identity_is_required(invalid):
    with pytest.raises(ValueError):
        module._uuid(invalid)


@pytest.mark.parametrize("position", [-1, 100, 1.5, True])
def test_pin_position_cannot_escape_bounded_range(position):
    with pytest.raises(ValueError):
        module._check_position(position)


def test_db_migration_preserves_source_fk_rls_and_no_client_grants():
    source = Path("supabase/migrations/20261118213000_64_kui_presentation_pin_references.sql").read_text()
    for required in (
        "REFERENCES public.conversations(conversation_id, tenant_id, user_id)",
        "REFERENCES public.messages(conversation_id, message_id)",
        "ON DELETE CASCADE",
        "FORCE ROW LEVEL SECURITY",
        "app.current_tenant_id",
        "app.current_user_id",
        "REVOKE ALL ON public.conversation_presentation_pins FROM authenticated",
        "conversation_presentation_pin_origin_unique",
        "conversation_presentation_pin_revision_check",
    ):
        assert required in source
    assert "card_html" not in source
    assert "presentation_payload" not in source
