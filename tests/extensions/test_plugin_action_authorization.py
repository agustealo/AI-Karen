"""Regression tests for plugin authorization scope and action-gate enforcement."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.services.plugin_execution import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PluginExecutionEngine,
    ResourceLimits,
    SecurityPolicy,
)
from ai_karen_engine.services.plugin_service import PluginService


class _ServiceRegistry:
    def get_plugin(self, plugin_name: str) -> dict[str, Any] | None:
        if plugin_name != "echo":
            return None
        return {
            "manifest": SimpleNamespace(
                name="echo",
                version="1.0.0",
                config_schema=None,
            ),
            "status": "registered",
        }


class _CapturingEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.request: ExecutionRequest | None = None
        self.plan: AuthorizedExecutionPlan | None = None

    async def execute_plugin(
        self,
        request: ExecutionRequest,
        plan: AuthorizedExecutionPlan,
    ) -> ExecutionResult:
        self.calls += 1
        self.request = request
        self.plan = plan
        return ExecutionResult(
            request_id=request.request_id,
            plugin_name=request.plugin_name,
            status=ExecutionStatus.COMPLETED,
            user_id=request.user_id or "",
            tenant_id=request.tenant_id or "",
            correlation_id=request.correlation_id or "",
            policy_decision_id=request.policy_decision_id or "",
        )


class _EngineRegistry:
    def __init__(self) -> None:
        self.calls = 0

    def get_plugin(self, plugin_name: str) -> dict[str, Any] | None:
        self.calls += 1
        if plugin_name != "echo":
            return None
        return {
            "manifest": SimpleNamespace(
                name="echo",
                version="1.0.0",
                permissions={},
                resources=None,
                capabilities=None,
            ),
            "status": "registered",
        }


def _plan(
    *,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    session_id: str | None = "session-1",
    plugin_id: str = "echo",
) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id=user_id,
        authorized_tenant_id=tenant_id,
        authorized_session_id=session_id,
        allowed_plugins=[plugin_id],
    )


def _service() -> tuple[PluginService, _CapturingEngine]:
    service = PluginService()
    engine = _CapturingEngine()
    service.registry = _ServiceRegistry()  # type: ignore[assignment]
    service.execution_engine = engine  # type: ignore[assignment]
    service.initialized = True
    return service, engine


@pytest.mark.asyncio
async def test_runtime_policy_emits_exact_plugin_tool_and_principal_scope():
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            correlation_id="corr-1",
            plugin_id="echo",
            action="plugin_execution",
            execution_topology={
                "plugin_candidates": ["echo", "search-plugin"],
                "tool_requirements": ["web-search", "file-reader"],
            },
        )
    )

    assert decision.allowed is True
    plan = decision.to_authorized_plan()
    assert plan.allowed_plugins == ["echo", "search-plugin"]
    assert plan.allowed_tools == ["web-search", "file-reader"]
    assert plan.authorized_user_id == "user-1"
    assert plan.authorized_tenant_id == "tenant-1"
    assert plan.authorized_session_id == "session-1"
    assert plan.audit_context["correlation_id"] == "corr-1"
    assert plan.matches_execution_scope(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        policy_decision_id=decision.decision_id,
    )
    assert await ActionExecutionGate.authorize(plan, "echo") is True
    assert await ActionExecutionGate.authorize(plan, "search-plugin") is True
    assert await ActionExecutionGate.authorize(plan, "web-search") is True


@pytest.mark.asyncio
async def test_plugin_service_rejects_bare_policy_decision_id():
    service, engine = _service()

    result = await service.execute_plugin(
        "echo",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "authorized_plan_required"
    assert engine.calls == 0


@pytest.mark.asyncio
async def test_plugin_service_rejects_cross_tenant_plan_replay():
    service, engine = _service()

    result = await service.execute_plugin(
        "echo",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        correlation_id="corr-1",
        authorized_plan=_plan(tenant_id="tenant-other"),
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "authorized_scope_mismatch"
    assert engine.calls == 0


@pytest.mark.asyncio
async def test_plugin_service_propagates_authorized_scope_to_engine():
    service, engine = _service()
    plan = _plan()

    result = await service.execute_plugin(
        "echo",
        parameters={"message": "hello"},
        execution_mode=ExecutionMode.DIRECT,
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conversation-1",
        correlation_id="corr-1",
        authorized_plan=plan,
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert engine.calls == 1
    assert engine.plan is plan
    assert engine.request is not None
    assert engine.request.user_id == "user-1"
    assert engine.request.tenant_id == "tenant-1"
    assert engine.request.session_id == "session-1"
    assert engine.request.conversation_id == "conversation-1"
    assert engine.request.correlation_id == "corr-1"
    assert engine.request.policy_decision_id == "policy-1"


@pytest.mark.asyncio
async def test_compatibility_engine_awaits_action_gate_before_handler(monkeypatch):
    registry = _EngineRegistry()
    engine = PluginExecutionEngine(registry=registry)  # type: ignore[arg-type]
    plan = _plan()
    request = ExecutionRequest(
        plugin_name="echo",
        parameters={"message": "hello"},
        execution_mode=ExecutionMode.DIRECT,
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conversation-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
    )

    async def deny(
        authorized_plan: AuthorizedExecutionPlan,
        action: str,
    ) -> bool:
        assert authorized_plan is plan
        assert action == "echo"
        return False

    monkeypatch.setattr(ActionExecutionGate, "authorize", staticmethod(deny))

    result = await engine.execute_plugin(request, plan=plan)
    await engine.cleanup()

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "policy_denied"
    assert "ActionExecutionGate" in (result.error or "")
    assert registry.calls == 1


@pytest.mark.asyncio
async def test_compatibility_engine_rejects_missing_plan_before_registry_lookup():
    registry = _EngineRegistry()
    engine = PluginExecutionEngine(registry=registry)  # type: ignore[arg-type]
    request = ExecutionRequest(
        plugin_name="echo",
        user_id="user-1",
        tenant_id="tenant-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
    )

    result = await engine.execute_plugin(request, plan=None)
    await engine.cleanup()

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "policy_denied"
    assert registry.calls == 0


@pytest.mark.asyncio
async def test_sandbox_uses_dict_backed_manifest_entrypoint(monkeypatch):
    engine = PluginExecutionEngine(registry=_EngineRegistry())  # type: ignore[arg-type]
    metadata = {
        "manifest": SimpleNamespace(entrypoint="handler:MainExtension"),
    }
    calls: list[str] = []

    async def execute_direct(*args, **kwargs):
        calls.append("direct")
        return {"ok": True}

    async def execute_process(*args, **kwargs):
        calls.append("process")
        return {"ok": False}

    monkeypatch.setattr(engine, "_execute_direct", execute_direct)
    monkeypatch.setattr(engine, "_execute_in_process", execute_process)

    result = await engine._execute_in_sandbox(
        metadata,
        {},
        ResourceLimits(),
        SecurityPolicy(),
        30,
        "request-1",
    )
    await engine.cleanup()

    assert result == {"ok": True}
    assert calls == ["direct"]
