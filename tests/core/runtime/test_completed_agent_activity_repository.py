"""Executable repository contract tests for owner-bound observed agent-step replay."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.persistence.repositories import chat_run_repository as module


def _row(
    message_id: str, run_id: str, seq: int, event_type: str,
    conversation_id: str, *, request_id: str = "request-1",
) -> dict[str, object]:
    payload = (
        {"type": "RUN_FINISHED", "threadId": conversation_id, "runId": run_id}
        if event_type == "RUN_FINISHED"
        else {
            "type": "CUSTOM", "name": "karen.agent_step",
            "value": {
                "step_id": "step-1", "agent_id": "research",
                "status": "completed", "event_type": "agent_step_completed",
                "description": "Observed completion.",
            },
        }
    )
    return {
        "message_id": message_id, "request_id": request_id,
        "assistant_message_digest": "a" * 64,
        "transport_run_id": run_id, "event_seq": seq,
        "event_type": event_type, "event_payload": payload,
    }


async def _read(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]],
) -> dict[str, object]:
    tenant, owner, conversation = (str(uuid4()) for _ in range(3))

    class Session:
        async def execute(self, statement: object, params: object) -> object:
            sql = str(statement)
            assert "r.tenant_id = CAST(:tenant AS uuid)" in sql
            assert "r.user_id = CAST(:owner AS uuid)" in sql
            assert "r.conversation_id = CAST(:conversation AS uuid)" in sql
            assert "e.execution_id = r.execution_id" in sql
            assert "r.status = 'completed'" in sql
            assert params == {
                "tenant": tenant, "owner": owner, "conversation": conversation,
            }
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(all=lambda: rows),
            )

    @asynccontextmanager
    async def transaction(
        tenant_id: str, *, user_id: str,
    ):
        assert tenant_id == tenant
        assert user_id == owner
        yield Session()

    monkeypatch.setattr(module, "async_transaction_scope", transaction)
    return await module.SqlChatRunRepository().completed_agent_activity(
        tenant_id=tenant, user_id=owner, conversation_id=conversation,
    )


@pytest.mark.asyncio
async def test_no_rows_has_no_fabricated_agent_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _read(monkeypatch, []) == {}


@pytest.mark.asyncio
async def test_conflicting_runs_for_one_assistant_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = str(uuid4())
    rows = [
        _row("assistant-1", "run-1", 1, "CUSTOM", conversation),
        _row("assistant-1", "run-2", 1, "CUSTOM", conversation),
    ]
    with pytest.raises(RuntimeError, match="chat_activity_multiple_run_owners"):
        await _read(monkeypatch, rows)


@pytest.mark.asyncio
async def test_missing_observed_terminal_never_replays_partial_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row("assistant-1", "run-1", 1, "CUSTOM", str(uuid4()))]
    with pytest.raises(RuntimeError, match="chat_activity_journal_incomplete"):
        await _read(monkeypatch, rows)


@pytest.mark.asyncio
async def test_mismatched_terminal_run_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = str(uuid4())
    rows = [
        _row("assistant-1", "run-1", 1, "CUSTOM", conversation),
        _row("assistant-1", "run-1", 2, "RUN_FINISHED", conversation),
    ]
    rows[1]["event_payload"] = {
        "type": "RUN_FINISHED", "threadId": conversation, "runId": "foreign",
    }
    with pytest.raises(RuntimeError, match="chat_activity_terminal_mismatch"):
        await _read(monkeypatch, rows)
