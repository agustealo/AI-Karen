"""Model transport admission survives missing SDK callbacks and nested concurrency.

External execution, scoped original RuntimePolicy evidence, and both model and
external quotas are verified before a provider wire call. These tests use an
observed transport stub only; no production model completion is claimed.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import HumanMessage

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.expression.settings import ExpressionPolicyConfig
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import StructuredChatResult
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine
from ai_karen_engine.core.model_runtime.structured_tool_chat_model import (
    GovernedToolModelAdmission,
    KarenGovernedChatModel,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)


def _endpoint(url: str = "http://127.0.0.1:11434/v1", *, runtime=RuntimeEngine.CUSTOM):
    return ProviderEndpoint(
        provider_id="governed-tool-endpoint",
        display_name="Governed tool model test",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url=url,
        runtime_engine=runtime,
        supports_streaming=True,
        capabilities=("chat_completion", "tools"),
    )


def _model(
    *,
    url: str = "http://127.0.0.1:11434/v1",
    max_model_calls: int = 2,
    max_external_requests: int = 2,
    principal_roles: list[str] | None = None,
    authenticated: bool = True,
    runtime: RuntimeEngine = RuntimeEngine.CUSTOM,
):
    budget = ExecutionBudget(
        max_duration_ms=60000,
        max_model_calls=max_model_calls,
        max_external_requests=max_external_requests,
    )
    plan = AuthorizedExecutionPlan(
        execution_id="request-a",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id="tenant-a",
        authorized_session_id="session-a",
        topology=ExecutionTopology.MULTI_AGENT,
        budget=budget,
    )
    meter = ExecutionBudgetMeter(budget)
    meter.start()
    principal = UserData(
        user_id="user-a",
        tenant_id="tenant-a",
        roles=principal_roles if principal_roles is not None else ["user"],
        permissions=[],
        is_active=True,
        is_verified=True,
    )
    context = ChatExecutionContext(
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        request_id="request-a",
        correlation_id="correlation-a",
        # Untrusted context role claims must never grant external execution.
        roles=["admin"],
        permissions=["admin.providers:manage"],
        authenticated_user=principal if authenticated else None,
    )
    admission = GovernedToolModelAdmission(
        plan=plan,
        meter=meter,
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        policy_decision_id="policy-a",
        request_id="request-a",
        correlation_id="correlation-a",
        authenticated_context=context,
    )
    return KarenGovernedChatModel(
        endpoint=_endpoint(url, runtime=runtime),
        selected_model="verified-tool-model",
        execution_admission=admission,
    ), admission


def _receipt():
    return StructuredChatResult(
        message={"content": "Observed provider result", "tool_calls": []},
        provider_id="governed-tool-endpoint",
        model="verified-tool-model",
        runtime_engine="custom",
        finish_reason="stop",
        usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    )


def _wire(monkeypatch):
    transport = AsyncMock(return_value=_receipt())
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.structured_tool_chat_model."
        "execute_structured_provider_endpoint",
        transport,
    )
    return transport


def _policy(monkeypatch, *, enabled=True, admin_required=True):
    import ai_karen_engine.core.expression.settings as settings

    monkeypatch.setattr(
        settings,
        "get_expression_settings",
        lambda: SimpleNamespace(policies=ExpressionPolicyConfig(
            allow_external_engines=enabled,
            require_admin_for_external=admin_required,
        )),
    )


async def _invoke(model):
    return await model._agenerate([HumanMessage(content="run authorized tool model")])


@pytest.mark.asyncio
async def test_direct_model_call_without_admission_never_sends_http(monkeypatch):
    transport = _wire(monkeypatch)
    model = KarenGovernedChatModel(
        endpoint=_endpoint(),
        selected_model="verified-tool-model",
    )
    with pytest.raises(PermissionError, match="admission_required"):
        await _invoke(model)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_local_transport_reserves_each_model_call_even_without_sdk_callback(
    monkeypatch,
):
    transport = _wire(monkeypatch)
    model, grant = _model(max_model_calls=2)
    assert (await _invoke(model)).generations[0].message.content == "Observed provider result"
    assert (await _invoke(model)).generations[0].message.content == "Observed provider result"
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await _invoke(model)
    assert transport.await_count == 2
    assert grant.meter.model_calls == 2
    assert grant.meter.external_requests == 0


@pytest.mark.asyncio
async def test_bind_tools_preserves_the_same_host_only_budget_and_scope(monkeypatch):
    transport = _wire(monkeypatch)
    model, grant = _model(max_model_calls=1)
    clone = model.bind_tools([])
    assert clone is not model
    assert clone.execution_admission is grant
    await _invoke(clone)
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await _invoke(model)
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_nested_calls_cannot_exceed_one_shared_meter(monkeypatch):
    transport = _wire(monkeypatch)
    model, grant = _model(max_model_calls=2)
    copies = [model.bind_tools([]) for _ in range(20)]
    results = await asyncio.gather(*(_invoke(copy) for copy in copies), return_exceptions=True)
    assert sum(not isinstance(item, BaseException) for item in results) == 2
    assert transport.await_count == 2
    assert grant.meter.model_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing_meter", "foreign_tenant", "foreign_decision"])
async def test_invalid_scope_and_untrusted_budget_never_reach_wire(monkeypatch, invalid):
    transport = _wire(monkeypatch)
    model, grant = _model()
    if invalid == "missing_meter":
        model.execution_admission = replace(grant, meter=None)
    elif invalid == "foreign_tenant":
        model.execution_admission = replace(grant, tenant_id="other-tenant")
    else:
        model.execution_admission = replace(grant, policy_decision_id="other-decision")
    with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
        await _invoke(model)
    transport.assert_not_awaited()
    assert grant.meter.model_calls == 0


@pytest.mark.asyncio
async def test_remote_labeled_local_is_denied_despite_forged_roles(monkeypatch):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=True, admin_required=True)
    model, grant = _model(url="https://external.vendor.example/v1")
    with pytest.raises(PermissionError, match="external_model_execution_denied"):
        await _invoke(model)
    transport.assert_not_awaited()
    assert grant.meter.model_calls == 0
    assert grant.meter.external_requests == 0


@pytest.mark.asyncio
async def test_external_admin_permission_and_both_quotas_are_required(monkeypatch):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=True, admin_required=True)
    model, grant = _model(
        url="https://external.vendor.example/v1",
        principal_roles=["admin"],
        max_model_calls=3,
        max_external_requests=1,
    )
    await _invoke(model)
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await _invoke(model)
    transport.assert_awaited_once()
    assert grant.meter.model_calls == 1
    assert grant.meter.external_requests == 1


@pytest.mark.asyncio
async def test_external_opt_out_denies_admin_without_spending_quota(monkeypatch):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=False, admin_required=True)
    model, grant = _model(
        url="https://external.vendor.example/v1",
        principal_roles=["admin"],
    )
    with pytest.raises(PermissionError, match="external_model_execution_denied"):
        await _invoke(model)
    transport.assert_not_awaited()
    assert grant.meter.model_calls == 0
    assert grant.meter.external_requests == 0


@pytest.mark.asyncio
async def test_authenticated_nonadmin_may_execute_only_under_explicit_broader_policy(
    monkeypatch,
):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=True, admin_required=False)
    model, grant = _model(url="https://external.vendor.example/v1")
    await _invoke(model)
    transport.assert_awaited_once()
    assert grant.meter.model_calls == 1
    assert grant.meter.external_requests == 1


@pytest.mark.asyncio
async def test_remote_execution_requires_unchanged_authenticated_principal(monkeypatch):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=True, admin_required=True)
    model, grant = _model(
        url="https://external.vendor.example/v1",
        principal_roles=["admin"],
    )
    grant.authenticated_context.authenticated_user.is_active = False
    with pytest.raises(PermissionError, match="external_model_execution_denied"):
        await _invoke(model)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_remote_principal_must_not_reserve_model_or_external_budget(
    monkeypatch,
):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=True, admin_required=True)
    model, grant = _model(
        url="https://external.vendor.example/v1",
        principal_roles=["admin"],
        authenticated=False,
    )
    with pytest.raises(PermissionError, match="external_model_execution_denied"):
        await _invoke(model)
    transport.assert_not_awaited()
    assert grant.meter.model_calls == 0
    assert grant.meter.external_requests == 0


@pytest.mark.asyncio
async def test_env_override_to_remote_rechecks_at_actual_transport_boundary(
    monkeypatch,
):
    transport = _wire(monkeypatch)
    _policy(monkeypatch, enabled=False, admin_required=True)
    model, grant = _model(
        url="http://127.0.0.1:11434/v1",
        runtime=RuntimeEngine.OLLAMA,
        principal_roles=["admin"],
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://remote.vendor.example/v1")
    with pytest.raises(PermissionError, match="external_model_execution_denied"):
        await _invoke(model)
    transport.assert_not_awaited()
    assert grant.meter.model_calls == 0
