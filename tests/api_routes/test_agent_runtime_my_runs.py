"""Consumer Medusa history only returns runs owned by authenticated user."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.agents.runtime import list_my_agent_runs, get_my_agent_run, get_my_run_context


class ControlPlane:
    def __init__(self, rows):
        self.rows = rows
        self.tenants = []

    async def list_runs(self, *, tenant_id, include_terminal, user_id):
        self.tenants.append((tenant_id, include_terminal, user_id))
        return {"runs": self.rows, "generated_at": "2026-10-20T00:00:00Z"}


@pytest.mark.asyncio
async def test_history_excludes_other_user_and_tenant_unknown_rows():
    tenant, owner, stranger = str(uuid4()), str(uuid4()), str(uuid4())
    plane = ControlPlane([
        {"run_id": "mine", "user_id": owner},
        {"run_id": "theirs", "user_id": stranger},
        {"run_id": "unattributed"},
    ])
    result = await list_my_agent_runs(
        current_user=SimpleNamespace(tenant_id=tenant, user_id=owner, is_active=True),
        control_plane=plane,
    )
    assert result["runs"] == [{"run_id": "mine", "user_id": owner}]
    assert result["total"] == 1
    assert plane.tenants == [(tenant, True, owner)]


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant,owner,active", [
    ("default", str(uuid4()), True),
    ("", str(uuid4()), True),
    (str(uuid4()), "", True),
    (str(uuid4()), str(uuid4()), False),
])
async def test_invalid_identity_cannot_read_history(tenant, owner, active):
    plane = ControlPlane([])
    with pytest.raises(HTTPException) as error:
        await list_my_agent_runs(
            current_user=SimpleNamespace(tenant_id=tenant, user_id=owner, is_active=active),
            control_plane=plane,
        )
    assert error.value.status_code == 403
    assert plane.tenants == []


class DetailControlPlane:
    def __init__(self, record):
        self.record = record
        self.requests = []

    async def get_run(self, *, run_id, tenant_id):
        self.requests.append((run_id, tenant_id))
        return self.record


@pytest.mark.asyncio
async def test_selected_run_detail_requires_record_owner():
    tenant, owner = str(uuid4()), str(uuid4())
    plane = DetailControlPlane({"run_id": "run-1", "user_id": str(uuid4())})
    principal = SimpleNamespace(tenant_id=tenant, user_id=owner, is_active=True)
    with pytest.raises(HTTPException) as error:
        await get_my_agent_run("run-1", current_user=principal, control_plane=plane)
    assert error.value.status_code == 404
    assert plane.requests == [("run-1", tenant)]
    plane.record = {"run_id": "run-1", "user_id": owner, "status": "running"}
    result = await get_my_agent_run("run-1", current_user=principal, control_plane=plane)
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_selected_run_detail_requires_verified_identity():
    plane = DetailControlPlane({"run_id": "run-1", "user_id": "someone"})
    with pytest.raises(HTTPException) as error:
        await get_my_agent_run(
            "run-1",
            current_user=SimpleNamespace(tenant_id="default", user_id=str(uuid4()), is_active=True),
            control_plane=plane,
        )
    assert error.value.status_code == 403
    assert plane.requests == []


@pytest.mark.asyncio
async def test_context_projection_only_exposes_owner_verified_fields():
    tenant, owner = str(uuid4()), str(uuid4())
    plane = DetailControlPlane({
        "run_id": "owned", "user_id": owner, "status": "completed",
        "started_at": "2026-10-20T12:00:00Z",
        "secret": "not-for-ui", "tenant_id": tenant,
    })
    principal = SimpleNamespace(tenant_id=tenant, user_id=owner, is_active=True)
    context = await get_my_run_context("owned", current_user=principal, control_plane=plane)
    assert context == {
        "resource_type": "medusa_run", "run_id": "owned", "status": "completed",
        "started_at": "2026-10-20T12:00:00Z", "completed_at": None, "error_type": None,
    }
    plane.record["user_id"] = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await get_my_run_context("owned", current_user=principal, control_plane=plane)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_workspace_reference_reuses_owner_checked_projection(monkeypatch):
    from ai_karen_engine.api_routes.chat import runtime as chat_runtime
    tenant, owner = str(uuid4()), str(uuid4())
    plane = DetailControlPlane({"run_id": "run-1", "user_id": owner, "status": "running"})
    from ai_karen_engine.api_routes.agents import runtime as agent_runtime
    monkeypatch.setattr(agent_runtime, "get_run_control_plane", lambda: plane)
    principal = {"tenant_id": tenant, "user_id": owner, "is_active": True}
    monkeypatch.setattr(chat_runtime, "UserData", SimpleNamespace(ensure=lambda user: SimpleNamespace(**user)))
    reference = await chat_runtime._verified_workspace_run_reference(
        run_id="run-1", user=principal,
    )
    assert reference["resource_type"] == "medusa_run"
    assert reference["run_id"] == "run-1"
    plane.record["user_id"] = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await chat_runtime._verified_workspace_run_reference(
            run_id="run-1", user=principal,
        )
    assert error.value.status_code == 404


def test_shared_chat_workspace_contract_rejects_non_bounded_refs():
    from pydantic import ValidationError
    from ai_karen_engine.api_routes.chat.runtime import ChatStreamRequest
    assert ChatStreamRequest(message="Explain", workspace_run_id="owned-run").workspace_run_id == "owned-run"
    with pytest.raises(ValidationError):
        ChatStreamRequest(message="Explain", workspace_run_id="x" * 129)


@pytest.mark.asyncio
async def test_chat_context_reference_rejects_unauthorized_run(monkeypatch):
    from ai_karen_engine.api_routes.chat import runtime as chat_runtime
    from ai_karen_engine.api_routes.agents import runtime as agent_runtime
    tenant, owner = str(uuid4()), str(uuid4())
    plane = DetailControlPlane({"run_id": "run-2", "user_id": str(uuid4()), "status": "running"})
    monkeypatch.setattr(agent_runtime, "get_run_control_plane", lambda: plane)
    monkeypatch.setattr(chat_runtime, "UserData", SimpleNamespace(ensure=lambda user: SimpleNamespace(**user)))
    with pytest.raises(HTTPException) as error:
        await chat_runtime._verified_workspace_run_reference(
            run_id="run-2", user={"tenant_id": tenant, "user_id": owner, "is_active": True},
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_workspace_reference_rejects_cross_tenant_and_inactive_identity(monkeypatch):
    from ai_karen_engine.api_routes.chat import runtime as chat_runtime
    from ai_karen_engine.api_routes.agents import runtime as agent_runtime
    owner = str(uuid4())
    original_tenant = str(uuid4())
    other_tenant = str(uuid4())
    plane = DetailControlPlane({"run_id": "restricted-run", "user_id": owner, "status": "running"})
    monkeypatch.setattr(agent_runtime, "get_run_control_plane", lambda: plane)
    monkeypatch.setattr(chat_runtime, "UserData", SimpleNamespace(ensure=lambda user: SimpleNamespace(**user)))
    for principal in (
        {"tenant_id": "default", "user_id": owner, "is_active": True},
        {"tenant_id": original_tenant, "user_id": owner, "is_active": False},
    ):
        with pytest.raises(HTTPException) as error:
            await chat_runtime._verified_workspace_run_reference(
                run_id="restricted-run", user=principal,
            )
        assert error.value.status_code == 403
    assert plane.requests == []
    # A run in another tenant must be rejected by the canonical lookup.
    from ai_karen_engine.agent_medusa.execution.run_manager import RunTenantMismatchError
    async def mismatch(*, run_id, tenant_id):
        raise RunTenantMismatchError("tenant mismatch")
    plane.get_run = mismatch
    with pytest.raises(HTTPException) as error:
        await chat_runtime._verified_workspace_run_reference(
            run_id="restricted-run",
            user={"tenant_id": other_tenant, "user_id": owner, "is_active": True},
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_agent_discovery_redacts_internal_metadata_and_denies_invalid_scopes():
    from ai_karen_engine.api_routes.agents.runtime import get_agent_catalog
    class Catalog:
        def __init__(self):
            self.called = 0
        async def list_agent_catalog(self):
            self.called += 1
            return [SimpleNamespace(
                agent_id="research", name="Research", lifecycle_state="active",
                healthy=True, implementation_id="internal-implementation",
                prompt_contract_id="private-prompt", missing_dependencies=["secret"],
                capabilities=["internal-only"]
            )]
    catalog = Catalog()
    for tenant, owner, active in [
        ("default", "owner", True),
        ("dev-tenant", "owner", True),
        ("", "owner", True),
        ("tenant-a", "", True),
        ("tenant-a", "owner", False),
    ]:
        with pytest.raises(HTTPException) as error:
            await get_agent_catalog(
                current_user={"tenant_id": tenant, "user_id": owner, "is_active": active},
                service=catalog,
            )
        assert error.value.status_code == 403
    assert catalog.called == 0
    result = await get_agent_catalog(
        current_user={"tenant_id": "tenant-a", "user_id": "owner", "is_active": True},
        service=catalog,
    )
    assert result["eligibility_verified"] is False
    assert result["agents"] == [{
        "agent_id": "research", "name": "Research",
        "lifecycle_state": "active", "healthy": True,
        "eligibility": "runtime_decided_per_request",
    }]
    assert "private-prompt" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, expected", [("owned", 200), ("missing", 404), ("wrong", 404), ("unavailable", 503), ("inactive", 403), ("default", 403), ("dev-tenant", 403)])
async def test_transition_route_uses_authenticated_owner_and_honest_errors(mode, expected):
    from unittest.mock import AsyncMock
    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import DurableRunLedgerUnavailable
    from ai_karen_engine.api_routes.agents.runtime import get_my_run_transitions

    tenant, owner = str(uuid4()), str(uuid4())
    receipt = {"run_id": "run-1", "transitions": [], "truncated": False,
               "response_source": "postgres_durable_run_ledger"}
    reader = AsyncMock(return_value=receipt)
    if mode == "missing":
        reader.return_value = None
    elif mode == "wrong":
        reader.return_value = {**receipt, "run_id": "other"}
    elif mode == "unavailable":
        reader.side_effect = DurableRunLedgerUnavailable("internal error")
    principal = SimpleNamespace(
        tenant_id=mode if mode in {"default", "dev-tenant"} else tenant,
        user_id=owner, is_active=mode != "inactive",
    )
    plane = SimpleNamespace(read_run_transitions=reader)
    if expected == 200:
        assert await get_my_run_transitions("run-1", current_user=principal, control_plane=plane) == receipt
    else:
        with pytest.raises(HTTPException) as error:
            await get_my_run_transitions("run-1", current_user=principal, control_plane=plane)
        assert error.value.status_code == expected
        assert "internal error" not in error.value.detail
    if expected == 403:
        reader.assert_not_awaited()
    else:
        reader.assert_awaited_once_with(run_id="run-1", tenant_id=tenant, user_id=owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("recorded", 200), ("empty", 200), ("missing", 404), ("wrong", 404),
    ("outage", 503), ("ledger_outage", 503), ("inactive", 403),
    ("unverified", 403), ("default", 403), ("dev-tenant", 403), ("long_id", 404),
])
async def test_participation_route_preserves_owner_scope_and_availability(mode, expected):
    from unittest.mock import AsyncMock
    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import DurableRunLedgerUnavailable
    from ai_karen_engine.api_routes.agents.runtime import get_my_run_participation
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    tenant, owner = str(uuid4()), str(uuid4())
    run_id = "x" * 129 if mode == "long_id" else "run-1"
    evidence = {
        "run_id": run_id,
        "evidence_status": "empty" if mode == "empty" else "recorded",
        "receipts": [] if mode == "empty" else [{"phase": "interrupted"}],
        "truncated": False,
        "response_source": "postgres_outcome_records",
    }
    reader = AsyncMock(return_value=evidence)
    if mode == "missing":
        reader.return_value = None
    elif mode == "wrong":
        reader.return_value = {**evidence, "run_id": "other"}
    elif mode == "outage":
        reader.side_effect = OutcomeStoreError("private database diagnostic")
    elif mode == "ledger_outage":
        reader.side_effect = DurableRunLedgerUnavailable("private database diagnostic")
    principal = SimpleNamespace(
        tenant_id=mode if mode in {"default", "dev-tenant"} else tenant,
        user_id=owner, is_active=mode != "inactive", is_verified=mode != "unverified",
    )
    plane = SimpleNamespace(read_run_participation=reader)
    if expected == 200:
        assert await get_my_run_participation(run_id, current_user=principal, control_plane=plane) == evidence
    else:
        with pytest.raises(HTTPException) as error:
            await get_my_run_participation(run_id, current_user=principal, control_plane=plane)
        assert error.value.status_code == expected
        assert "private database diagnostic" not in error.value.detail
    if expected == 403 or mode == "long_id":
        reader.assert_not_awaited()
    else:
        reader.assert_awaited_once_with(run_id=run_id, tenant_id=tenant, user_id=owner)
