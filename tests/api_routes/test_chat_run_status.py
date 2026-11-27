"""Read-only durable cancellation status is owned by the existing scoped ledger."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.persistence.repositories import chat_run_repository as repo
from ai_karen_engine.api_routes.chat import runtime as ingress

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "11111111-1111-1111-1111-111111111111"
THREAD = "4f6dc890-2644-4ff8-8f15-888888888888"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,requested,terminal,live,wanted,confirmed",
    [
        ("running", False, False, True, "running", False),
        ("cancelling", True, False, True, "cancelling", False),
        ("cancelling", True, False, False, "interrupted", False),
        ("cancelled", True, True, None, "cancelled", True),
        ("cancelled", False, True, None, "cancelled", False),
        ("completed", False, True, None, "completed", False),
        ("failed", False, True, None, "failed", False),
    ],
)
async def test_scoped_run_status_no_mutation(
    monkeypatch, state, requested, terminal, live, wanted, confirmed,
):
    queries = []
    class Session:
        async def execute(self, statement, params):
            queries.append((str(statement), params))
            row = {
                "status": state, "stop_requested": requested,
                "terminal_recorded": terminal, "lease_live": live,
                "completion_bound": True,
            }
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: row)
            )

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert tenant == TENANT
        assert user_id == OWNER
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    result = await repo.SqlChatRunRepository().read_status(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="run-exact",
    )
    assert result == {
        "status": wanted,
        "cancel_requested": requested,
        "cancellation_confirmed": confirmed,
    }
    assert len(queries) == 1
    sql, args = queries[0]
    assert sql.lstrip().startswith("SELECT")
    assert "UPDATE" not in sql and "INSERT" not in sql
    assert "tenant_id = CAST(:tenant AS uuid)" in sql
    assert "user_id = CAST(:owner AS uuid)" in sql
    assert "conversation_id = CAST(:conversation AS uuid)" in sql
    assert "transport_run_id = :run_id" in sql
    assert args == {
        "tenant": TENANT, "owner": OWNER,
        "conversation": THREAD, "run_id": "run-exact",
    }


@pytest.mark.asyncio
async def test_unknown_run_is_indistinguishable_without_mutating(monkeypatch):
    class Session:
        async def execute(self, statement, params):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: None)
            )

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert (tenant, user_id) == (TENANT, OWNER)
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    assert await repo.SqlChatRunRepository().read_status(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
        transport_run_id="missing",
    ) is None


@pytest.mark.asyncio
async def test_unverified_terminal_fails_closed(monkeypatch):
    class Session:
        async def execute(self, statement, params):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "status": "cancelled", "stop_requested": True,
                    "terminal_recorded": False, "lease_live": None,
                }
            ))

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    with pytest.raises(RuntimeError, match="unverified_chat_run_terminal"):
        await repo.SqlChatRunRepository().read_status(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            transport_run_id="run-exact",
        )


@pytest.mark.asyncio
async def test_readonly_endpoint_requires_enabled_durable_owner_and_no_leak(monkeypatch):
    class Coordinator:
        async def read_status(self, context, *, run_id):
            assert (context.tenant_id, context.user_id,
                    context.conversation_id, run_id) == (
                TENANT, OWNER, THREAD, "run-exact"
            )
            return {
                "status": "cancelling",
                "cancel_requested": True,
                "cancellation_confirmed": False,
            }

    monkeypatch.setattr(ingress, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        ),
    ))
    monkeypatch.setattr(ingress, "get_chat_run_coordinator", lambda: Coordinator())
    response = await ingress.get_ag_ui_chat_run_status(
        THREAD, "run-exact", user={"user_id": OWNER, "tenant_id": TENANT}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert b'"cancellation_confirmed":false' in response.body

    class Denied:
        async def read_status(self, context, *, run_id):
            raise PermissionError("private foreign user detail")

    monkeypatch.setattr(ingress, "get_chat_run_coordinator", lambda: Denied())
    with pytest.raises(HTTPException) as denied:
        await ingress.get_ag_ui_chat_run_status(
            THREAD, "run-exact", user={"user_id": OWNER, "tenant_id": TENANT}
        )
    assert denied.value.status_code == 404
    assert "private" not in denied.value.detail

    monkeypatch.setattr(ingress, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=False,
        ),
    ))
    with pytest.raises(HTTPException) as off:
        await ingress.get_ag_ui_chat_run_status(
            THREAD, "run-exact", user={"user_id": OWNER, "tenant_id": TENANT}
        )
    assert off.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "live", "expected"), [
    ("running", True, "running"), ("cancelling", True, "cancelling"),
    ("running", False, "interrupted"), ("orphaned", None, "orphaned"),
    ("completed", None, None), ("failed", None, None), ("cancelled", None, None),
])
async def test_recovery_observation_is_scoped_and_never_an_execution_receipt(
    monkeypatch, state, live, expected,
):
    queries = []

    class Session:
        async def execute(self, statement, params):
            queries.append((str(statement), params))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "transport_run_id": "original-run", "submission_id": "original-turn",
                    "status": state, "stop_requested": state == "cancelling",
                    "terminal_recorded": state not in {"running", "cancelling"},
                    "lease_live": live, "completion_bound": True,
                },
            ))

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert (tenant, user_id) == (TENANT, OWNER)
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    result = await repo.SqlChatRunRepository().read_recovery_run(
        tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
    )
    assert result == (None if expected is None else {
        "runId": "original-run", "submissionId": "original-turn", "status": expected,
    })
    assert len(queries) == 1
    sql, args = queries[0]
    assert sql.lstrip().startswith("SELECT")
    assert "ORDER BY CASE WHEN status IN ('running', 'cancelling', 'orphaned')" in sql
    assert "lease_token" not in sql
    assert args == {"tenant": TENANT, "owner": OWNER, "conversation": THREAD}


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("bound", [False, None])
async def test_completed_status_requires_exact_transcript_binding(monkeypatch, recovery, bound):
    class Session:
        async def execute(self, statement, params):
            sql = str(statement)
            assert "JOIN messages u" in sql
            assert "JOIN messages a" in sql
            assert "u.message_id::text = r.user_message_id::text" in sql
            assert "a.message_id::text = r.assistant_message_id::text" in sql
            assert "a.message_metadata::jsonb ->> 'request_id' = r.request_id" in sql
            assert "c.user_id = r.user_id" in sql
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "status": "completed", "stop_requested": False,
                    "terminal_recorded": True, "lease_live": None,
                    "completion_bound": bound,
                },
            ))

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert (tenant, user_id) == (TENANT, OWNER)
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    ledger = repo.SqlChatRunRepository()
    identity = dict(tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD)
    with pytest.raises(RuntimeError, match="unverified_chat_run_completion_binding"):
        if recovery:
            await ledger.read_recovery_run(**identity)
        else:
            await ledger.read_status(**identity, transport_run_id="run-exact")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,live,terminal,bound,expected,error",
    [
        ("running", True, False, True, "running", None),
        ("cancelling", True, False, True, "cancelling", None),
        ("running", False, False, True, "interrupted", None),
        ("orphaned", None, True, True, "orphaned", None),
        ("completed", None, True, True, "completed", None),
        ("failed", None, True, True, "failed", None),
        ("cancelled", None, True, True, "cancelled", None),
        ("completed", None, True, False, None, "unverified_chat_run_completion_binding"),
        ("failed", None, False, True, None, "unverified_chat_run_terminal"),
    ],
)
async def test_exact_submission_status_reuses_scoped_terminal_evidence(
    monkeypatch, state, live, terminal, bound, expected, error,
):
    queries = []

    class Session:
        async def execute(self, statement, params):
            queries.append((str(statement), params))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: {
                    "transport_run_id": "original-run",
                    "submission_id": "original-turn",
                    "status": state,
                    "stop_requested": state in {"cancelling", "cancelled"},
                    "terminal_recorded": terminal,
                    "lease_live": live,
                    "completion_bound": bound,
                },
            ))

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert (tenant, user_id) == (TENANT, OWNER)
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    ledger = repo.SqlChatRunRepository()
    args = dict(tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
                submission_id="original-turn")
    if error:
        with pytest.raises(RuntimeError, match=error):
            await ledger.read_submission_status(**args)
    else:
        result = await ledger.read_submission_status(**args)
        assert result == {
            "runId": "original-run",
            "submissionId": "original-turn",
            "status": expected,
            "cancel_requested": state in {"cancelling", "cancelled"},
            "cancellation_confirmed": state == "cancelled",
        }
    assert len(queries) == 1
    sql, params = queries[0]
    assert sql.lstrip().startswith("SELECT")
    assert "UPDATE" not in sql and "INSERT" not in sql
    assert "lease_token" not in sql
    assert "tenant_id = CAST(:tenant AS uuid)" in sql
    assert "user_id = CAST(:owner AS uuid)" in sql
    assert "conversation_id = CAST(:conversation AS uuid)" in sql
    assert "submission_id = :submission_id" in sql
    assert "ORDER BY" not in sql and "LIMIT 1" not in sql
    assert "JOIN messages u" in sql and "JOIN messages a" in sql
    assert params == {
        "tenant": TENANT, "owner": OWNER, "conversation": THREAD,
        "submission_id": "original-turn",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    None,
    {"transport_run_id": "foreign run", "submission_id": "original-turn"},
    {"transport_run_id": "other-run", "submission_id": "other-turn"},
])
async def test_exact_submission_absence_or_mismatch_never_falls_back(monkeypatch, row):
    class Session:
        async def execute(self, statement, params):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                one_or_none=lambda: row,
            ))

    @asynccontextmanager
    async def scope(tenant, *, user_id=None):
        assert (tenant, user_id) == (TENANT, OWNER)
        yield Session()

    monkeypatch.setattr(repo, "async_transaction_scope", scope)
    ledger = repo.SqlChatRunRepository()
    args = dict(tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
                submission_id="original-turn")
    if row is None:
        assert await ledger.read_submission_status(**args) is None
    else:
        with pytest.raises(RuntimeError, match="unverified_chat_run_recovery_identity"):
            await ledger.read_submission_status(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize("submission_id", ["", "bad id", "x" * 101, None])
async def test_invalid_exact_submission_is_rejected_before_database(monkeypatch, submission_id):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid selector entered the database")

    monkeypatch.setattr(repo, "async_transaction_scope", unexpected)
    with pytest.raises(ValueError, match="invalid_chat_submission_id"):
        await repo.SqlChatRunRepository().read_submission_status(
            tenant_id=TENANT, user_id=OWNER, conversation_id=THREAD,
            submission_id=submission_id,
        )
