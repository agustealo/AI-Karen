"""Regression tests for plugin authorization scope and canonical delegation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.extensions.contracts import (
    DataClassification,
    ExtensionExecutionResult,
    ResponseSource,
    ResultTrust,
    TrustTier,
)
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services.plugin_service import ExecutionStatus, PluginService


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


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        name="echo",
        version="1.0.0",
        display_name="Echo",
        description="Authorization fixture",
        author="Kari",
        license="MIT",
        category="test",
        entrypoint="handler:MainExtension",
    )


class _Kernel:
    def __init__(self) -> None:
        self.calls = 0
        self.request = None
        self.record = {
            "manifest": _manifest(),
            "path": Path("/tmp/echo"),
            "status": "enabled",
            "checksum": "fixture",
            "error_message": None,
            "dependencies_resolved": True,
            "compatibility_checked": True,
        }

    def get_record(self, plugin_id: str):
        return self.record if plugin_id == "echo" else None

    def list_records(self):
        return [self.record]

    async def execute(self, request):
        self.calls += 1
        self.request = request
        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id=request.plugin_id,
            plugin_version="1.0.0",
            capability=request.capability,
            source=ResponseSource.PLUGIN,
            payload={"ok": True},
            latency_ms=1.0,
            status="success",
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=TrustTier.FIRST_PARTY,
            result_trust=ResultTrust.VERIFIED,
            data_classification=DataClassification.PUBLIC,
        )


def _service() -> tuple[PluginService, _Kernel]:
    service = PluginService()
    kernel = _Kernel()
    service.kernel = kernel  # type: ignore[assignment]
    service.initialized = True
    return service, kernel


def test_chat_runtime_authorized_plan_binds_request_principal():
    runtime = object.__new__(ChatRuntime)
    request = SimpleNamespace(
        context=SimpleNamespace(
            request_id="request-1",
            correlation_id="corr-1",
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
        ),
        max_tokens=1024,
    )
    decision = SimpleNamespace(
        time_budget_ms=30000,
        max_model_calls=1,
        tool_requirements=[],
        max_steps=1,
        execution_mode=SimpleNamespace(value="direct"),
        policy_reason_codes=[],
        risk_level=SimpleNamespace(value="low"),
        required_capabilities=[],
        memory_write_allowed=False,
        policy_decision_id="policy-1",
        topology=ExecutionTopology.DIRECT,
        plugin_candidates=["echo"],
        memory_scope="session",
        reasoning_modes=[],
        workflow_id=None,
        intent="plugin_execution",
        reason_codes=[],
    )

    plan = runtime._build_authorized_plan(request, decision)

    assert plan.authorized_user_id == "user-1"
    assert plan.authorized_tenant_id == "tenant-1"
    assert plan.authorized_session_id == "session-1"
    assert plan.allowed_plugins == ["echo"]
    assert plan.matches_execution_scope(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        policy_decision_id="policy-1",
    )


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
    assert await ActionExecutionGate.authorize(plan, "echo") is True
    assert await ActionExecutionGate.authorize(plan, "search-plugin") is True
    assert await ActionExecutionGate.authorize(plan, "web-search") is True


@pytest.mark.asyncio
async def test_plugin_service_rejects_bare_policy_decision_id():
    service, kernel = _service()

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
    assert kernel.calls == 0


@pytest.mark.asyncio
async def test_plugin_service_rejects_cross_tenant_plan_replay():
    service, kernel = _service()

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
    assert kernel.calls == 0


@pytest.mark.asyncio
async def test_plugin_service_propagates_scope_to_canonical_kernel():
    service, kernel = _service()
    plan = _plan()

    result = await service.execute_plugin(
        "echo",
        parameters={"message": "hello"},
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conversation-1",
        correlation_id="corr-1",
        roles=["user"],
        authorized_plan=plan,
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert kernel.calls == 1
    assert kernel.request is not None
    assert kernel.request.authorized_plan is plan
    assert kernel.request.context.user_id == "user-1"
    assert kernel.request.context.tenant_id == "tenant-1"
    assert kernel.request.context.session_id == "session-1"
    assert kernel.request.context.conversation_id == "conversation-1"
    assert kernel.request.context.correlation_id == "corr-1"
    assert kernel.request.context.policy_decision_id == "policy-1"


@pytest.mark.asyncio
async def test_plugin_service_awaits_action_gate_before_kernel(monkeypatch):
    service, kernel = _service()
    plan = _plan()

    async def deny(
        authorized_plan: AuthorizedExecutionPlan,
        action: str,
    ) -> bool:
        assert authorized_plan is plan
        assert action == "echo"
        return False

    monkeypatch.setattr(ActionExecutionGate, "authorize", staticmethod(deny))

    result = await service.execute_plugin(
        "echo",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conversation-1",
        correlation_id="corr-1",
        authorized_plan=plan,
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "action_gate_denied"
    assert result.user_id == "user-1"
    assert result.tenant_id == "tenant-1"
    assert result.session_id == "session-1"
    assert result.conversation_id == "conversation-1"
    assert result.correlation_id == "corr-1"
    assert result.policy_decision_id == "policy-1"
    assert kernel.calls == 0
