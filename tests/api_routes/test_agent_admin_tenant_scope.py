"""Fail-closed tenant boundary for RBAC-governed Medusa run administration."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.admin.agents import (
    _tenant_id,
    cancel_run,
    get_run,
    list_runs,
)


class _RunControlPlane:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def list_runs(self, *, tenant_id: str, include_terminal: bool):
        self.calls.append(("list", tenant_id))
        return {"runs": [], "total": 0}

    async def get_run(self, *, run_id: str, tenant_id: str):
        self.calls.append(("get", tenant_id))
        return {"run_id": run_id, "tenant_id": tenant_id}

    async def cancel_run(
        self, *, run_id: str, tenant_id: str, actor_user_id: str | None,
        session_id: str | None,
    ):
        self.calls.append(("cancel", tenant_id))
        return {"run_id": run_id, "status": "cancelling"}


@pytest.mark.parametrize("tenant_id", [None, "", " ", "default", "DEFAULT", "dev-tenant", " DEV-TENANT "])
def test_admin_run_tenant_scope_rejects_placeholders(tenant_id: str | None) -> None:
    with pytest.raises(HTTPException) as exc:
        _tenant_id({"tenant_id": tenant_id})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("tenant_id", ["tenant-one", " tenant-one "])
def test_admin_run_tenant_scope_normalizes_valid_identity(tenant_id: str) -> None:
    assert _tenant_id({"tenant_id": tenant_id}) == "tenant-one"


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", [None, "", "default", "dev-tenant", "  "])
async def test_admin_run_routes_reject_invalid_tenant_before_control_plane(tenant_id: str | None) -> None:
    control = _RunControlPlane()
    principal = {"tenant_id": tenant_id, "user_id": "administrator", "session_id": "session"}
    for operation in (
        lambda: list_runs(include_terminal=True, current_user=principal, control_plane=control),
        lambda: get_run(run_id="run-1", current_user=principal, control_plane=control),
        lambda: cancel_run(run_id="run-1", current_user=principal, control_plane=control),
    ):
        with pytest.raises(HTTPException) as exc:
            await operation()
        assert exc.value.status_code == 403
    assert control.calls == []


@pytest.mark.asyncio
async def test_admin_run_routes_delegate_with_normalized_verified_tenant() -> None:
    control = _RunControlPlane()
    principal = {"tenant_id": " tenant-one ", "user_id": "administrator", "session_id": "session"}
    assert (await list_runs(include_terminal=True, current_user=principal, control_plane=control))["total"] == 0
    assert (await get_run(run_id="run-1", current_user=principal, control_plane=control))["run_id"] == "run-1"
    assert (await cancel_run(run_id="run-1", current_user=principal, control_plane=control))["status"] == "cancelling"
    assert control.calls == [("list", "tenant-one"), ("get", "tenant-one"), ("cancel", "tenant-one")]
