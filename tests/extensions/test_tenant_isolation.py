"""Tests for tenant isolation at the canonical execution authority."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    TenantScope,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService


class _Handler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Dict[str, Any]:
        self.calls += 1
        return {"ok": True, "tenant_id": context.tenant_id}


class _Registry:
    def __init__(self, manifest: ExtensionManifest, handler: _Handler) -> None:
        self.manifest = manifest
        self.handler = handler

    def get(self, plugin_id: str) -> ExtensionRegistration | None:
        if plugin_id != self.manifest.id:
            return None
        return ExtensionRegistration(
            manifest=self.manifest,
            state=ExtensionLifecycleState.ENABLED,
            instance=self.handler,
        )


def _manifest(
    tenant_scope: TenantScope,
    *,
    allowed_tenant_ids: list[str] | None = None,
) -> ExtensionManifest:
    return ExtensionManifest(
        id="tenant-test",
        name="tenant-test",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Tenant isolation fixture",
        entrypoint="handler:TenantTest",
        capabilities=[ExtensionCapability(id="execute")],
        tenant_scope=tenant_scope,
        allowed_tenant_ids=list(allowed_tenant_ids or []),
    )


def _context(tenant_id: str = "tenant-a") -> ExtensionExecutionContext:
    return ExtensionExecutionContext(
        request_id="request-1",
        correlation_id="correlation-1",
        user_id="user-1",
        tenant_id=tenant_id,
        session_id="session-1",
        policy_decision_id="policy-1",
    )


def _plan(tenant_id: str = "tenant-a") -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id=tenant_id,
        authorized_session_id="session-1",
        allowed_plugins=["tenant-test"],
    )


async def _execute(
    tenant_scope: TenantScope,
    *,
    allowed_tenant_ids: list[str] | None = None,
    tenant_id: str = "tenant-a",
) -> tuple[Any, _Handler]:
    handler = _Handler()
    service = ExtensionExecutionService(
        registry=_Registry(
            _manifest(
                tenant_scope,
                allowed_tenant_ids=allowed_tenant_ids,
            ),
            handler,
        )
    )
    result = await service.execute(
        ExtensionExecutionRequest(
            plugin_id="tenant-test",
            capability="execute",
            payload={},
            context=_context(tenant_id),
            authorized_plan=_plan(tenant_id),
        )
    )
    return result, handler


@pytest.mark.asyncio
async def test_global_tenant_scope_fails_closed_before_handler() -> None:
    result, handler = await _execute(TenantScope.GLOBAL)

    assert result.status == "failed"
    assert result.error_code == "tenant_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_multi_tenant_without_allowlist_fails_closed() -> None:
    result, handler = await _execute(TenantScope.MULTI)

    assert result.status == "failed"
    assert result.error_code == "tenant_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_multi_tenant_requires_exact_allowlist_membership() -> None:
    denied, denied_handler = await _execute(
        TenantScope.MULTI,
        allowed_tenant_ids=["tenant-b"],
    )
    allowed, allowed_handler = await _execute(
        TenantScope.MULTI,
        allowed_tenant_ids=["tenant-a", "tenant-b"],
    )

    assert denied.status == "failed"
    assert denied.error_code == "tenant_denied"
    assert denied_handler.calls == 0
    assert allowed.status == "success"
    assert allowed.payload == {"ok": True, "tenant_id": "tenant-a"}
    assert allowed_handler.calls == 1


@pytest.mark.asyncio
async def test_single_tenant_scope_accepts_authoritative_tenant_context() -> None:
    result, handler = await _execute(TenantScope.SINGLE)

    assert result.status == "success"
    assert result.payload == {"ok": True, "tenant_id": "tenant-a"}
    assert handler.calls == 1
