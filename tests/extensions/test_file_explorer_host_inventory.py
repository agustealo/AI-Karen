"""Host-only File Explorer inventory admission, paging and execution proof."""
from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
from ai_karen_engine.extensions.file_explorer_inventory import (
    FileExplorerInventoryHost,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
SHA = "a" * 64


def _item(number: int) -> dict:
    return {
        "source_id": f"44444444-4444-4444-8444-{number:012d}",
        "parent_id": None,
        "kind": "file",
        "name": f"artifact-{number}.txt",
        "revision": SHA,
        "size_bytes": 12,
        "sha256": SHA,
    }


class OwnerSource:
    def __init__(self, *, pages=None, error=None):
        self.pages = pages or [{"items": [_item(1)], "has_more": False, "next_cursor": None}]
        self.error = error
        self.calls = []

    async def list_owner_sources_page(self, *, tenant_id, user_id, limit, cursor):
        self.calls.append((tenant_id, user_id, limit, cursor))
        if self.error is not None:
            raise self.error
        index = 0 if cursor is None else 1
        return self.pages[index]


class Kernel:
    def __init__(self, *, status="enabled", valid=True, response_status="success"):
        self.status = status
        self.valid = valid
        self.response_status = response_status
        self.calls = []

    def get_record(self, plugin_id):
        return {
            "status": self.status,
            "dependencies_resolved": self.valid,
        }

    async def execute(self, request):
        self.calls.append(request)
        items = request.context.resource_scope["file_explorer_entries"]
        return SimpleNamespace(
            status=self.response_status,
            payload={"operation": "list", "items": items},
        )


def _context(tenant=TENANT, owner=OWNER, **changes):
    return replace(ExtensionExecutionContext(
        request_id="request-1",
        correlation_id="corr-1",
        user_id=owner,
        tenant_id=tenant,
        session_id="session-1",
        policy_decision_id="policy-1",
        allowed_capabilities=["file-explorer"],
        resource_scope={},
    ), **changes)


def _plan(tenant=TENANT, owner=OWNER, **changes):
    return replace(AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id=owner,
        authorized_tenant_id=tenant,
        authorized_session_id="session-1",
        allowed_plugins=["file-explorer"],
        allowed_capabilities=["file-explorer"],
    ), **changes)


@pytest.mark.asyncio
async def test_owner_page_calls_canonical_kernel_and_preserves_metadata():
    source, kernel = OwnerSource(), Kernel()
    result = await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
        context=_context(), plan=_plan(), limit=25
    )
    assert source.calls == [(TENANT, OWNER, 25, None)]
    assert result["items"] == [_item(1)]
    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert result["correlation_id"] == "corr-1"
    assert len(kernel.calls) == 1
    request = kernel.calls[0]
    assert request.plugin_id == "file-explorer"
    assert request.authorized_plan.policy_decision_id == "policy-1"
    assert request.context.resource_scope["file_explorer_grant"] == "host_verified"
    assert request.payload == {"operation": "list"}
    assert "file_explorer_entries" not in _context().resource_scope


@pytest.mark.asyncio
async def test_scope_and_plan_gates_precede_repository_access():
    attempts = [
        (_context(owner=OTHER), _plan()),
        (_context(tenant=OTHER), _plan()),
        (_context(), _plan(owner=OTHER)),
        (_context(), _plan(tenant=OTHER)),
        (_context(), _plan(policy_decision_id="different")),
        (_context(), _plan(allowed_plugins=[])),
        (_context(allowed_capabilities=[]), _plan()),
        (_context(policy_decision_id=None), _plan()),
        (_context(resource_scope={"file_explorer_grant": "host_verified"}), _plan()),
        (_context(resource_scope={"file_explorer_entries": [_item(1)]}), _plan()),
        (_context(tenant_id="default"), _plan()),
        (_context(user_id="default"), _plan()),
    ]
    for ctx, plan in attempts:
        source, kernel = OwnerSource(), Kernel()
        with pytest.raises(PermissionError):
            await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
                context=ctx, plan=plan
            )
        assert source.calls == []
        assert kernel.calls == []


@pytest.mark.asyncio
async def test_disabled_invalid_plugin_and_bad_limits_never_query_source():
    for status, valid in [("disabled", True), ("enabled", False), ("discovered", True)]:
        source, kernel = OwnerSource(), Kernel(status=status, valid=valid)
        with pytest.raises(PermissionError):
            await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
                context=_context(), plan=_plan()
            )
        assert source.calls == []
    for limit in [0, True, 201, 1.0, -1]:
        source, kernel = OwnerSource(), Kernel()
        with pytest.raises(ValueError):
            await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
                context=_context(), plan=_plan(), limit=limit
            )
        assert source.calls == []


@pytest.mark.asyncio
async def test_cursor_is_passed_without_becoming_a_permission():
    source = OwnerSource(pages=[
        {"items": [_item(1)], "has_more": True, "next_cursor": "scoped-cursor"},
        {"items": [_item(2)], "has_more": False, "next_cursor": None},
    ])
    kernel = Kernel()
    host = FileExplorerInventoryHost(kernel=kernel, source=source)
    one = await host.list_owner_page(context=_context(), plan=_plan(), limit=1)
    two = await host.list_owner_page(
        context=replace(_context(), request_id="request-2"),
        plan=_plan(), limit=1, cursor=one["next_cursor"]
    )
    assert one["has_more"] is True
    assert two["items"] == [_item(2)]
    assert source.calls == [
        (TENANT, OWNER, 1, None),
        (TENANT, OWNER, 1, "scoped-cursor"),
    ]
    assert all("file_explorer_grant" not in request.payload for request in kernel.calls)


@pytest.mark.asyncio
async def test_unavailable_source_is_not_a_successful_empty_inventory():
    source = OwnerSource(error=RuntimeError("file_explorer_artifact_list_unavailable"))
    kernel = Kernel()
    with pytest.raises(RuntimeError, match="file_explorer_artifact_list_unavailable"):
        await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
            context=_context(), plan=_plan()
        )
    assert kernel.calls == []


@pytest.mark.asyncio
async def test_kernel_denial_and_corrupt_page_fail_closed():
    source = OwnerSource()
    kernel = Kernel(response_status="error")
    with pytest.raises(PermissionError, match="file_explorer_kernel_denied"):
        await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
            context=_context(), plan=_plan()
        )
    for page in [
        {"items": [_item(1)], "has_more": True, "next_cursor": None},
        {"items": [_item(1)], "has_more": True, "next_cursor": "x" * 769},
        {"items": [_item(1)], "has_more": True, "next_cursor": 123},
        {"items": [_item(1)], "has_more": True, "next_cursor": ""},
        {"items": [], "has_more": True, "next_cursor": "x"},
        {"items": [_item(1)], "has_more": False, "next_cursor": "x"},
        {"items": [_item(1), _item(2)], "has_more": False, "next_cursor": None},
    ]:
        source = OwnerSource(pages=[page])
        kernel = Kernel()
        with pytest.raises(RuntimeError, match="file_explorer_source_page_invalid"):
            await FileExplorerInventoryHost(kernel=kernel, source=source).list_owner_page(
                context=_context(), plan=_plan(), limit=1
            )
        assert kernel.calls == []
