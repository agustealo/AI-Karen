"""CK-07C0: one canonical SQL transaction owns transcript + run finality."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from ai_karen_engine.services.database.repositories.conversation_repository import (
    Message,
)
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from ai_karen_engine.persistence.repositories.chat_run_repository import ChatRunLease

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"


def lease() -> ChatRunLease:
    return ChatRunLease(
        execution_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="run-atomic", request_id="req-atomic",
        correlation_id="trace-atomic",
    )


def messages(run: ChatRunLease) -> tuple[Message, Message]:
    base = {
        "authorized_user_id": run.user_id,
        "request_id": run.request_id,
        "correlation_id": run.correlation_id,
    }
    return (
        Message(id=str(uuid.uuid4()), conversation_id=THREAD,
                tenant_id=TENANT, role="user", content="original input",
                metadata={**base, "transcript_actor": "user"}),
        Message(id=str(uuid.uuid4()), conversation_id=THREAD,
                tenant_id=TENANT, role="assistant", content="saved answer",
                metadata={**base, "transcript_actor": "assistant"}),
    )


class FakeTransaction:
    def __init__(self, *, allow_admission: bool = True,
                 allow_finish: bool = True):
        self.allow_admission = allow_admission
        self.allow_finish = allow_finish
        self.calls: list[tuple[str, dict]] = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rolled_back = True
        else:
            self.committed = True
        return False

    def begin(self):
        return self

    async def execute(self, sql, args):
        statement = str(sql)
        self.calls.append((statement, args))
        if "FROM public.runtime_chat_runs" in statement and "FOR UPDATE" in statement:
            return SimpleNamespace(
                scalar_one_or_none=lambda: "owned" if self.allow_admission else None,
            )
        if "SELECT conversation_id FROM conversations" in statement:
            return SimpleNamespace(fetchone=lambda: ("found",))
        if "INSERT INTO messages" in statement:
            return SimpleNamespace(rowcount=1)
        if "UPDATE public.runtime_chat_runs" in statement:
            return SimpleNamespace(
                scalar_one_or_none=lambda: "terminal" if self.allow_finish else None,
            )
        return SimpleNamespace()


def make_repo(tx: FakeTransaction) -> PostgresConversationRepository:
    async def factory():
        return tx
    return PostgresConversationRepository(factory)


@pytest.mark.asyncio
async def test_both_messages_and_run_complete_inside_one_transaction() -> None:
    current = lease()
    tx = FakeTransaction()
    result = await make_repo(tx).add_completed_turn(
        *messages(current), run_lease=current,
    )
    assert result.success and result.data == 2
    assert tx.committed and not tx.rolled_back
    joined = "\n".join(sql for sql, _ in tx.calls)
    assert "FOR UPDATE" in joined
    assert joined.index("FROM public.runtime_chat_runs") < joined.index(
        "SELECT conversation_id FROM conversations"
    ) < joined.index("INSERT INTO messages")
    assert joined.rindex("UPDATE public.runtime_chat_runs") > joined.index(
        "INSERT INTO messages"
    )
    assert "status = 'completed'" in joined
    assert "cancel_requested_at IS NULL" in joined
    assert "app.current_tenant_id" in joined
    assert "app.current_user_id" in joined
    assert all(
        item["tenant"] == current.tenant_id
        for sql, item in tx.calls
        if "FROM public.runtime_chat_runs" in sql
           or "UPDATE public.runtime_chat_runs" in sql
    )


@pytest.mark.asyncio
async def test_cancel_winner_cannot_insert_any_transcript_messages() -> None:
    current = lease()
    tx = FakeTransaction(allow_admission=False)
    result = await make_repo(tx).add_completed_turn(
        *messages(current), run_lease=current,
    )
    assert not result.success
    assert result.error == "chat_run_commit_not_authorized"
    assert tx.rolled_back
    assert not any("INSERT INTO messages" in sql for sql, _ in tx.calls)


@pytest.mark.asyncio
async def test_terminal_write_failure_rolls_back_both_messages() -> None:
    current = lease()
    tx = FakeTransaction(allow_finish=False)
    result = await make_repo(tx).add_completed_turn(
        *messages(current), run_lease=current,
    )
    assert not result.success
    assert result.error == "chat_run_commit_not_authorized"
    assert tx.rolled_back and not tx.committed
    assert sum("INSERT INTO messages" in sql for sql, _ in tx.calls) == 2


@pytest.mark.asyncio
async def test_foreign_run_lease_never_reaches_message_insert() -> None:
    current = lease()
    tx = FakeTransaction()
    user, assistant = messages(current)
    assistant.metadata["request_id"] = "foreign-request"
    result = await make_repo(tx).add_completed_turn(
        user, assistant, run_lease=current,
    )
    assert not result.success
    assert result.error == "chat_run_transcript_scope_mismatch"
    assert tx.rolled_back
    assert not any("INSERT INTO messages" in sql for sql, _ in tx.calls)
