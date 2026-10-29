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
