"""Tests for canonical extension executor authorization."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.extensions.contracts import (
    CapabilityInvocationRequest,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionHealth,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    ResolvedCapability,
    ResponseSource,
    TrustTier,
    ExecutionIsolationMode,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService


class FakeHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        self.calls += 1
        return {"echo": payload.get("message", "")}


class FakeRegistry:
    def __init__(
        self,
        *,
        enabled: bool = True,
        handler: FakeHandler | None = None,
        manifest: ExtensionManifest | None = None,
    ) -> None:
        self.handler = handler or FakeHandler()
        self.enabled = enabled
        self.manifest = manifest or _manifest()

    def get(self, plugin_id: str) -> ExtensionRegistration | None:
        if plugin_id != "echo":
            return None
        return ExtensionRegistration(
            manifest=self.manifest,
            state=(
                ExtensionLifecycleState.ENABLED
                if self.enabled
                else ExtensionLifecycleState.DISABLED
            ),
            instance=self.handler,
        )


class FakeLifecycle:
    def get_health(self, plugin_id: str) -> ExtensionHealth:
        return ExtensionHealth.HEALTHY


class FakeCapabilityResolver:
    async def resolve(
        self,
        request: CapabilityInvocationRequest,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> ResolvedCapability:
        assert authorized_plan.policy_decision_id == "policy-1"
        return ResolvedCapability(
            capability=ExtensionCapability(id="echo", version="1.0.0"),
            extension_id="echo",
            extension_version="1.0.0",
            extension_trust_tier=TrustTier.UNTRUSTED,
            extension_isolation_mode=ExecutionIsolationMode.IN_PROCESS,
            policy_decision_id=authorized_plan.policy_decision_id,
        )


def _manifest(
    *, required_permissions: list[str] | None = None
) -> ExtensionManifest:
    permissions = list(required_permissions or [])
    return ExtensionManifest(
        id="echo",
        name="echo",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Test",
        entrypoint="handler:EchoExtension",
        capabilities=[
            ExtensionCapability(
                id="echo",
                version="1.0.0",
                required_permissions=permissions,
            )
        ],
        intents=["echo"],
        required_permissions=permissions,
        optional_permissions=[],
        required_roles=[],
        tenant_scope="single",
        allowed_tenant_ids=[],
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        output_schema={
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "required": ["echo"],
        },
        side_effect_level="none",
        timeout_ms=5000,
        max_retries=1,
        enabled_by_default=False,
        trusted_ui=False,
        dependencies=[],
    )


def _context(
    *,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    session_id: str | None = "session-1",
) -> ExtensionExecutionContext:
    return ExtensionExecutionContext(
        request_id="req-1",
        correlation_id="corr-1",
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        policy_decision_id="policy-1",
        allowed_capabilities=[],
    )


def _plan(
    *,
    allowed_plugins: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    session_id: str | None = "session-1",
) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id=user_id,
        authorized_tenant_id=tenant_id,
        authorized_session_id=session_id,
        allowed_plugins=list(allowed_plugins if allowed_plugins is not None else ["echo"]),
        allowed_capabilities=list(allowed_capabilities or []),
    )


def _request(
    *,
    plan: AuthorizedExecutionPlan | None,
    context: ExtensionExecutionContext | None = None,
) -> ExtensionExecutionRequest:
    return ExtensionExecutionRequest(
        plugin_id="echo",
        capability="echo",
        payload={"message": "hello"},
        context=context or _context(),
        authorized_plan=plan,
    )


@pytest.mark.asyncio
async def test_execute_success_with_matching_authorized_plan():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "success"
    assert result.source == ResponseSource.PLUGIN
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_missing_authorized_plan_denied_before_handler():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=None))

    assert result.status == "failed"
    assert result.error_code == "authorized_plan_required"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_empty_allowed_plugins_is_fail_closed():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan(allowed_plugins=[])))

    assert result.status == "failed"
    assert result.error_code == "not_authorized"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_required_permission_is_fail_closed_when_plan_grant_is_empty():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(required_permissions=["custom_access"]),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(allowed_capabilities=[]))
    )

    assert result.status == "failed"
    assert result.error_code == "permission_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_required_permission_executes_only_when_plan_grants_it():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(required_permissions=["custom_access"]),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(allowed_capabilities=["custom_access"]))
    )

    assert result.status == "success"
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_wrong_tenant_plan_is_denied():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(tenant_id="tenant-other"))
    )

    assert result.status == "failed"
    assert result.error_code == "authorized_scope_mismatch"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_action_execution_gate_denial_prevents_handler(monkeypatch):
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    async def deny(plan: AuthorizedExecutionPlan, action: str) -> bool:
        assert action == "echo"
        return False

    monkeypatch.setattr(ActionExecutionGate, "authorize", staticmethod(deny))

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "failed"
    assert result.error_code == "action_gate_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_capability_first_path_uses_single_execute_signature():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
        capability_resolver=FakeCapabilityResolver(),
    )
    request = CapabilityInvocationRequest(
        capability_id="echo",
        payload={"message": "hello"},
        context=_context(),
        authorized_plan=_plan(),
    )

    result = await service.execute_capability(request, request.authorized_plan)

    assert result.status == "success"
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_disabled_plugin_denied():
    service = ExtensionExecutionService(
        registry=FakeRegistry(enabled=False),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "failed"
    assert result.error_code == "disabled"


@pytest.mark.asyncio
async def test_not_found():
    service = ExtensionExecutionService(
        registry=type("FakeRegistry", (), {"get": lambda self, pid: None})()
    )
    request = ExtensionExecutionRequest(
        plugin_id="missing",
        capability="echo",
        payload={},
        context=_context(),
        authorized_plan=AuthorizedExecutionPlan(
            execution_id="exec-1",
            policy_decision_id="policy-1",
            authorized_user_id="user-1",
            authorized_tenant_id="tenant-1",
            authorized_session_id="session-1",
            allowed_plugins=["missing"],
        ),
    )

    result = await service.execute(request)

    assert result.status == "failed"
    assert result.error_code == "not_found"
