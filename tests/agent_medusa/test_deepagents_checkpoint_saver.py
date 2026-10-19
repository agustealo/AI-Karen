"""Fail-closed, tenant-scoped LangGraph checkpoint saver contract tests.

The fake session below exercises SQL parameters and serde round-trips only.
PostgreSQL RLS/migration and cross-process resume require the separate live
database proof before the checkpoint feature flag can be enabled.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.agent_medusa.execution.deepagents_checkpoints import (
    DeepAgentsCheckpointScopeError,
    ScopedPostgresDeepAgentsSaver,
    trusted_thread_id,
)


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"


class FakeResult:
    def __init__(self, rows=None, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.statements = []
        self.checkpoint = None
        self.writes = []
        self.commits = 0

    async def execute(self, statement, params):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, dict(params)))
        if "set_config('app.current_tenant_id'" in sql:
            return FakeResult()
        if "INSERT INTO agent_medusa_deepagents_checkpoints" in sql:
            self.checkpoint = dict(params)
            return FakeResult()
        if "INSERT INTO agent_medusa_deepagents_checkpoint_writes" in sql:
            self.writes.append(dict(params))
            return FakeResult()
        if "SELECT checkpoint_id, parent_checkpoint_id" in sql:
            if self.checkpoint is None:
                return FakeResult()
            if params["checkpoint_id"] not in (None, self.checkpoint["checkpoint_id"]):
                return FakeResult()
            return FakeResult([self.checkpoint])
        if "SELECT task_id, task_path, write_index" in sql:
            return FakeResult(self.writes)
        if "SELECT checkpoint_id FROM" in sql:
            return FakeResult([{
                "checkpoint_id": self.checkpoint["checkpoint_id"]
            }] if self.checkpoint else [])
        if "DELETE FROM agent_medusa_deepagents_checkpoints" in sql:
            self.checkpoint = None
            self.writes = []
            return FakeResult()
        raise AssertionError("Unexpected checkpoint SQL: " + sql[:180])

    async def commit(self):
        self.commits += 1


class FakePostgres:
    def __init__(self):
        self.session = FakeSession()

    @asynccontextmanager
    async def get_async_session(self):
        yield self.session


def make_saver(postgres=None):
    return ScopedPostgresDeepAgentsSaver(
        tenant_id=TENANT, user_id=USER, session_id="session-1",
        policy_decision_id="policy-1", run_id="run-1",
        thread_id="safe-thread",
        postgres=postgres or FakePostgres(),
    )


def config(checkpoint_id=None, thread_id="safe-thread"):
    options = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id:
        options["checkpoint_id"] = checkpoint_id
    return {"configurable": options}


@pytest.mark.asyncio
async def test_checkpoint_and_writes_roundtrip_with_scoped_postgres_queries():
    db = FakePostgres()
    saver = make_saver(db)
    checkpoint = {
        "id": "checkpoint-1", "v": 2,
        "channel_values": {"messages": ["hello"]},
        "channel_versions": {"messages": "version-1"},
        "versions_seen": {},
        "pending_sends": [],
    }
    parent = await saver.aput(
        config(), checkpoint, {"source": "input", "step": -1}, {},
    )
    assert parent["configurable"]["checkpoint_id"] == "checkpoint-1"
    await saver.aput_writes(
        parent, [("messages", {"result": "ok"})],
        task_id="task-1", task_path="path/1",
    )
    observed = await saver.aget_tuple(config())
    assert observed.checkpoint["id"] == "checkpoint-1"
    assert observed.checkpoint["channel_values"]["messages"] == ["hello"]
    assert observed.metadata["source"] == "input"
    assert observed.pending_writes == [
        ("task-1", "messages", {"result": "ok"})
    ]
    assert observed.parent_config is None
    assert db.session.commits == 2
    scoped = [args for sql, args in db.session.statements
              if "set_config('app.current_tenant_id'" in sql]
    assert scoped and all(item["tenant_id"] == TENANT for item in scoped)
    inserts = [(sql, args) for sql, args in db.session.statements
               if "INSERT INTO agent_medusa_deepagents_checkpoints" in sql]
    assert len(inserts) == 1
    assert inserts[0][1]["user_id"] == USER
    assert inserts[0][1]["policy_decision_id"] == "policy-1"
    assert inserts[0][1]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_checkpoint_thread_cannot_be_changed_by_client_graph_config():
    db = FakePostgres()
    saver = make_saver(db)
    with pytest.raises(DeepAgentsCheckpointScopeError, match="does not belong"):
        await saver.aget_tuple(config(thread_id="another-tenant-thread"))
    with pytest.raises(DeepAgentsCheckpointScopeError, match="another thread"):
        await saver.adelete_thread("another-tenant-thread")
    assert db.session.statements == []


@pytest.mark.asyncio
async def test_checkpoint_history_reads_and_tenant_scoped_delete():
    db = FakePostgres()
    saver = make_saver(db)
    await saver.aput(config(), {"id": "checkpoint-3"}, {"source": "input"}, {})
    found = [row async for row in saver.alist(config())]
    assert [row.checkpoint["id"] for row in found] == ["checkpoint-3"]
    await saver.adelete_thread("safe-thread")
    assert await saver.aget_tuple(config()) is None
    assert any(
        "DELETE FROM agent_medusa_deepagents_checkpoints" in sql
        for sql, args in db.session.statements
    )


@pytest.mark.asyncio
async def test_checkpoint_serializer_refuses_pickle_and_untrusted_types():
    saver = make_saver()
    with pytest.raises(ValueError, match="Unsafe"):
        saver._deserialize("pickle", b"not-a-pickle")
    with pytest.raises(ValueError, match="Unsafe"):
        saver._deserialize("unregistered", b"anything")


def test_authorized_execution_scope_and_opaque_run_thread_identity():
    class Plan:
        def matches_execution_scope(self, **kwargs):
            return (
                kwargs["tenant_id"] == TENANT
                and kwargs["user_id"] == USER
                and kwargs["policy_decision_id"] == "policy-1"
            )

    execution = SimpleNamespace(
        authorized_plan=Plan(), tenant_id=TENANT, user_id=USER,
        session_id="session-1", policy_decision_id="policy-1",
        trajectory_id="run-1", step_id="researcher-1",
    )
    thread = trusted_thread_id(execution)
    assert len(thread) == 64
    assert TENANT not in thread
    saver = ScopedPostgresDeepAgentsSaver.for_authorized_execution(
        execution, thread_id=thread, postgres=FakePostgres(),
    )
    assert saver._thread_id == thread
    execution.tenant_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    with pytest.raises(DeepAgentsCheckpointScopeError, match="RuntimePolicy"):
        ScopedPostgresDeepAgentsSaver.for_authorized_execution(
            execution, thread_id=thread, postgres=FakePostgres(),
        )


def test_forward_migration_has_tenant_rls_and_canonical_ledger_relation():
    text = Path(
        "supabase/migrations/"
        "20261019010000_36_medusa_deepagents_checkpoints.sql"
    ).read_text()
    assert "REFERENCES agent_medusa_runs (run_id, tenant_id)" in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "current_setting('app.current_tenant_id', true)" in text
    assert "ON DELETE CASCADE" in text
    assert "CREATE TABLE agent_medusa_deepagents_checkpoint_writes" in text
