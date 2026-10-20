"""Consumer Medusa history only returns runs owned by authenticated user."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.agents.runtime import list_my_agent_runs


class ControlPlane:
    def __init__(self, rows):
        self.rows = rows
        self.tenants = []

    async def list_runs(self, *, tenant_id, include_terminal):
        self.tenants.append((tenant_id, include_terminal))
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
    assert plane.tenants == [(tenant, True)]


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
