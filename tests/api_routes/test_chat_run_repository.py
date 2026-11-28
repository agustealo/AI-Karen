"""CK-07A SQL-scoped, fenced ledger contract without a fake production backend."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.persistence.repositories import chat_run_repository as repository

OWNER = "11111111-1111-1111-1111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
THREAD = "4f6dc890-2644-4ff8-8f15-888888888888"


class Transaction:
    def __init__(self, values: list[str | bool | None]):
        self.values = iter(values)
        self.sql: list[str] = []
        self.parameters: list[dict[str, Any]] = []

    async def execute(self, statement, parameters):
        self.sql.append(str(statement))
        self.parameters.append(parameters)
        return SimpleNamespace(scalar_one_or_none=lambda: next(self.values))


def scoped_transaction(monkeypatch, transaction):
    @asynccontextmanager
    async def begin(tenant_id: str, *, user_id: str | None = None):
        assert tenant_id == TENANT
        assert user_id == OWNER
        yield transaction

    monkeypatch.setattr(repository, "async_transaction_scope", begin)


@pytest.mark.asyncio
async def test_admit_only_in_authenticated_rls_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Schema readiness is checked before any mutation. The expiry UPDATE
    # has no scalar receipt; the next scalar is the INSERT receipt.
    transaction = Transaction([True, str(uuid.uuid4())])
    scoped_transaction(monkeypatch, transaction)
    lease = await repository.SqlChatRunRepository().admit(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
        submission_id="original-user-turn",
    )
    assert lease is not None
    assert lease.user_id == OWNER
    assert lease.tenant_id == TENANT
    assert lease.conversation_id == THREAD
    assert lease.transport_run_id == "client-1"
    assert "runtime_chat_runs_unresolved_idx" in transaction.sql[0]
    assert "runtime_chat_runs_submission_idx" in transaction.sql[0]
    assert "conversation_id = CAST(:conversation AS uuid)" in transaction.sql[1]
    assert transaction.parameters[1]["conversation"] == THREAD
    assert "ON CONFLICT DO NOTHING" in transaction.sql[2]
    assert "RETURNING execution_id" in transaction.sql[2]
    assert transaction.parameters[2]["owner"] == OWNER
    assert transaction.parameters[2]["tenant"] == TENANT
    assert transaction.parameters[2]["conversation"] == THREAD
    assert transaction.parameters[2]["token"] == lease.lease_token
    assert transaction.parameters[2]["submission_id"] == "original-user-turn"


@pytest.mark.asyncio
async def test_duplicate_admission_is_not_restarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([True, None])
    scoped_transaction(monkeypatch, transaction)
    assert await repository.SqlChatRunRepository().admit(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
    ) is None


@pytest.mark.asyncio
async def test_lease_heartbeat_and_final_are_fenced_by_owner_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([str(uuid.uuid4()), None])
    scoped_transaction(monkeypatch, transaction)
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()),
        lease_token=str(uuid.uuid4()),
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
    )
    repo = repository.SqlChatRunRepository()
    assert await repo.renew(lease) is True
    assert await repo.finish(lease, status="failed", error_code="CHAT_TEST_ERROR") is False
    assert len(transaction.sql) == 2
    for sql, args in zip(transaction.sql, transaction.parameters):
        assert "lease_token = CAST(:token AS uuid)" in sql
        assert "lease_expires_at > NOW()" in sql
        assert "tenant_id = CAST(:tenant AS uuid)" in sql
        assert "user_id = CAST(:owner AS uuid)" in sql
        assert "conversation_id = CAST(:conversation AS uuid)" in sql
        assert args["token"] == lease.lease_token
    assert "cancel_requested_at IS NULL" in transaction.sql[1]


@pytest.mark.asyncio
async def test_invalid_identifiers_do_not_open_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def unreachable(*args, **kwargs):
        raise AssertionError("invalid identity must fail before SQL")
        yield

    monkeypatch.setattr(repository, "async_transaction_scope", unreachable)
    repo = repository.SqlChatRunRepository()
    for kwargs in (
        {"tenant_id": "not-a-uuid"},
        {"user_id": "forged-user"},
        {"conversation_id": "wrong"},
        {"transport_run_id": "untrusted run id"},
    ):
        supplied = {
            "tenant_id": TENANT,
            "user_id": OWNER,
            "conversation_id": THREAD,
            "transport_run_id": "client-1",
            "request_id": "request-1",
            "correlation_id": "correlation-1",
            **kwargs,
        }
        with pytest.raises(ValueError):
            await repo.admit(**supplied)


@pytest.mark.asyncio
async def test_cancel_locks_only_the_owned_row_and_reuses_the_scoped_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LockedTransaction:
        def __init__(self):
            self.sql: list[str] = []
            self.params: list[dict[str, Any]] = []

        async def execute(self, statement, parameters):
            sql = str(statement)
            self.sql.append(sql)
            self.params.append(parameters)
            if "FOR UPDATE" in sql:
                return SimpleNamespace(
                    mappings=lambda: SimpleNamespace(
                        one_or_none=lambda: {
                            "status": "running", "lease_expires_at": object(),
                        },
                    ),
                )
            return SimpleNamespace(scalar_one_or_none=lambda: "cancelling")

    tx = LockedTransaction()
    scoped_transaction(monkeypatch, tx)
    state = await repository.SqlChatRunRepository().request_cancel(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="run-a",
    )
    assert state == "cancelling"
    assert len(tx.sql) == 2
    assert "FOR UPDATE" in tx.sql[0]
    assert "cancel_requested_at" in tx.sql[1]
    assert "status IN ('running', 'cancelling')" in tx.sql[1]
    for args in tx.params:
        assert args == {
            "tenant": TENANT, "owner": OWNER,
            "conversation": THREAD, "run_id": "run-a",
        }


@pytest.mark.asyncio
async def test_stop_rejects_absent_scoped_record_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingTransaction:
        def __init__(self):
            self.calls = 0

        async def execute(self, statement, parameters):
            self.calls += 1
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: None),
            )

    tx = MissingTransaction()
    scoped_transaction(monkeypatch, tx)
    result = await repository.SqlChatRunRepository().request_cancel(
        tenant_id=TENANT, user_id=OWNER,
        conversation_id=THREAD, transport_run_id="run-missing",
    )
    assert result is None
    assert tx.calls == 1


@pytest.mark.asyncio
async def test_worker_cancel_observation_is_scoped_to_its_fencing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tx = Transaction(["cancelling"])
    scoped_transaction(monkeypatch, tx)
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()),
        lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER,
        conversation_id=THREAD, transport_run_id="run-a",
        request_id="request-a", correlation_id="correlation-a",
    )
    assert await repository.SqlChatRunRepository().cancel_requested(lease) is True
    assert "lease_token = CAST(:token AS uuid)" in tx.sql[0]
    assert "cancel_requested_at IS NOT NULL" in tx.sql[0]
    assert tx.parameters[0]["token"] == lease.lease_token


@pytest.mark.asyncio
async def test_ledger_refuses_standalone_completed_status() -> None:
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="run-proof", request_id="request-proof",
        correlation_id="correlation-proof",
    )
    with pytest.raises(ValueError, match="requires_atomic_transcript_commit"):
        await repository.SqlChatRunRepository().finish(lease, status="completed")


@pytest.mark.asyncio
async def test_atomic_completion_receipt_checks_scoped_record_and_both_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([1, None])
    scoped_transaction(monkeypatch, transaction)
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="run-proof", request_id="request-proof",
        correlation_id="correlation-proof",
    )
    repo = repository.SqlChatRunRepository()
    assert await repo.committed_turn(
        lease,
        user_message_id="11111111-1111-5111-8111-111111111111",
        assistant_message_id="22222222-2222-5222-8222-222222222222",
    )
    assert await repo.completed(lease) is False
    assert "JOIN messages u" in transaction.sql[0]
    assert "JOIN messages a" in transaction.sql[0]
    assert "status = 'completed'" in transaction.sql[0]
    assert "r.request_id = :request_id" in transaction.sql[0]
    assert "r.correlation_id = :correlation_id" in transaction.sql[0]
    assert "u.message_metadata::jsonb ->> 'request_id'" in transaction.sql[0]
    assert transaction.parameters[0]["tenant"] == TENANT
    assert transaction.parameters[0]["owner"] == OWNER
    assert transaction.parameters[0]["conversation"] == THREAD


@pytest.mark.asyncio
async def test_replay_attestation_has_immutable_digest_and_owner_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assistant_id = "22222222-2222-5222-8222-222222222222"
    request_id = "request-proof"
    digest = "a" * 64

    class AttestationTransaction:
        def __init__(self):
            self.sql = ""
            self.scope = {}

        async def execute(self, statement, parameters):
            self.sql = str(statement)
            self.scope = parameters
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                all=lambda: [{
                    "message_id": assistant_id,
                    "request_id": request_id,
                    "assistant_message_digest": digest,
                }],
            ))

    tx = AttestationTransaction()
    scoped_transaction(monkeypatch, tx)
    proof = await repository.SqlChatRunRepository().completed_replay_attestations(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
    )
    assert proof == {assistant_id: (request_id, digest)}
    assert "r.assistant_message_digest" in tx.sql
    assert "r.user_message_id IS NOT NULL" in tx.sql
    assert "r.status = 'completed'" in tx.sql
    assert "JOIN messages a" in tx.sql
    assert "JOIN messages u" in tx.sql
    assert tx.scope == {"tenant": TENANT, "owner": OWNER, "conversation": THREAD}


def test_replay_digest_migration_preserves_legacy_rows_without_fake_backfill():
    root = Path(__file__).resolve().parents[2]
    migration = root / (
        "supabase/migrations/20261025040000_45_runtime_chat_replay_digest.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "assistant_message_digest CHAR(64)" in sql
    assert "ck_runtime_chat_completed_digest" in sql
    assert "NOT VALID" in sql
    assert "assistant_message_digest" in sql
    assert "UPDATE public.runtime_chat_runs SET" not in sql


def test_migration_enforces_both_tenant_and_user_rls() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / (
        "supabase/migrations/20261025020000_43_runtime_chat_run_ledger.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app.current_tenant_id" in sql
    assert "app.current_user_id" in sql
    assert "UNIQUE (" in sql
    assert "tenant_id, user_id, conversation_id, transport_run_id" in sql
    assert "lease_token UUID" in sql


@pytest.mark.asyncio
async def test_missing_admission_indexes_fail_before_mutation(monkeypatch):
    transaction = Transaction([False])
    scoped_transaction(monkeypatch, transaction)
    with pytest.raises(RuntimeError, match="chat_run_admission_schema_unavailable"):
        await repository.SqlChatRunRepository().admit(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            transport_run_id="new-run", request_id="request",
            correlation_id="correlation", submission_id="original-user-turn",
        )
    assert len(transaction.sql) == 1
    assert "pg_catalog.pg_index" in transaction.sql[0]


@pytest.mark.parametrize(("value", "expected"), [
    (None, None), ("ordinary-turn", None), ("draft-v1-1", 1),
    ("draft-v1-9007199254740990", 9007199254740990),
])
def test_reserved_draft_identity_is_revision_bound(value, expected):
    assert repository.draft_revision_from_submission_id(value) == expected


@pytest.mark.parametrize("value", ["draft-v1-0", "draft-v1-01", "draft-v1-abc", "draft-v1-9007199254740991"])
def test_invalid_reserved_draft_identity_fails_closed(value):
    with pytest.raises(ValueError, match="invalid_draft_submission_identity"):
        repository.draft_revision_from_submission_id(value)



def test_unresolved_admission_migration_retains_orphan_fence():
    root = Path(__file__).resolve().parents[2]
    sql = (root / (
        "supabase/migrations/20261125030000_76_runtime_chat_unresolved_run.sql"
    )).read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX runtime_chat_runs_unresolved_idx" in sql
    assert "tenant_id, user_id, conversation_id" in sql
    assert "WHERE status IN ('running', 'cancelling', 'orphaned')" in sql
    assert "DROP INDEX public.runtime_chat_runs_single_active_idx" in sql
    assert "UPDATE public.runtime_chat_runs" not in sql



@pytest.mark.asyncio
async def test_attachment_bound_identity_matches_exact_selection(monkeypatch):
    from ai_karen_engine.services.database.repositories.conversation_repository import (
        draft_attachment_selection_digest,
    )
    import json

    selected = [{"source_id": THREAD, "revision": "a" * 64}]
    digest = draft_attachment_selection_digest(selected)
    submission = f"draft-v2-3-{digest}"
    assert repository.draft_revision_from_submission_id(submission) == 3
    assert repository.draft_attachment_digest_from_submission_id(submission) == digest
    transaction = Transaction([True, str(uuid.uuid4()), "same text"])
    scoped_transaction(monkeypatch, transaction)
    lease = await repository.SqlChatRunRepository().admit(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="attached", request_id="request", correlation_id="trace",
        submission_id=submission, submitted_text="same text",
        submitted_attachment_references=selected,
    )
    assert lease is not None and lease.submission_id == submission
    assert transaction.parameters[2]["submission_id"] == submission
    assert "revision = :revision" in transaction.sql[3]
    assert "attachment_references = CAST(:attachments AS jsonb)" in transaction.sql[3]
    assert transaction.parameters[3]["revision"] == 3
    assert json.loads(transaction.parameters[3]["attachments"]) == selected


@pytest.mark.asyncio
async def test_attachment_bound_identity_rejects_missing_or_substituted_selection(monkeypatch):
    from ai_karen_engine.services.database.repositories.conversation_repository import (
        draft_attachment_selection_digest,
    )

    selected = [{"source_id": THREAD, "revision": "a" * 64}]
    digest = draft_attachment_selection_digest(selected)
    transaction = Transaction([])
    scoped_transaction(monkeypatch, transaction)
    for submission, references in (
        (f"draft-v2-3-{digest}", []),
        (f"draft-v2-3-{digest}", [{**selected[0], "revision": "b" * 64}]),
        ("draft-v1-3", selected),
        ("ordinary-turn", selected),
    ):
        with pytest.raises(repository.DraftSubmissionConflict):
            await repository.SqlChatRunRepository().admit(
                tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
                transport_run_id="attached", request_id="request", correlation_id="trace",
                submission_id=submission, submitted_text="same text",
                submitted_attachment_references=references,
            )
    assert transaction.sql == []


def test_attachment_identity_digest_binds_order_and_validates_reserved_format():
    from ai_karen_engine.services.database.repositories.conversation_repository import (
        draft_attachment_selection_digest,
    )

    selected = [
        {"source_id": THREAD, "revision": "a" * 64},
        {"source_id": OWNER, "revision": "b" * 64},
    ]
    assert draft_attachment_selection_digest(selected) != draft_attachment_selection_digest(selected[::-1])
    for value in ("draft-v2-0-" + "a" * 64, "draft-v2-1-short", "draft-v2-1-" + "A" * 64):
        with pytest.raises(ValueError, match="invalid_draft_submission_identity"):
            repository.draft_revision_from_submission_id(value)



@pytest.mark.asyncio
@pytest.mark.parametrize("eligible,matched,advanced,expected", [
    (False, False, None, None),
    (True, False, None, None),
    (True, True, None, None),
    (True, True, 8, 8),
])
async def test_retry_advances_only_verified_retained_revision(
    monkeypatch, eligible, matched, advanced, expected,
):
    from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
        PostgresConversationRepository,
    )

    calls = []
    transaction = Transaction([str(uuid.uuid4()) if eligible else None, advanced, advanced])
    scoped_transaction(monkeypatch, transaction)

    async def match(session, **kwargs):
        assert session is transaction
        calls.append(kwargs)
        return matched

    monkeypatch.setattr(PostgresConversationRepository, "lock_matching_submission_draft", match)
    result = await repository.SqlChatRunRepository().advance_failed_draft_revision(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        submission_id="draft-v1-7", submitted_text="retained",
        attachment_references=[],
    )
    assert result == expected
    assert len(calls) == int(eligible)
    assert len(transaction.sql) == (3 if expected is not None else 2 if eligible and matched else 1)
    if expected is not None:
        assert "SET retry_prepared_revision = :prepared_revision" in transaction.sql[2]
        assert "retry_prepared_revision IS NULL" in transaction.sql[2]
        assert transaction.parameters[2]["prepared_revision"] == expected
    assert "FOR UPDATE" in transaction.sql[0]
    assert "status IN ('failed', 'cancelled')" in transaction.sql[0]
    assert "terminal_at IS NOT NULL" in transaction.sql[0]
    assert "assistant_message_digest IS NULL" in transaction.sql[0]
    assert "submission_id = :submission_id" in transaction.sql[0]
    if eligible and matched:
        assert "NOT EXISTS" in transaction.sql[1]
        assert "r.status IN ('running', 'cancelling', 'orphaned')" in transaction.sql[1]
        assert "d.revision = :revision" in transaction.sql[1]
        assert "SET revision = d.revision + 1" in transaction.sql[1]
        assert "draft_text =" not in transaction.sql[1]
        assert "attachment_references =" not in transaction.sql[1]
    for params in transaction.parameters:
        assert params["tenant"] == TENANT and params["owner"] == OWNER
        assert params["conversation"] == THREAD and params["revision"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,refs", [
    ("random-id", []),
    ("draft-v1-9007199254740990", []),
    ("draft-v1-7", [{"source_id": THREAD, "revision": "a" * 64}]),
    ("draft-v2-7-" + "a" * 64, []),
    ("draft-v2-7-" + "a" * 64, [{"source_id": THREAD, "revision": "a" * 64}]),
])
async def test_invalid_retry_identity_never_opens_transaction(monkeypatch, identity, refs):
    @asynccontextmanager
    async def unreachable(*args, **kwargs):
        raise AssertionError("invalid retry must not open a transaction")
        yield

    monkeypatch.setattr(repository, "async_transaction_scope", unreachable)
    with pytest.raises(ValueError):
        await repository.SqlChatRunRepository().advance_failed_draft_revision(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            submission_id=identity, submitted_text="retained", attachment_references=refs,
        )

@pytest.mark.asyncio
async def test_retry_marker_failure_cannot_commit_draft_advance(monkeypatch):
    from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
        PostgresConversationRepository,
    )
    from unittest.mock import AsyncMock

    transaction = Transaction([str(uuid.uuid4()), 8, None])
    scoped_transaction(monkeypatch, transaction)
    monkeypatch.setattr(PostgresConversationRepository, "lock_matching_submission_draft",
                        AsyncMock(return_value=True))
    with pytest.raises(RuntimeError, match="retry_receipt_not_recorded"):
        await repository.SqlChatRunRepository().advance_failed_draft_revision(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            submission_id="draft-v1-7", submitted_text="retained", attachment_references=[],
        )
    assert len(transaction.sql) == 3
