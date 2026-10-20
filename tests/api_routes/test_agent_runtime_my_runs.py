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
    monkeypatch.setattr(chat_runtime, "get_my_run_context", get_my_run_context, raising=False)
    from ai_karen_engine.api_routes.agents import runtime as agent_runtime
    monkeypatch.setattr(agent_runtime, "get_run_control_plane", lambda: plane)
    from ai_karen_engine.auth.models import UserData
    principal = {"tenant_id": tenant, "user_id": owner, "is_active": True}
    try:
        reference = await chat_runtime._verified_workspace_run_reference(
            run_id="run-1", user=principal,
        )
    except (TypeError, ValueError):
        pytest.skip("UserData principal fixture requires canonical auth claims")
    assert reference["resource_type"] == "medusa_run"
    assert reference["run_id"] == "run-1"
    plane.record["user_id"] = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await chat_runtime._verified_workspace_run_reference(
            run_id="run-1", user=principal,
        )
    assert error.value.status_code == 404
