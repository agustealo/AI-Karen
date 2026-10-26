"""CK-07E0: observed-only event cursor fencing, replay and SSE contract."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk, ChatStreamEventType,
)
from ai_karen_engine.persistence.repositories import chat_run_repository as repository

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"
RUN_ID = "run_cursor"


def lease() -> repository.ChatRunLease:
    return repository.ChatRunLease(
        execution_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id=RUN_ID,
        request_id="request-cursor", correlation_id="trace-cursor",
    )


class Transaction:
    def __init__(self, *, status="running", cursor=0, stored=None):
        self.status = status
        self.cursor = cursor
        self.stored = stored or []
        self.queries = []
        self.params = []
        self.committed = False

    async def execute(self, statement, params):
        sql = str(statement)
        self.queries.append(sql)
        self.params.append(params)
        if "FOR UPDATE" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "status": self.status,
                    "lease_token": params.get("token"),
                    "lease_expires_at": "future",
                    "cancel_requested_at": None,
                    "terminal_at": "terminal" if self.status in {
                        "completed", "cancelled", "failed", "orphaned"
                    } else None,
                    "assistant_message_id": str(uuid.uuid4()),
                    "assistant_message_digest": "a" * 64,
                },
            ))
        if "FOR SHARE" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "execution_id": params.get("execution", "33333333-3333-4333-8333-333333333333"),
                    "status": self.status,
                    "lease_expires_at": "future",
                    "terminal_at": None,
                },
            ))
        if "COALESCE(MAX(event_seq)" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one=lambda: {"last_seq": self.cursor, "bytes": 0},
            ))
        if "SELECT event_seq, event_payload" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                all=lambda: self.stored,
            ))
        if "INSERT INTO public.runtime_chat_run_events" in sql:
            self.cursor = params["seq"]
            return SimpleNamespace(scalar_one_or_none=lambda: self.cursor)
        if "SELECT event_type FROM public.runtime_chat_run_events" in sql:
            terminals = [
                entry["event_payload"]["type"]
                for entry in self.stored
                if entry["event_payload"]["type"] in {"RUN_FINISHED", "RUN_ERROR"}
            ]
            return SimpleNamespace(
                scalar_one_or_none=lambda: terminals[0] if terminals else None,
            )
        if "SELECT 1" in sql:
            return SimpleNamespace(scalar_one_or_none=lambda: (
                1 if self.status == "running" else None
            ))
        raise AssertionError("Unexpected SQL: " + sql)

    @asynccontextmanager
    async def scope(self, tenant, *, user_id):
        assert tenant == TENANT and user_id == OWNER
        yield self
        self.committed = True


def scoped(monkeypatch, tx: Transaction):
    monkeypatch.setattr(repository, "async_transaction_scope", tx.scope)


@pytest.mark.asyncio
async def test_serialized_append_preserves_owner_fence_and_monotonic_cursor(monkeypatch):
    tx = Transaction()
    scoped(monkeypatch, tx)
    owned = lease()
    repo = repository.SqlChatRunRepository()
    assert await repo.append_projected_event(
        owned, event={"type": "RUN_STARTED", "threadId": THREAD, "runId": RUN_ID},
    ) == 1
    assert await repo.append_projected_event(
        owned, event={"type": "TEXT_MESSAGE_CONTENT", "messageId": "assistant-test",
                      "delta": "observed, not synthesized"},
    ) == 2
    assert tx.committed
    assert all("FOR UPDATE" in tx.queries[i] for i in (0, 4))
    insert_params = [
        args for sql, args in zip(tx.queries, tx.params)
        if "INSERT INTO public.runtime_chat_run_events" in sql
    ]
    assert [p["seq"] for p in insert_params] == [1, 2]
    assert all(p["execution"] == owned.execution_id for p in insert_params)
    assert all(p["tenant"] == TENANT and p["owner"] == OWNER for p in insert_params)


@pytest.mark.asyncio
async def test_stop_or_expired_fence_refuses_further_projected_tokens(monkeypatch):
    tx = Transaction(status="cancelling")
    scoped(monkeypatch, tx)
    with pytest.raises(ValueError, match="not_active"):
        await repository.SqlChatRunRepository().append_projected_event(
            lease(), event={"type": "TEXT_MESSAGE_CONTENT",
                            "messageId": "a", "delta": "should not be seen"},
        )
    assert not any("INSERT INTO public.runtime_chat_run_events" in s for s in tx.queries)


@pytest.mark.asyncio
async def test_atomic_completed_status_accepts_only_verifiable_final_envelope(monkeypatch):
    tx = Transaction(status="completed")
    scoped(monkeypatch, tx)
    owned = lease()
    repo = repository.SqlChatRunRepository()
    assert await repo.append_projected_event(
        owned, event={"type": "TEXT_MESSAGE_END", "messageId": "assistant-run_cursor"},
    ) == 1
    assert await repo.append_projected_event(
        owned, event={"type": "CUSTOM", "name": "karen.execution_receipt.v1",
                      "value": {"actual_model": "observed"}},
    ) == 2
    assert await repo.append_projected_event(
        owned, event={"type": "RUN_FINISHED", "threadId": THREAD, "runId": RUN_ID},
    ) == 3
    with pytest.raises(ValueError, match="not_active"):
        await repo.append_projected_event(
            owned, event={"type": "TEXT_MESSAGE_CONTENT",
                          "messageId": "a", "delta": "late token"},
        )


@pytest.mark.asyncio
async def test_untrusted_event_types_and_unbounded_fields_fail_before_sql(monkeypatch):
    tx = Transaction()
    scoped(monkeypatch, tx)
    cases = [
        {"type": "RUN_FINISHED", "threadId": "foreign", "runId": RUN_ID},
        {"type": "CUSTOM", "name": "karen.admin_action",
         "value": {"tools": ["execute"]}},
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "a" * 33000},
        {"type": "TOOL_CALL_START", "toolCallId": "forged", "token": float("nan")},
    ]
    for case in cases:
        with pytest.raises(ValueError):
            await repository.SqlChatRunRepository().append_projected_event(
                lease(), event=case,
            )
    assert tx.queries == []


@pytest.mark.asyncio
async def test_paged_event_read_marks_expired_lease_interrupted_without_success(monkeypatch):
    tx = Transaction(status="running", stored=[
        {"event_seq": 8, "event_payload": {"type": "TEXT_MESSAGE_CONTENT",
                                         "messageId": "a", "delta": "observed"}},
        {"event_seq": 9, "event_payload": {"type": "TEXT_MESSAGE_END",
                                         "messageId": "a"}},
        {"event_seq": 10, "event_payload": {"type": "TEXT_MESSAGE_CONTENT",
                                          "messageId": "a", "delta": "more observed"}},
    ])
    # Our fake clock returns no active lease when the live run is expired.
    original_execute = tx.execute

    async def expired_execute(statement, params):
        if "lease_expires_at > clock_timestamp()" in str(statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return await original_execute(statement, params)

    tx.execute = expired_execute
    scoped(monkeypatch, tx)
    result = await repository.SqlChatRunRepository().read_projected_events(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id=RUN_ID, after=7, limit=2,
    )
    assert result["runStatus"] == "interrupted"
    assert result["terminalConfirmed"] is False
    assert result["journalTerminalObserved"] is False
    assert result["continuationAvailable"] is False
    assert result["nextCursor"] == 9
    assert result["hasMore"] is True
    assert [p["seq"] for p in result["events"]] == [8, 9]
    assert all(p["event"]["type"] != "RESUME_EXECUTION" for p in result["events"])


@pytest.mark.asyncio
async def test_cursor_rejects_contradictory_terminal_journal_and_running_ledger(
    monkeypatch,
):
    tx = Transaction(status="running", stored=[
        {"event_seq": 1, "event_payload": {
            "type": "RUN_FINISHED", "threadId": THREAD, "runId": RUN_ID,
        }},
    ])
    scoped(monkeypatch, tx)
    with pytest.raises(RuntimeError, match="terminal_state_mismatch"):
        await repository.SqlChatRunRepository().read_projected_events(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            transport_run_id=RUN_ID,
        )


@pytest.mark.asyncio
async def test_scoped_cursor_missing_run_has_no_leakage(monkeypatch):
    tx = Transaction()

    async def missing(statement, params):
        if "FOR SHARE" in str(statement):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: None,
            ))
        raise AssertionError("No foreign run's events should be read")

    tx.execute = missing
    scoped(monkeypatch, tx)
    result = await repository.SqlChatRunRepository().read_projected_events(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="unknown", after=0, limit=50,
    )
    assert result is None


@pytest.mark.asyncio
async def test_sse_journal_failure_before_start_never_launches_model(monkeypatch):
    started = []
    failed = []
    recorded = []

    class Journal:
        async def append_observed_event(self, lease, event):
            recorded.append(event["type"])
            raise RuntimeError("postgres unavailable")

        async def fail_unstarted_event_journal(self, lease):
            failed.append(lease.execution_id)
            return True

    class Runtime:
        async def execute_stream(self, request):
            started.append(request)
            yield ChatStreamChunk(type=ChatStreamEventType.CONTENT, content="should not run")

    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
            enable_ag_ui_event_journal=True,
        )),
    )
    monkeypatch.setattr(ingress, "get_chat_run_coordinator", lambda: Journal())
    monkeypatch.setattr(ingress, "get_chat_runtime", lambda: Runtime())
    owned = lease()
    request = ingress._stream_execution_request(
        request=ingress.ChatStreamRequest(
            message="hi", session_id=THREAD, conversation_id=THREAD,
        ),
        user={"user_id": OWNER, "tenant_id": TENANT},
        session_id=THREAD, correlation_id=owned.correlation_id,
        response_id=owned.request_id,
    )
    stream = "".join([
        piece async for piece in ingress._ag_ui_sse(
            request, thread_id=THREAD, run_id=RUN_ID, run_lease=owned,
        )
    ])
    assert started == []
    assert failed == [owned.execution_id]
    assert recorded == ["RUN_STARTED", "RUN_ERROR"]
    assert "RUN_ERROR" in stream
    assert "RUN_FINISHED" not in stream


@pytest.mark.asyncio
async def test_sse_cursor_is_emitted_only_after_successful_append(monkeypatch):
    records = []
    class Journal:
        async def append_observed_event(self, lease, event):
            records.append(event)
            return len(records)

        async def stream(self, chunks, *, lease):
            async for chunk in chunks:
                yield chunk

    class Runtime:
        async def execute_stream(self, request):
            yield ChatStreamChunk(type=ChatStreamEventType.CONTENT, content="token")
            yield ChatStreamChunk(type=ChatStreamEventType.COMPLETE, metadata={
                "transcript_persistence_status": "persisted",
                "actual_provider": "local", "actual_model": "observed",
                "response_source": "model",
            })

    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
            enable_ag_ui_event_journal=True,
        )),
    )
    monkeypatch.setattr(ingress, "get_chat_run_coordinator", lambda: Journal())
    monkeypatch.setattr(ingress, "get_chat_runtime", lambda: Runtime())
    owned = lease()
    request = ingress._stream_execution_request(
        request=ingress.ChatStreamRequest(
            message="hi", session_id=THREAD, conversation_id=THREAD,
        ),
        user={"user_id": OWNER, "tenant_id": TENANT},
        session_id=THREAD, correlation_id=owned.correlation_id,
        response_id=owned.request_id,
    )
    stream = "".join([
        piece async for piece in ingress._ag_ui_sse(
            request, thread_id=THREAD, run_id=RUN_ID, run_lease=owned,
        )
    ])
    assert [r["type"] for r in records] == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END", "CUSTOM", "RUN_FINISHED",
    ]
    assert [line for line in stream.splitlines() if line.startswith("id: ")] == [
        f"id: {index}" for index in range(1, len(records) + 1)
    ]


def test_cursor_schema_is_principal_scoped_and_bounded():
    from pathlib import Path
    path = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20261025050000_46_runtime_chat_event_journal.sql"
    )
    sql = path.read_text(encoding="utf-8")
    assert "FOREIGN KEY (execution_id, tenant_id, user_id, conversation_id)" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.current_user_id', true)" in sql
    assert "octet_length(event_payload::text) <= 32768" in sql
    assert "event_seq <= 2048" in sql
    assert "CREATE TABLE public.runtime_chat_run_events" in sql


@pytest.mark.asyncio
async def test_cursor_ingress_is_authenticated_owner_scoped_and_never_calls_model(
    monkeypatch,
):
    received = []
    class ReadOnlyCoordinator:
        async def read_observed_events(self, ctx, *, run_id, after, limit):
            received.append((
                ctx.tenant_id, ctx.user_id, ctx.conversation_id,
                run_id, after, limit,
            ))
            return {
                "threadId": THREAD, "runId": run_id, "events": [],
                "nextCursor": after, "hasMore": False,
                "runStatus": "interrupted", "terminalConfirmed": False,
                "continuationAvailable": False,
                "responseSource": "observed_event_journal",
            }
    class ForbiddenRuntime:
        def execute_stream(self, request):
            raise AssertionError("Cursor read must not execute inference")
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
            enable_ag_ui_event_journal=True,
        )),
    )
    monkeypatch.setattr(
        ingress, "get_chat_run_coordinator", lambda: ReadOnlyCoordinator(),
    )
    monkeypatch.setattr(
        ingress, "get_chat_runtime", lambda: ForbiddenRuntime(),
    )
    response = await ingress.get_ag_ui_run_observed_events(
        thread_id=THREAD, run_id=RUN_ID, after=7, limit=25,
        user={"user_id": OWNER, "tenant_id": TENANT},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = json.loads(response.body)
    assert body["runStatus"] == "interrupted"
    assert body["terminalConfirmed"] is False
    assert received == [(TENANT, OWNER, THREAD, RUN_ID, 7, 25)]


@pytest.mark.asyncio
async def test_event_read_refuses_flag_off_foreign_run_and_unbounded_cursors(
    monkeypatch,
):
    calls = []
    class NoOwnRun:
        async def read_observed_events(self, *args, **kwargs):
            calls.append(kwargs)
            return None
    monkeypatch.setattr(
        ingress, "get_chat_run_coordinator", lambda: NoOwnRun(),
    )
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
            enable_ag_ui_event_journal=False,
        )),
    )
    user = {"user_id": OWNER, "tenant_id": TENANT}
    with pytest.raises(HTTPException) as blocked:
        await ingress.get_ag_ui_run_observed_events(
            thread_id=THREAD, run_id=RUN_ID, user=user,
        )
    assert blocked.value.status_code == 404
    assert calls == []
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
            enable_ag_ui_event_journal=True,
        )),
    )
    for parameters in [
        {"thread_id": "not-uuid", "run_id": RUN_ID},
        {"thread_id": THREAD, "run_id": "wrong run ID"},
        {"thread_id": THREAD, "run_id": RUN_ID, "after": -1},
        {"thread_id": THREAD, "run_id": RUN_ID, "after": 2049},
        {"thread_id": THREAD, "run_id": RUN_ID, "limit": 101},
        {"thread_id": THREAD, "run_id": RUN_ID, "limit": 0},
    ]:
        with pytest.raises(HTTPException) as denied:
            await ingress.get_ag_ui_run_observed_events(
                **parameters, user=user,
            )
        assert denied.value.status_code == 422
    assert calls == []
    with pytest.raises(HTTPException) as absent:
        await ingress.get_ag_ui_run_observed_events(
            thread_id=THREAD, run_id=RUN_ID, user=user,
        )
    assert absent.value.status_code == 404
    assert len(calls) == 1
