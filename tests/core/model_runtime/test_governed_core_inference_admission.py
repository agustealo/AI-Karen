"""KCHAT-AUTH-05B2A: one original admission and budget across Core façades.

No HTTP requests, downloaded models or synthetic model receipts are used.
The real principal, authorization scope and shared meter are evaluated before
the model runtime or compatibility transport can be invoked.
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextvars import ContextVar
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.model_runtime.governed_model_admission import (
    GovernedToolModelAdmission,
)
from ai_karen_engine.core.model_runtime.inference_port import (
    InferenceRequest,
    ModelManagerInferencePort,
)
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
from ai_karen_engine.core.model_runtime.model_manager import ModelManager, RuntimeSelection
from ai_karen_engine.core.model_runtime.provider_contracts import (
    EmbeddingFailed,
    ProviderNotAvailable,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import ProviderExecutionResult
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyDecision, PolicyEvaluationRequest, ProviderConstraints, RuntimePolicyEnforcer,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)


def _scope(
    *, calls: int = 2, tenant: str = "tenant-a",
    provider_constraints: dict | None = None,
    meter_model_calls: int | None = None,
    max_duration_ms: int = 60000,
    degraded_allowed: bool = True,
    user: str = "user-a",
    allowed_tools: tuple[str, ...] = (),
    topology: ExecutionTopology = ExecutionTopology.DIRECT,
) -> GovernedToolModelAdmission:
    budget = ExecutionBudget(
        max_model_calls=calls,
        max_external_requests=1,
        max_duration_ms=max_duration_ms,
    )
    plan = AuthorizedExecutionPlan(
        execution_id=f"execution-{uuid4().hex}",
        policy_decision_id="policy-a",
        authorized_user_id=user,
        authorized_tenant_id=tenant,
        authorized_session_id="session-a",
        provider_constraints=dict(provider_constraints or {}),
        allowed_tools=list(allowed_tools),
        topology=topology,
        budget=budget,
        degraded_allowed=degraded_allowed,
    )
    if meter_model_calls is not None:
        budget.max_model_calls = meter_model_calls
    meter = ExecutionBudgetMeter(budget)
    budget.max_model_calls = calls
    principal = UserData(
        user_id=user,
        tenant_id=tenant,
        roles=["user"],
        permissions=[],
        is_active=True,
        is_verified=True,
    )
    context = ChatExecutionContext(
        user_id=user,
        tenant_id=tenant,
        session_id="session-a",
        request_id="request-a",
        correlation_id="correlation-a",
        authenticated_user=principal,
    )
    issuer = RuntimePolicyEnforcer()
    issued_decision = PolicyDecision(
        decision_id=plan.policy_decision_id,
        policy_version="fixture",
        allowed=True,
        runtime_constraints={
            "authorized_user_id": context.user_id,
            "authorized_tenant_id": context.tenant_id,
            "authorized_session_id": context.session_id,
            "correlation_id": context.correlation_id,
            "max_model_calls": plan.budget.max_model_calls,
            "max_tool_calls": plan.budget.max_tool_calls,
            "allowed_tools": list(allowed_tools),
        },
    )
    # These tests exercise admission using an original issuer-returned
    # decision object. Policy evaluation itself has separate real-policy
    # integration coverage, never a production test-mode bypass.
    issuer._record_issued_model_decision(issued_decision)
    issuer.bind_chat_model_policy(
        context=context, decision=issued_decision,
    )
    context.bind_runtime_model_authority(plan, meter)
    return GovernedToolModelAdmission(
        plan=plan,
        meter=meter,
        user_id=user,
        tenant_id=tenant,
        session_id="session-a",
        policy_decision_id="policy-a",
        request_id="request-a",
        correlation_id="correlation-a",
        authenticated_context=context,
    )


def _local_manager(
    monkeypatch, *, observed_model: str | None = "model-a", shared_health: bool = False,
):
    from ai_karen_engine.core.model_runtime import model_manager as manager_module
    from ai_karen_engine.core.model_runtime import llm_adapter as adapter_module

    manager = object.__new__(ModelManager)
    endpoint = ProviderEndpoint(
        provider_id="ollama-local",
        display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:11434/v1",
        default_model=observed_model,
        tenant_scoped=not shared_health,
    )
    selection = RuntimeSelection(
        provider_id=endpoint.provider_id,
        display_name=endpoint.display_name,
        endpoint_type=endpoint.endpoint_type,
        model=endpoint.default_model,
        base_url=endpoint.base_url,
        runtime_engine=endpoint.runtime_engine.value,
    )
    attempts = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        attempts.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": observed_model,
            "choices": [{"message": {"role": "assistant", "content": "actual observed output"}}],
            "finish_reason": "stop",
        })

    original_client = httpx.AsyncClient

    def client_factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "_resolve_endpoint", lambda _: endpoint)
    def forbidden_runtime(_):
        pytest.fail("governed HTTP must not borrow the blocking compatibility runtime")
    monkeypatch.setattr(manager, "resolve_runtime", forbidden_runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager,
        "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_record_provider_result", lambda *a, **kw: None)
    monkeypatch.setattr(manager_module, "get_model_manager", lambda: manager)
    monkeypatch.setattr(adapter_module, "get_model_manager", lambda: manager)
    return manager, attempts, endpoint


@pytest.mark.asyncio
async def test_missing_core_port_admission_denied_before_manager_lookup(monkeypatch):
    from ai_karen_engine.core.model_runtime import model_manager as module

    selected = []
    monkeypatch.setattr(
        module, "get_model_manager",
        lambda: selected.append("lookup") or object(),
    )
    with pytest.raises(PermissionError, match="admission_required"):
        await ModelManagerInferencePort().generate(
            InferenceRequest(messages=[{"role": "user", "content": "private"}])
        )
    assert selected == []


@pytest.mark.asyncio
async def test_original_meter_is_charged_once_per_real_inference_attempt(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    admission = _scope(calls=1)
    request = InferenceRequest(
        messages=[{"role": "user", "content": "sensitive input"}],
        preferred_provider="ollama-local",
        execution_admission=admission,
    )
    result = await ModelManagerInferencePort().generate(request)
    assert result.text == "actual observed output"
    assert result.model == "model-a"
    assert admission.meter.model_calls == 1
    assert admission.meter.external_requests == 0
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await ModelManagerInferencePort().generate(request)
    assert len(attempts) == 1
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_invalid_principal_and_session_have_zero_model_calls(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    for mutate in (
        lambda scope: replace(scope, tenant_id="tenant-other"),
        lambda scope: replace(scope, session_id="session-other"),
        lambda scope: replace(scope, request_id="request-other"),
        lambda scope: replace(scope, policy_decision_id="policy-other"),
        lambda scope: replace(scope, meter=ExecutionBudgetMeter(
            ExecutionBudget(max_model_calls=2, max_duration_ms=60000),
        )),
    ):
        scope = _scope()
        untrusted = mutate(scope)
        with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
            await ModelManagerInferencePort().generate(
                InferenceRequest(
                    messages=[{"role": "user", "content": "private"}],
                    execution_admission=untrusted,
                )
            )
        assert scope.meter.model_calls == 0
    assert attempts == []


@pytest.mark.asyncio
async def test_deactivated_authenticated_user_denied_locally(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    scope = _scope()
    scope.authenticated_context.authenticated_user.is_active = False
    with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
        await ModelManagerInferencePort().generate(
            InferenceRequest(
                messages=[{"role": "user", "content": "private"}],
                execution_admission=scope,
            )
        )
    assert attempts == []
    assert scope.meter.model_calls == 0


@pytest.mark.asyncio
async def test_policy_provider_constraint_denies_before_client_execution(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    scope = _scope(provider_constraints={
        "eligible_providers": ["other-provider"],
    })
    with pytest.raises(PermissionError, match="provider_not_authorized"):
        await ModelManagerInferencePort().generate(
            InferenceRequest(
                messages=[{"role": "user", "content": "private"}],
                execution_admission=scope,
            )
        )
    assert attempts == []
    assert scope.meter.model_calls == 0


@pytest.mark.parametrize("selected_model", [None, "auto"])
@pytest.mark.parametrize(
    "restriction",
    [
        {"model": "model-a"},
        {"allowed_models": ["model-a"]},
        {"allowed_models": []},
    ],
)
@pytest.mark.asyncio
async def test_restricted_model_with_unresolved_identity_denied_before_wire(
    monkeypatch, selected_model, restriction,
):
    manager, attempts, _ = _local_manager(
        monkeypatch, observed_model=selected_model,
    )
    scope = _scope(provider_constraints=restriction)
    with pytest.raises(PermissionError, match="governed_model_identity_not_authorized"):
        await manager.generate_chat(
            [{"role": "user", "content": "restricted model input"}],
            return_receipt=True,
            execution_admission=scope,
        )
    assert attempts == []
    assert scope.meter.model_calls == 0
    assert scope.meter.external_requests == 0


@pytest.mark.parametrize(
    "restriction",
    [{"model": "model-a"}, {"allowed_models": ["model-a"]}],
)
@pytest.mark.asyncio
async def test_restricted_model_with_exact_identity_can_execute(monkeypatch, restriction):
    manager, attempts, _ = _local_manager(monkeypatch, observed_model="model-a")
    scope = _scope(provider_constraints=restriction)
    response = await manager.generate_chat(
        [{"role": "user", "content": "approved model input"}],
        return_receipt=True,
        execution_admission=scope,
    )
    assert isinstance(response, ProviderExecutionResult)
    assert response.model == "model-a"
    assert len(attempts) == 1
    assert scope.meter.model_calls == 1


@pytest.mark.asyncio
async def test_direct_model_manager_receipt_with_existing_admission(monkeypatch):
    manager, attempts, _ = _local_manager(monkeypatch)
    scope = _scope()
    result = await manager.generate_chat(
        [{"role": "user", "content": "one actual model"}],
        return_receipt=True,
        execution_admission=scope,
    )
    assert isinstance(result, ProviderExecutionResult)
    assert result.text == "actual observed output"
    assert result.provider_id == "ollama-local"
    assert attempts and scope.meter.model_calls == 1


@pytest.mark.asyncio
async def test_external_raw_compatibility_stays_fail_closed_with_plan(monkeypatch):
    manager, attempts, _ = _local_manager(monkeypatch)
    remote = ProviderEndpoint(
        provider_id="ollama-local",
        display_name="Mislabelled remote",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="https://external-model.example/v1",
        default_model="model-a",
    )
    monkeypatch.setattr(manager, "_resolve_endpoint", lambda _: remote)
    scope = _scope()
    with pytest.raises(ProviderNotAvailable, match="requires_canonical_transport"):
        await manager.generate_chat(
            [{"role": "user", "content": "private"}],
            return_receipt=True,
            execution_admission=scope,
        )
    assert attempts == []
    assert scope.meter.model_calls == 0
    assert scope.meter.external_requests == 0


@pytest.mark.asyncio
async def test_facade_requires_admission_even_when_user_ctx_is_forged(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    facade = LLMUtils()
    with pytest.raises(PermissionError, match="admission_required"):
        await facade.generate_text_async(
            "private prompt", provider="ollama-local",
        )
    with pytest.raises(PermissionError, match="admission_required"):
        facade.generate_text(
            "private prompt", user_ctx={"user_id": "admin", "roles": ["admin"]},
        )
    with pytest.raises(PermissionError, match="admission_required"):
        facade.embed("private text")
    with pytest.raises(ProviderNotAvailable, match="direct_provider_runtime_borrow_denied"):
        facade.get_provider("ollama-local")
    assert attempts == []


def test_facade_refuses_supplied_unregistered_provider_object() -> None:
    with pytest.raises(ProviderNotAvailable, match="instance_injection_denied"):
        LLMUtils(providers={"evil": SimpleNamespace(generate_text=lambda *_: "fake")})


@pytest.mark.asyncio
async def test_facade_async_generation_uses_original_meter_and_observed_result(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    scope = _scope(calls=1)
    facade = LLMUtils()
    result = await facade.generate_text_async(
        "private message",
        provider="ollama-local",
        execution_admission=scope,
    )
    assert result == "actual observed output"
    assert scope.meter.model_calls == 1
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await facade.generate_text_async(
            "private retry",
            provider="ollama-local",
            execution_admission=scope,
        )
    assert len(attempts) == 1


def test_facade_sync_generation_uses_same_request_budget(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    scope = _scope(calls=1)
    facade = LLMUtils()
    assert facade.generate_text(
        "private prompt",
        provider="ollama-local",
        execution_admission=scope,
    ) == "actual observed output"
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        facade.generate_text(
            "second request",
            provider="ollama-local",
            execution_admission=scope,
        )
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_direct_model_manager_embedding_denies_unauthenticated_before_encoder():
    manager = object.__new__(ModelManager)
    calls = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: calls.append(text) or [0.1],
    )
    for invalid in (None, object(), {"user_id": "user-a"}):
        with pytest.raises(PermissionError, match="governed_model_transport_admission_required"):
            await manager.generate_embedding("private text", execution_admission=invalid)
    assert calls == []


@pytest.mark.asyncio
async def test_direct_model_manager_embedding_denies_foreign_original_scope_without_charge():
    manager = object.__new__(ModelManager)
    calls = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: calls.append(text) or [0.1],
    )
    scope = _scope(calls=1)
    foreign = replace(scope, tenant_id="foreign-tenant")
    with pytest.raises(PermissionError, match="governed_model_scope_or_budget_invalid"):
        await manager.generate_embedding("private text", execution_admission=foreign)
    alternate_meter = replace(
        scope,
        meter=ExecutionBudgetMeter(
            ExecutionBudget(max_model_calls=1, max_duration_ms=60000),
        ),
    )
    with pytest.raises(PermissionError, match="governed_model_scope_or_budget_invalid"):
        await manager.generate_embedding("private text", execution_admission=alternate_meter)
    assert calls == []
    assert scope.meter.model_calls == 0
    assert scope.meter.external_requests == 0


@pytest.mark.asyncio
async def test_copied_original_plan_and_fresh_same_budget_meter_cannot_reset_quota():
    manager = object.__new__(ModelManager)
    calls = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: calls.append(text) or [0.6, 0.2],
    )
    admission = _scope(calls=1)
    assert await manager.generate_embedding(
        "first", execution_admission=admission,
    ) == [0.6, 0.2]
    assert admission.meter.model_calls == 1

    copied_plan = replace(admission.plan)
    fresh_meter_same_budget = ExecutionBudgetMeter(admission.plan.budget)
    copied_context = replace(admission.authenticated_context)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        copied_context.bind_runtime_model_authority(
            admission.plan, fresh_meter_same_budget,
        )

    # A full value-preserving clone must not be able to reissue the same
    # RuntimePolicy request with a fresh budget and zeroed counters.
    copied_budget = replace(admission.plan.budget)
    copied_policy_plan = replace(admission.plan, budget=copied_budget)
    copied_meter = ExecutionBudgetMeter(copied_budget)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        copied_context.bind_runtime_model_authority(
            copied_policy_plan, copied_meter,
        )
    forged = replace(
        admission,
        plan=copied_policy_plan,
        meter=copied_meter,
        authenticated_context=copied_context,
    )
    with pytest.raises(PermissionError, match="governed_model_scope_or_budget_invalid"):
        await manager.generate_embedding("replay", execution_admission=forged)
    assert copied_meter.model_calls == 0
    for clone in (
        replace(admission, plan=copied_plan),
        replace(admission, meter=fresh_meter_same_budget),
        replace(admission, plan=copied_plan, meter=fresh_meter_same_budget),
        replace(admission, authenticated_context=copied_context),
    ):
        with pytest.raises(PermissionError, match="governed_model_scope_or_budget_invalid"):
            await manager.generate_embedding("forbidden", execution_admission=clone)

    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        admission.authenticated_context.bind_runtime_model_authority(
            copied_plan, admission.meter,
        )
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        admission.authenticated_context.bind_runtime_model_authority(
            admission.plan, fresh_meter_same_budget,
        )
    # Neither the rejected clones nor the original exhausted grant executes
    # another encoder call, even though the replacement meter had free quota.
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await manager.generate_embedding(
            "exhausted", execution_admission=admission,
        )
    assert calls == ["first"]
    assert admission.meter.model_calls == 1
    assert fresh_meter_same_budget.model_calls == 0


@pytest.mark.asyncio
async def test_original_policy_issuer_must_reject_fresh_execution_id_replay():
    """Regression proof: a new string ID is not a RuntimePolicy authorization."""
    manager = object.__new__(ModelManager)
    invoked = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: invoked.append(text) or [0.7],
    )
    original = _scope(calls=1)
    assert await manager.generate_embedding(
        "admitted", execution_admission=original,
    ) == [0.7]
    assert original.meter.model_calls == 1

    # The caller holds the exhausted admission but has no newly issued
    # RuntimePolicy decision. Renaming an execution is not a new grant.
    copied_budget = replace(original.plan.budget)
    forged_plan = replace(
        original.plan,
        budget=copied_budget,
        execution_id=f"{original.plan.execution_id}-self-issued",
    )
    forged_context = replace(original.authenticated_context)
    fresh_meter = ExecutionBudgetMeter(copied_budget)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        forged_context.bind_runtime_model_authority(forged_plan, fresh_meter)
    forged = replace(
        original,
        plan=forged_plan,
        meter=fresh_meter,
        authenticated_context=forged_context,
    )
    with pytest.raises(
        PermissionError, match="governed_model_scope_or_budget_invalid",
    ):
        await manager.generate_embedding("unauthorized", execution_admission=forged)
    assert original.meter.model_calls == 1
    assert fresh_meter.model_calls == 0
    assert invoked == ["admitted"]


@pytest.mark.asyncio
async def test_real_runtime_policy_evaluation_is_required_before_any_initial_model_bind():
    """A policy identifier or a value-equal copy cannot issue model quota."""
    issuer = RuntimePolicyEnforcer()
    scope = PolicyEvaluationRequest(
        user_id="issued-user",
        tenant_id="issued-tenant",
        session_id="issued-session",
        correlation_id=f"issued-correlation-{uuid4().hex}",
        max_model_calls=1,
        action="general_assist",
        requested_capabilities=[],
    )
    original_decision = await issuer.evaluate(scope)
    assert original_decision.allowed
    assert issuer._issued_model_decisions.get(original_decision.decision_id) is (
        original_decision
    )

    context = ChatExecutionContext(
        user_id=scope.user_id,
        tenant_id=scope.tenant_id,
        session_id=scope.session_id,
        request_id=f"issued-request-{uuid4().hex}",
        correlation_id=scope.correlation_id,
        authenticated_user=UserData(
            user_id=scope.user_id,
            tenant_id=scope.tenant_id,
            roles=["user"],
            permissions=[],
            is_active=True,
            is_verified=True,
        ),
    )
    budget = ExecutionBudget(max_model_calls=1)
    plan = AuthorizedExecutionPlan(
        execution_id=f"exec-{context.request_id}",
        policy_decision_id=original_decision.decision_id,
        authorized_user_id=context.user_id,
        authorized_tenant_id=context.tenant_id,
        authorized_session_id=context.session_id,
        budget=budget,
    )
    meter = ExecutionBudgetMeter(budget)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        context.bind_runtime_model_authority(plan, meter)
    with pytest.raises(
        PermissionError, match="runtime_model_policy_issuance_invalid",
    ):
        issuer.bind_chat_model_policy(
            context=context,
            decision=replace(original_decision),
        )

    # The issuer must enforce its actual evaluated values, not mutable
    # attributes on the same PolicyDecision identity.
    original_decision.runtime_constraints["max_model_calls"] = 9
    with pytest.raises(
        PermissionError, match="runtime_model_policy_issuance_invalid",
    ):
        issuer.bind_chat_model_policy(context=context, decision=original_decision)
    original_decision.runtime_constraints["max_model_calls"] = 1

    original_decision.allowed_capabilities.append("model.personal_key.execute")
    with pytest.raises(
        PermissionError, match="runtime_model_policy_issuance_invalid",
    ):
        issuer.bind_chat_model_policy(context=context, decision=original_decision)
    original_decision.allowed_capabilities.pop()

    issuer.bind_chat_model_policy(context=context, decision=original_decision)

    # A serialized or in-process plan assembled before first binding cannot
    # introduce permissions that the *real evaluated policy* never granted.
    for attribute, unauthorized in (
        ("allowed_tools", ["unapproved-tool"]),
        ("allowed_plugins", ["unapproved-plugin"]),
        ("allowed_agents", ["unapproved-agent"]),
        ("allowed_capabilities", ["model.personal_key.execute"]),
    ):
        forged = replace(plan, **{attribute: unauthorized})
        with pytest.raises(
            PermissionError, match="runtime_model_execution_authority_invalid",
        ):
            context.bind_runtime_model_authority(forged, meter)
        assert context.original_runtime_model_plan(meter) is None
    context.bind_runtime_model_authority(plan, meter)
    assert context.original_runtime_model_plan(meter) is plan

    copied_budget = replace(budget)
    copied_plan = replace(
        plan, execution_id=f"forged-{uuid4().hex}", budget=copied_budget,
    )
    cloned_context = replace(context)
    with pytest.raises(
        PermissionError, match="runtime_model_policy_issuance_invalid",
    ):
        issuer.bind_chat_model_policy(
            context=cloned_context, decision=original_decision,
        )
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        cloned_context.bind_runtime_model_authority(
            copied_plan, ExecutionBudgetMeter(copied_budget),
        )
    assert context.original_runtime_model_plan(meter) is plan


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "widened"),
    [
        ("eligible_providers", []),
        ("eligible_providers", ["builtin_transformers", "external-provider"]),
        ("forbidden_providers", []),
        ("local_only", False),
        ("external_allowed", True),
        ("eligible_providers", "builtin_transformers"),
    ],
)
async def test_issued_provider_scope_cannot_widen_before_first_model_bind(
    field: str, widened: object,
) -> None:
    """A plan copy cannot relax the original issuer's provider limits."""
    issuer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="provider-scope-user",
        tenant_id="provider-scope-tenant",
        session_id="provider-scope-session",
        correlation_id=f"provider-scope-{uuid4().hex}",
        max_model_calls=1,
        requested_capabilities=[],
        provider_constraints=ProviderConstraints(
            eligible_providers=["builtin_transformers"],
            forbidden_providers=["external-provider"],
            local_only=True,
            external_allowed=False,
        ),
    )
    decision = await issuer.evaluate(request)
    assert decision.allowed
    context = ChatExecutionContext(
        user_id=request.user_id,
        tenant_id=request.tenant_id,
        session_id=request.session_id,
        request_id=f"provider-scope-request-{uuid4().hex}",
        correlation_id=request.correlation_id,
        authenticated_user=UserData(
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            roles=["user"],
            permissions=[],
            is_active=True,
            is_verified=True,
        ),
    )
    issuer.bind_chat_model_policy(context=context, decision=decision)
    original = decision.to_authorized_plan()
    assert issuer.verifies_chat_model_policy(context=context, plan=original)

    proposed = dict(original.provider_constraints)
    proposed[field] = widened
    forged = replace(original, provider_constraints=proposed)
    meter = ExecutionBudgetMeter(original.budget)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        context.bind_runtime_model_authority(forged, meter)
    assert context.original_runtime_model_plan(meter) is None
    assert meter.model_calls == 0
    assert meter.external_requests == 0

    # The original issuer-derived plan remains eligible under the same meter.
    context.bind_runtime_model_authority(original, meter)
    assert context.original_runtime_model_plan(meter) is original


@pytest.mark.asyncio
async def test_tool_only_issuer_cannot_widen_external_request_meter() -> None:
    """A zero-model policy does not authorize a forged external-call budget."""
    issuer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="external-quota-user",
        tenant_id="external-quota-tenant",
        session_id="external-quota-session",
        correlation_id=f"external-quota-{uuid4().hex}",
        max_model_calls=0,
        action="general_assist",
        requested_capabilities=[],
    )
    decision = await issuer.evaluate(request)
    assert decision.allowed
    context = ChatExecutionContext(
        user_id=request.user_id,
        tenant_id=request.tenant_id,
        session_id=request.session_id,
        request_id=f"external-quota-request-{uuid4().hex}",
        correlation_id=request.correlation_id,
        authenticated_user=UserData(
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            roles=["user"],
            permissions=[],
            is_active=True,
            is_verified=True,
        ),
    )
    issuer.bind_chat_model_policy(context=context, decision=decision)
    original = decision.to_authorized_plan()
    assert original.budget.max_model_calls == 0

    forged_budget = replace(
        original.budget,
        max_external_requests=original.budget.max_external_requests + 1,
    )
    forged_plan = replace(original, budget=forged_budget)
    forged_meter = ExecutionBudgetMeter(forged_budget)
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        context.bind_runtime_model_authority(forged_plan, forged_meter)
    assert forged_meter.external_requests == 0
    assert context.original_runtime_model_plan(forged_meter) is None

    # A legitimate tool-only, zero-model issuer-derived plan still binds.
    legitimate_meter = ExecutionBudgetMeter(original.budget)
    context.bind_runtime_model_authority(original, legitimate_meter)
    assert context.original_runtime_model_plan(legitimate_meter) is original


@pytest.mark.asyncio
async def test_allowed_zero_model_quota_preserves_tool_only_plan_without_encoder():
    issuer_scope = _scope(calls=0)
    issuer_scope._require_scope()
    assert issuer_scope.plan.budget.max_model_calls == 0
    assert issuer_scope.meter.model_calls == 0
    invoked = []
    manager = object.__new__(ModelManager)
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda data: invoked.append(data) or [0.6],
    )
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await manager.generate_embedding(
            "blocked even if local", execution_admission=issuer_scope,
        )
    assert invoked == []
    assert issuer_scope.meter.model_calls == 0


@pytest.mark.asyncio
async def test_mutating_authorized_budget_never_widens_original_meter_quota():
    """Copyable plan budget fields are not a second quota authorization."""
    budget = ExecutionBudget(
        max_model_calls=1,
        max_external_requests=1,
        max_tool_calls=1,
        max_reasoning_steps=1,
        max_input_tokens=3,
        max_duration_ms=60_000,
    )
    meter = ExecutionBudgetMeter(budget)
    meter.start()
    assert await meter.reserve_model_execution() is True
    assert meter.model_calls == 1
    assert await meter.reserve_tool_call() is True
    assert await meter.add_input_tokens(3) is True

    # An in-process consumer holding an admitted plan may mutate its
    # dataclass, but no original reservation limit can be rewritten.
    budget.max_model_calls = 100
    budget.max_tool_calls = 100
    budget.max_input_tokens = 1000
    budget.max_duration_ms = 3_600_000
    assert meter.budget is budget
    assert await meter.reserve_model_execution() is False
    assert await meter.reserve_tool_call() is False
    assert await meter.add_input_tokens(1) is False
    assert meter.model_calls == 1
    assert meter.tool_calls == 1
    assert meter.input_tokens == 3


@pytest.mark.asyncio
async def test_mutated_external_budget_cannot_gain_second_model_transport():
    budget = ExecutionBudget(
        max_model_calls=2,
        max_external_requests=1,
        max_duration_ms=60_000,
    )
    meter = ExecutionBudgetMeter(budget)
    assert await meter.reserve_model_execution(external=True) is True
    budget.max_external_requests = 50
    budget.max_model_calls = 50
    assert await meter.reserve_model_execution(external=True) is False
    assert meter.model_calls == 1
    assert meter.external_requests == 1


def test_original_meter_snapshot_must_match_policy_at_first_bind():
    # The rejected prebind replay captured three model calls while the live
    # budget was reduced to one before issuer/model authority binding.
    with pytest.raises(
        PermissionError, match="runtime_model_execution_authority_invalid",
    ):
        _scope(calls=1, meter_model_calls=3)
    admitted = _scope(calls=1)
    admitted._require_scope()
    assert admitted.meter.model_calls == 0


def test_postbind_mutations_of_root_model_permissions_fail_closed():
    scope = _scope(calls=1)
    scope._require_scope()
    scope.plan.allowed_tools.append("unapproved-tool")
    with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
        scope._require_scope()
    scope.plan.allowed_tools.clear()
    scope._require_scope()
    scope.plan.provider_constraints["eligible_providers"] = ["outside"]
    with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
        scope._require_scope()
    scope.plan.provider_constraints.clear()
    scope._require_scope()
    assert scope.meter.model_calls == 0


def test_runtime_context_binding_is_not_serialized_or_cloned():
    from dataclasses import asdict

    admission = _scope(calls=1)
    context = admission.authenticated_context
    assert context.original_runtime_model_plan(admission.meter) is admission.plan
    assert "_runtime_model_authority" not in asdict(context)
    assert "_runtime_model_authority" not in asdict(admission.plan.budget)
    assert not replace(context).is_runtime_model_plan_authorized(
        admission.plan, admission.meter,
    )


def test_medusa_style_child_scope_preserves_identity_and_single_meter():
    admission = _scope(calls=1)
    narrowed_plan = replace(
        admission.plan,
        allowed_tools=[],
        allowed_plugins=[],
        allowed_agents=[],
    )
    child = replace(admission, plan=narrowed_plan)
    with pytest.raises(PermissionError, match="governed_model_scope_or_budget_invalid"):
        child._require_scope()
    admission.authenticated_context.register_runtime_model_child_plan(
        narrowed_plan, admission.meter,
    )
    child._require_scope()
    assert child.meter is admission.meter
    with pytest.raises(PermissionError, match="runtime_model_execution_authority_invalid"):
        admission.authenticated_context.register_runtime_model_child_plan(
            replace(narrowed_plan, budget=ExecutionBudget(max_model_calls=1)),
            admission.meter,
        )


def test_facade_embedding_batch_consumes_one_budget_per_actual_vector(monkeypatch):
    manager, _, _ = _local_manager(monkeypatch)
    calls = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-sentence-transformer",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: calls.append(text) or [0.4, 0.8],
    )
    scope = _scope(calls=2)
    facade = LLMUtils()
    assert facade.embed(
        ["first", "second"], execution_admission=scope,
    ) == [[0.4, 0.8], [0.4, 0.8]]
    assert calls == ["first", "second"]
    assert scope.meter.model_calls == 2
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        facade.embed("third", execution_admission=scope)
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_concurrent_port_calls_cannot_exceed_shared_budget(monkeypatch):
    _, attempts, _ = _local_manager(monkeypatch)
    scope = _scope(calls=2)
    request = InferenceRequest(
        messages=[{"role": "user", "content": "parallel request"}],
        execution_admission=scope,
    )
    answers = await asyncio.gather(
        *(ModelManagerInferencePort().generate(request) for _ in range(12)),
        return_exceptions=True,
    )
    assert sum(not isinstance(answer, BaseException) for answer in answers) == 2
    assert len(attempts) == 2
    assert scope.meter.model_calls == 2


@pytest.mark.parametrize(
    "constraints",
    [
        {"eligible_providers": ["ollama-local"]},
        {"forbidden_providers": ["builtin_transformers"]},
    ],
)
def test_embedding_respects_runtime_policy_provider_allow_and_deny(monkeypatch, constraints):
    manager, _, _ = _local_manager(monkeypatch)
    invoked = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=True,
        model=object(),
        embed_authoritative=lambda text: invoked.append(text) or [0.1],
    )
    scope = _scope(provider_constraints=constraints)
    with pytest.raises(PermissionError, match="provider_not_authorized"):
        LLMUtils().embed("private text", execution_admission=scope)
    assert invoked == []
    assert scope.meter.model_calls == 0


def test_invalid_embedding_input_and_missing_model_spend_no_budget(monkeypatch):
    manager, _, _ = _local_manager(monkeypatch)
    invoked = []
    manager.embedding_manager = SimpleNamespace(
        model_name="local-embedding-model",
        model_loaded=False,
        model=None,
        embed_authoritative=lambda text: invoked.append(text) or [0.1],
    )
    scope = _scope(calls=1)
    facade = LLMUtils()
    with pytest.raises(EmbeddingFailed, match="embedding_model_unavailable"):
        facade.embed("input", execution_admission=scope)
    assert scope.meter.model_calls == 0
    manager.embedding_manager.model_loaded = True
    manager.embedding_manager.model = object()
    for invalid in ("", "   "):
        with pytest.raises(EmbeddingFailed, match="embedding_input_required"):
            facade.embed(invalid, execution_admission=scope)
    assert scope.meter.model_calls == 0
    assert invoked == []
    assert facade.embed("actual input", execution_admission=scope) == [0.1]
    assert scope.meter.model_calls == 1
    assert invoked == ["actual input"]


@pytest.mark.asyncio
async def test_governed_http_preserves_roles_and_canonical_receipt(monkeypatch):
    manager, attempts, _ = _local_manager(monkeypatch)
    admission = _scope(calls=1)
    messages = [
        {"role": "system", "content": "Preserve roles"},
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "Prior answer"},
        {"role": "user", "content": "Next question"},
    ]
    result = await manager.generate_chat(
        messages, execution_admission=admission, return_receipt=True,
        max_tokens=12, temperature=0.1,
    )
    assert isinstance(result, ProviderExecutionResult)
    assert result.model == "model-a"
    assert attempts[0]["messages"] == messages
    assert attempts[0]["stream"] is False
    assert attempts[0]["max_tokens"] == 12
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"stream": True}, {"tools": []}, {"max_tokens": True}, {"temperature": float("nan")},
    {"messages": [{"role": "user", "content": "injected"}]},
])
async def test_governed_http_rejects_unsupported_options_before_reservation(monkeypatch, options):
    manager, attempts, _ = _local_manager(monkeypatch)
    admission = _scope(calls=1)
    # Use the positional messages parameter except when verifying Python's
    # duplicate-argument rejection; no compatibility kwargs reach the wire.
    if "messages" in options:
        with pytest.raises(TypeError):
            await manager.generate_chat(
                [{"role": "user", "content": "input"}],
                execution_admission=admission, **options,
            )
    else:
        with pytest.raises(ProviderNotAvailable, match="governed_model_"):
            await manager.generate_chat(
                [{"role": "user", "content": "input"}],
                execution_admission=admission, **options,
            )
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_governed_http_registry_drift_prevents_wire_and_reservation(monkeypatch):
    manager, attempts, endpoint = _local_manager(monkeypatch)
    admission = _scope(calls=1)
    monkeypatch.setattr(
        manager, "_resolve_endpoint",
        lambda _: replace(endpoint, default_model="changed-model"),
    )
    with pytest.raises(ProviderNotAvailable, match="registry_drift"):
        await manager.generate_chat(
            [{"role": "user", "content": "input"}], execution_admission=admission,
        )
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_governed_http_deadline_rejects_late_receipt_without_success(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from ai_karen_engine.core.model_runtime import model_manager as module

    manager, attempts, endpoint = _local_manager(monkeypatch)
    admission = _scope(calls=1, max_duration_ms=60000)
    observations = Mock()
    monkeypatch.setattr(manager, "_record_provider_result", observations)

    async def late(*args, **kwargs):
        admission.meter._start_ms -= 61000
        return ProviderExecutionResult(
            text="late answer", model=endpoint.default_model,
            provider_id=endpoint.provider_id, runtime_engine=endpoint.runtime_engine.value,
        )

    transport = AsyncMock(side_effect=late)
    monkeypatch.setattr(module, "execute_provider_endpoint", transport)
    with pytest.raises(RuntimeError, match="execution_deadline_exhausted"):
        await manager.generate_chat(
            [{"role": "user", "content": "input"}],
            execution_admission=admission, return_receipt=True,
        )
    transport.assert_awaited_once()
    assert transport.await_args.kwargs["local_only"] is True
    assert not any(call.args[1] is True for call in observations.call_args_list)
    assert attempts == []
    assert admission.meter.model_calls == 1


def _owned_worker_fixture(monkeypatch, native, worker):
    manager, _, endpoint = _local_manager(monkeypatch)
    if native:
        from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
            TransformersRuntime,
        )
        from ai_karen_engine.core.model_runtime.runtime_engine import (
            EndpointProtocol, RuntimeEngine,
        )
        endpoint = replace(
            endpoint, provider_id="builtin_transformers", base_url=None,
            builtin=True, tenant_scoped=False,
            endpoint_type=ProviderEndpointType.BUILTIN_TRANSFORMERS,
            protocol=EndpointProtocol.NATIVE, runtime_engine=RuntimeEngine.TRANSFORMERS,
        )
        selection = RuntimeSelection(
            provider_id=endpoint.provider_id, display_name=endpoint.display_name,
            endpoint_type=endpoint.endpoint_type, model=endpoint.default_model,
            runtime_engine=endpoint.runtime_engine.value, base_url=endpoint.base_url,
        )
        provider = object.__new__(TransformersRuntime)
        def selected_worker(prompt, *, required_model, before_generate, **kwargs):
            assert required_model == endpoint.default_model
            before_generate()
            return worker(prompt, **kwargs)

        monkeypatch.setattr(provider, "generate_text_with_model", selected_worker, raising=False)
        monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
        monkeypatch.setattr(manager, "_resolve_endpoint", lambda _: endpoint)
        monkeypatch.setattr(manager, "resolve_runtime", lambda _: provider)

        def invoke(admission):
            return manager.generate_chat(
                [{"role": "user", "content": "input"}],
                return_receipt=True, execution_admission=admission,
            )
    else:
        manager.embedding_manager = SimpleNamespace(
            model_name="local-embedding-model", model_loaded=True, model=object(),
            embed_authoritative=worker,
        )

        def invoke(admission):
            return manager.generate_embedding("input", execution_admission=admission)
    return manager, invoke


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("late_failure", [False, True])
async def test_governed_native_worker_owned_across_repeated_cancellation(
    monkeypatch, native, late_failure,
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()
    marker = ContextVar("native_worker_scope", default="missing")
    marker.set("original")
    observed = []

    def worker(*args, **kwargs):
        try:
            observed.append(marker.get())
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("test worker release deadline")
            if late_failure:
                raise RuntimeError("late worker failure")
            return ("late text", "model-a") if native else [0.1]
        finally:
            retired.set()

    manager, invoke = _owned_worker_fixture(monkeypatch, native, worker)
    from unittest.mock import Mock
    observations = Mock()
    monkeypatch.setattr(manager, "_record_provider_result", observations)
    admission = _scope(calls=1)
    task = asyncio.create_task(invoke(admission))
    try:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task  # expose the original pre-worker failure
            raise
        assert observed == ["original"]
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not retired.is_set()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)

    assert retired.is_set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert admission.meter.model_calls == 1
    assert not any(call.args[1] is True for call in observations.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_expired_native_worker_result_never_becomes_success(monkeypatch, native):
    from unittest.mock import Mock

    admission = _scope(calls=1)
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()

    def worker(*args, **kwargs):
        try:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("test worker release deadline")
            return ("late text", "model-a") if native else [0.1]
        finally:
            retired.set()

    manager, invoke = _owned_worker_fixture(monkeypatch, native, worker)
    observations = Mock()
    monkeypatch.setattr(manager, "_record_provider_result", observations)
    task = asyncio.create_task(invoke(admission))
    try:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task  # expose the original pre-worker failure
            raise
        admission.meter._start_ms -= 61000
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)
    assert retired.is_set()
    with pytest.raises(RuntimeError, match="execution_deadline_exhausted"):
        await task
    assert admission.meter.model_calls == 1
    assert not any(call.args[1] is True for call in observations.call_args_list)


@pytest.mark.asyncio
async def test_native_embedding_timeout_waits_for_worker_retirement(monkeypatch):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()

    def worker(text):
        try:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("test worker release deadline")
            return [0.1]
        finally:
            retired.set()

    _, invoke = _owned_worker_fixture(monkeypatch, False, worker)
    admission = _scope(calls=1, max_duration_ms=500)
    task = asyncio.create_task(invoke(admission))
    try:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task  # expose the original pre-worker failure
            raise
        await asyncio.sleep(0.6)
        assert not task.done()
        assert not retired.is_set()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)
    assert retired.is_set()
    with pytest.raises(RuntimeError, match="execution_deadline_exhausted"):
        await task
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_native_admission_propagates_caller_cancellation_to_worker_checkpoint():
    admission = _scope(calls=1)
    await admission.reserve_local_embedding(model="local-embedding-model")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    retired = threading.Event()
    observed_stop = threading.Event()
    release = threading.Event()

    def worker(checkpoint):
        try:
            loop.call_soon_threadsafe(entered.set)
            # No native library is needed to exercise the real stop owner.
            while not release.wait(0.01):
                checkpoint()
        except ProviderNotAvailable as exc:
            if str(exc) == "governed_model_execution_cancelled":
                observed_stop.set()
            raise
        finally:
            retired.set()

    task = asyncio.create_task(admission.run_admitted_blocking(worker))
    try:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task  # expose the original pre-worker failure
            raise
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert observed_stop.is_set()
        assert retired.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_native_reservation_is_local_without_relaxing_http_classification():
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS
    from ai_karen_engine.core.model_runtime.provider_execution import (
        provider_endpoint_requires_external_permission,
    )

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=1)
    assert provider_endpoint_requires_external_permission(endpoint) is True
    await admission.reserve_native_generation(endpoint, model="model-a")
    assert admission.meter.model_calls == 1
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"base_url": "https://remote.example/v1"},
    {"provider_id": "unregistered-native"},
    {"builtin": False},
    {"enabled": False},
])
async def test_native_reservation_rejects_mislabeled_endpoint(changes):
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=1)
    with pytest.raises(PermissionError, match="native_endpoint_not_eligible"):
        await admission.reserve_native_generation(replace(endpoint, **changes), model="model-a")
    assert admission.meter.model_calls == 0
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
async def test_native_attempt_sequence_reserves_before_dispatch_and_rejects_overrun():
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=2)
    observed = []
    dispatched = []
    captured = []
    loop_thread = threading.get_ident()

    def worker(checkpoint, reserve):
        assert threading.get_ident() != loop_thread
        captured.append(reserve)
        checkpoint()
        for index in range(3):
            reserve()
            dispatched.append(index)

    with pytest.raises(RuntimeError, match="budget_exhausted"):
        await admission.run_native_attempt_sequence(
            endpoint, model="model-a", function=worker,
            on_reserved=lambda: observed.append(
                (threading.get_ident(), admission.meter.model_calls),
            ),
        )
    assert dispatched == [0, 1]
    assert observed == [(loop_thread, 1), (loop_thread, 2)]
    assert admission.meter.model_calls == 2
    assert admission.meter.external_requests == 0
    with pytest.raises(RuntimeError, match="worker_scope_invalid"):
        captured[0]()


@pytest.mark.asyncio
async def test_native_attempt_sequence_denies_forged_meter_before_worker():
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=1)
    forged = replace(admission, meter=ExecutionBudgetMeter(admission.plan.budget))
    with pytest.raises(PermissionError, match="scope_or_budget_invalid"):
        await forged.run_native_attempt_sequence(
            endpoint, model="model-a",
            function=lambda *_: pytest.fail("unauthorized worker"),
        )
    assert admission.meter.model_calls == forged.meter.model_calls == 0


@pytest.mark.asyncio
async def test_native_attempt_sequence_preserves_failed_attempt_and_zero_attempt_work():
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=1)
    assert await admission.run_native_attempt_sequence(
        endpoint, model="model-a", function=lambda *_: "prepared",
    ) == "prepared"
    assert admission.meter.model_calls == 0

    def worker(checkpoint, reserve):
        reserve()
        raise ValueError("native failure")

    with pytest.raises(ValueError, match="native failure"):
        await admission.run_native_attempt_sequence(
            endpoint, model="model-a", function=worker,
        )
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_native_attempt_sequence_retains_worker_and_stops_later_attempts():
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=2)
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()
    observed = []

    def worker(checkpoint, reserve):
        try:
            reserve()
            observed.append("first")
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("test worker release deadline")
            reserve()
            observed.append("second")
        finally:
            retired.set()

    task = asyncio.create_task(admission.run_native_attempt_sequence(
        endpoint, model="model-a", function=worker,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not retired.is_set()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert retired.is_set()
    assert observed == ["first"]
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_late_native_retirement_failure_survives_repeated_cancellation():
    from ai_karen_engine.core.model_runtime.provider_contracts import NativeRetirementUnverified

    admission = _scope(calls=1)
    await admission.reserve_local_embedding(model="local-embedding-model")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def worker(checkpoint):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("test worker release deadline")
        raise NativeRetirementUnverified()

    task = asyncio.create_task(admission.run_admitted_blocking(worker))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)
    with pytest.raises(NativeRetirementUnverified):
        await task
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_workflow_serialized_plan_is_not_model_authority():
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRequest, WorkflowGenerationRuntime,
    )

    admission = _scope()
    request = WorkflowGenerationRequest(
        request_id=admission.request_id, correlation_id=admission.correlation_id,
        tenant_id=admission.tenant_id, user_id=admission.user_id,
        conversation_id="conversation-a", policy_decision_id=admission.policy_decision_id,
        messages=[{"role": "user", "content": "task"}],
        authorized_plan={"execution_id": admission.plan.execution_id,
                         "policy_decision_id": admission.policy_decision_id},
    )
    with pytest.raises(PermissionError, match="authority_required"):
        await WorkflowGenerationRuntime().execute(request)
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_workflow_authority_revocation_invalidates_copied_task_context():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, WorkflowGenerationRequest,
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope()
    authority = WorkflowGenerationAuthority.create(
        ChatExecutionRequest(context=admission.authenticated_context,
                             messages=[{"role": "user", "content": "task"}]),
        ExecutionDecision(), admission.plan, admission.meter,
    )
    request = WorkflowGenerationRequest(
        request_id=admission.request_id, correlation_id=admission.correlation_id,
        tenant_id=admission.tenant_id, user_id=admission.user_id,
        conversation_id="conversation-a", policy_decision_id=admission.policy_decision_id,
        messages=[], authorized_plan={},
    )
    start = asyncio.Event()

    async def copied_context():
        await start.wait()
        await WorkflowGenerationRuntime().execute(request)

    with bind_workflow_generation(authority):
        task = asyncio.create_task(copied_context())
    authority.revoke()
    start.set()
    with pytest.raises(PermissionError, match="authority_revoked"):
        await task
    assert admission.meter.model_calls == 0


def _workflow_transport(monkeypatch, admission, *, available=True, observed_model="model-a",
                        preferred_provider="ollama-local", disable_primary=False,
                        retry_secondary=False):
    from ai_karen_engine.core.expression.gateway import ExpressionGateway
    from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings
    from ai_karen_engine.core.model_runtime import provider_registry_service
    from ai_karen_engine.core.runtime import composition
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, WorkflowGenerationRequest,
    )

    _, attempts, endpoint = _local_manager(monkeypatch, observed_model=observed_model)
    endpoint = replace(
        endpoint, default_model="model-a",
        capabilities=("chat_completion", "text_generation"),
    )
    endpoints = {endpoint.provider_id: endpoint}
    if retry_secondary:
        secondary = replace(
            endpoint, provider_id="llamacpp-server", base_url="http://127.0.0.1:8080/v1",
        )
        endpoints[secondary.provider_id] = secondary
    registry = SimpleNamespace(
        get_provider_endpoint=endpoints.get,
        get_provider_status=lambda _: SimpleNamespace(is_available=available),
        resolve_capable_targets=lambda **_: list(endpoints.values()),
        canonicalize_provider_id=lambda value: value,
    )
    monkeypatch.setattr(
        provider_registry_service, "get_provider_registry_service", lambda: registry,
    )
    settings = ExpressionSettings()
    if disable_primary:
        settings.engines["local"].enabled = False
        settings.engines["secondary"] = EngineConfig(enabled=True, type="openai_compatible")
        settings.engine_fallback_order = ["local", "secondary"]
    if retry_secondary:
        settings.engines["secondary"] = EngineConfig(
            enabled=True, type="openai_compatible",
            metadata={"preferred_provider": "llamacpp-server"},
        )
        settings.engine_fallback_order = ["local", "secondary"]
    gateway = ExpressionGateway(settings=settings)
    monkeypatch.setattr(composition, "get_expression_gateway", lambda: gateway)
    ctx = admission.authenticated_context
    messages = [{"role": "user", "content": "Explain the workflow result."}]
    original = ChatExecutionRequest(
        context=ctx, messages=messages, preferred_provider=preferred_provider,
        preferred_model="model-a",
    )
    decision = ExecutionDecision()
    authority = WorkflowGenerationAuthority.create(
        original, decision, admission.plan, admission.meter,
    )
    admission.meter.start()
    request = WorkflowGenerationRequest(
        request_id=admission.request_id, correlation_id=admission.correlation_id,
        tenant_id=admission.tenant_id, user_id=admission.user_id,
        conversation_id=ctx.require_conversation_id(),
        policy_decision_id=admission.policy_decision_id, messages=messages,
        authorized_plan={"execution_id": admission.plan.execution_id,
                         "policy_decision_id": admission.policy_decision_id},
    )
    return authority, request, attempts


@pytest.mark.asyncio
async def test_workflow_governed_http_uses_original_meter_and_observed_receipt(monkeypatch):
    from ai_karen_engine.core.expression.errors import EngineUnavailableError
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    with bind_workflow_generation(authority):
        result = await WorkflowGenerationRuntime().execute(request)
        assert result.text == "actual observed output"
        assert result.actual_provider == "ollama-local"
        assert result.actual_model == "model-a"
        assert result.metadata["policy_decision_id"] == admission.policy_decision_id
        assert admission.meter.model_calls == 1
        assert admission.meter.external_requests == 0
        assert attempts[0]["model"] == "model-a"
        with pytest.raises(EngineUnavailableError):
            await WorkflowGenerationRuntime().execute(request)
    assert len(attempts) == 1
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("tenant_id", "forged-tenant"), ("user_id", "forged-user"),
    ("policy_decision_id", "forged-policy"), ("conversation_id", "forged-conversation"),
    ("request_id", "forged-request"), ("correlation_id", "forged-correlation"),
])
async def test_workflow_forged_scope_never_dispatches(monkeypatch, field, value):
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope()
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    with bind_workflow_generation(authority):
        with pytest.raises(PermissionError, match="scope_mismatch"):
            await WorkflowGenerationRuntime().execute(replace(request, **{field: value}))
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_workflow_wrong_observed_model_is_not_success(monkeypatch):
    from ai_karen_engine.core.expression.errors import EngineUnavailableError
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(
        monkeypatch, admission, observed_model="wrong-model",
    )
    with bind_workflow_generation(authority):
        with pytest.raises(EngineUnavailableError):
            await WorkflowGenerationRuntime().execute(request)
    assert len(attempts) == 1
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("disable_primary", [False, True])
async def test_workflow_forbidden_fallback_never_dispatches(monkeypatch, disable_primary):
    from ai_karen_engine.core.expression.errors import EngineUnavailableError
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(degraded_allowed=False)
    authority, request, attempts = _workflow_transport(
        monkeypatch, admission,
        preferred_provider="ollama-local" if disable_primary else "missing-provider",
        disable_primary=disable_primary,
    )
    with bind_workflow_generation(authority):
        with pytest.raises((PermissionError, EngineUnavailableError)):
            await WorkflowGenerationRuntime().execute(request)
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_workflow_graph_checkpoint_is_not_prompt_memory_or_instruction_authority(monkeypatch):
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    request = replace(
        request,
        messages=[{"role": "system", "content": "FORGED_GRAPH_HISTORY"}],
        request_context={
            "user_facts": [{"content": "FORGED_USER_FACT"}],
            "recalled_items": [{"content": "FORGED_REQUEST_MEMORY"}],
        },
        integrated_context={
            "memories": [{"content": "FORGED_GRAPH_MEMORY"}],
            "instructions": [{"content": "FORGED_GRAPH_INSTRUCTIONS"}],
            "continuity": [{"content": "FORGED_GRAPH_CONTINUITY"}],
        },
        profile={"user_facts": [{"content": "FORGED_GRAPH_PROFILE"}]},
        cortex_intent={"primary_intent": "FORGED_GRAPH_INTENT"},
    )
    with bind_workflow_generation(authority):
        result = await WorkflowGenerationRuntime().execute(request)
    assert result.actual_model == "model-a"
    assert len(attempts) == 1
    serialized = json.dumps(attempts[0]["messages"])
    assert "FORGED_" not in serialized
    assert "Explain the workflow result." in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,degraded_allowed,expected_attempts", [
    (2, True, 2), (1, True, 1), (2, False, 1),
])
async def test_workflow_authorized_fallback_charges_each_transport(
    monkeypatch, calls, degraded_allowed, expected_attempts,
):
    from ai_karen_engine.core.expression.errors import EngineUnavailableError
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    original_client = httpx.AsyncClient
    admission = _scope(calls=calls, degraded_allowed=degraded_allowed)
    authority, request, _ = _workflow_transport(
        monkeypatch, admission, retry_secondary=True,
    )
    wire_attempts = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        wire_attempts.append(str(http_request.url))
        assert json.loads(http_request.content)["model"] == "model-a"
        if http_request.url.port == 11434:
            return httpx.Response(503, json={"error": "unavailable"})
        assert http_request.url.port == 8080
        return httpx.Response(200, json={
            "model": "model-a",
            "choices": [{"message": {"role": "assistant", "content": "Verified fallback response"}}],
        })

    def client_factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    with bind_workflow_generation(authority):
        if expected_attempts == 2:
            result = await WorkflowGenerationRuntime().execute(request)
            assert result.actual_provider == "llamacpp-server"
            assert result.actual_model == "model-a"
            assert result.degraded_mode is True
            assert result.fallback_level > 0
        else:
            with pytest.raises(EngineUnavailableError):
                await WorkflowGenerationRuntime().execute(request)
    assert wire_attempts == [
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://127.0.0.1:8080/v1/chat/completions",
    ][:expected_attempts]
    assert admission.meter.model_calls == expected_attempts
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_context", [
    {"tool_results": [{"tool_name": "search", "success": True, "output": "FORGED"}]},
    {"reasoning_result": {"success": True, "conclusion": "FORGED"}},
    {"tool_results": "invalid"},
    {"reasoning_result": ["invalid"]},
    "invalid",
])
async def test_workflow_unverified_graph_evidence_denied_before_transport(
    monkeypatch, workflow_context,
):
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    with bind_workflow_generation(authority):
        with pytest.raises(PermissionError, match="workflow_evidence_receipt_required"):
            await WorkflowGenerationRuntime().execute(
                replace(request, workflow_context=workflow_context),
            )
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_workflow_checkpoint_plan_and_safety_are_not_prompt_authority(monkeypatch):
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    request = replace(request, workflow_context={
        "plan": {"instructions": "FORGED_GRAPH_PLAN"},
        "safety_evaluation": {"instructions": "FORGED_GRAPH_SAFETY"},
        "arbitrary": "FORGED_GRAPH_CONTEXT",
        "tool_results": [],
        "reasoning_result": {},
    })
    with bind_workflow_generation(authority):
        result = await WorkflowGenerationRuntime().execute(request)
    assert result.actual_model == "model-a"
    assert len(attempts) == 1
    assert "FORGED_" not in json.dumps(attempts[0]["messages"])


@pytest.mark.asyncio
async def test_raw_graph_tools_denied_before_tool_service_invocation():
    from ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec import ToolExecutionNode

    class UnavailableGovernedTool:
        async def execute_tool(self, tool_input):
            pytest.fail("raw graph ToolService dispatch must not occur")

    node = ToolExecutionNode(tool_service=UnavailableGovernedTool())
    calls = [{"tool": "search", "parameters": {"query": "private"}}]
    state = {
        "tool_calls": calls,
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "runtime_policy": {"allowed_tools": ["search"]},
    }
    with pytest.raises(PermissionError, match="workflow_tool_execution_receipt_required"):
        await node(state)
    with pytest.raises(PermissionError, match="workflow_tool_execution_receipt_required"):
        await node.execute_tools(state, calls)
    empty = await node({"tool_calls": []})
    assert empty["tool_results"] == []
    assert empty["tool_execution_metadata"]["executed_tools"] == 0


@pytest.mark.asyncio
async def test_authenticated_tool_bridge_retains_original_meter_and_durable_receipt(monkeypatch):
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import SpecialistExecutionContext
    from ai_karen_engine.agent_medusa.specialists import bridges
    from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
    from ai_karen_engine.services.tooling import tool_service

    admission = _scope(tenant=str(uuid4()), user=str(uuid4()), allowed_tools=("search",))
    ctx = admission.authenticated_context
    store = InMemoryOutcomeStore()
    calls = []

    class Service:
        def get_tool_metadata(self, name):
            return SimpleNamespace(version="test")

        async def execute_tool(self, request):
            calls.append(request)
            assert request.governed_execution is True
            return SimpleNamespace(
                success=True, error=None, metadata={}, request_id=request.request_id,
                result={"observation": "actual tool result"},
            )

    monkeypatch.setattr(tool_service, "get_tool_service", lambda: Service())
    monkeypatch.setattr(bridges, "get_outcome_store", lambda: store)
    execution = SpecialistExecutionContext(
        authorized_plan=admission.plan,
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, session_id=ctx.session_id,
        policy_decision_id=admission.policy_decision_id,
        trajectory_id="actual-runtime-trajectory", correlation_id=ctx.correlation_id,
        step_id="step-a", budget_meter=admission.meter,
        authenticated_chat_context=ctx,
    )

    async def invoke(scope, tool_name="search"):
        return await bridges.ToolBridge().execute(
            tool_name=tool_name, parameters={},
            authorized_plan=scope.authorized_plan,
            tenant_id=ctx.tenant_id, user_id=ctx.user_id,
            policy_decision_id=admission.policy_decision_id,
            trajectory_id=execution.trajectory_id, agent_id="researcher",
            step_id=execution.step_id, execution=scope,
        )

    for invalid in (
        replace(execution, budget_meter=None),
        replace(execution, budget_meter=ExecutionBudgetMeter(admission.plan.budget)),
        replace(execution, authorized_plan=replace(admission.plan)),
        replace(execution, correlation_id="forged-correlation"),
    ):
        with pytest.raises(PermissionError):
            await invoke(invalid)
    with pytest.raises(PermissionError, match="not authorized"):
        await invoke(execution, tool_name="unauthorized")
    assert calls == []
    assert admission.meter.tool_calls == 0

    result = await invoke(execution)
    assert result["success"] is True
    assert result["receipt_id"].startswith("out_tool_")
    assert len(calls) == 1
    assert admission.meter.tool_calls == 1
    receipts = await store.list_governed_tool_receipts_async(
        trajectory_id=execution.trajectory_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
    )
    assert len(receipts) == 1
    assert receipts[0]["outcome_id"] == result["receipt_id"]
    assert receipts[0]["metadata"]["independently_verified"] is False


@pytest.mark.asyncio
async def test_workflow_receipt_uses_host_trajectory_not_checkpoint_metadata(monkeypatch):
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=1)
    authority, request, attempts = _workflow_transport(monkeypatch, admission)
    authority = WorkflowGenerationAuthority.create(
        authority.request, authority.decision, admission.plan, admission.meter,
        trajectory_id="runtime-owned-trajectory",
    )
    request = replace(request, request_context={"trajectory_id": "forged-trajectory"})
    with bind_workflow_generation(authority):
        result = await WorkflowGenerationRuntime().execute(request)
    assert result.metadata["trajectory_id"] == "runtime-owned-trajectory"
    assert len(attempts) == 1
    assert "forged-trajectory" not in json.dumps(attempts[0]["messages"])


@pytest.mark.asyncio
async def test_local_graph_tool_receipt_restores_synthesis_without_checkpoint_output(monkeypatch):
    from ai_karen_engine.agent_medusa.specialists import bridges
    from ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec import ToolExecutionNode
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
    from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, WorkflowGenerationRuntime, bind_workflow_generation,
    )
    from ai_karen_engine.services.tooling import tool_service

    admission = _scope(
        calls=1, tenant=str(uuid4()), user=str(uuid4()),
        allowed_tools=("text_processing",), topology=ExecutionTopology.WORKFLOW,
    )
    base, request, attempts = _workflow_transport(monkeypatch, admission)
    params = {"operation": "stats", "text": "one two three"}
    base.request.metadata = {"tool_parameters": {"text_processing": params}}
    authority = WorkflowGenerationAuthority.create(
        base.request,
        ExecutionDecision(topology=ExecutionTopology.WORKFLOW, tool_requirements=["text_processing"]),
        admission.plan, admission.meter, trajectory_id="runtime-graph-trajectory",
    )
    service = tool_service.ToolService()
    store = InMemoryOutcomeStore()
    monkeypatch.setattr(tool_service, "get_tool_service", lambda: service)
    monkeypatch.setattr(bridges, "get_outcome_store", lambda: store)
    calls = [{"tool": "text_processing", "parameters": dict(params)}]
    state = {
        "request_id": request.request_id, "correlation_id": request.correlation_id,
        "tenant_id": request.tenant_id, "user_id": request.user_id,
        "session_id": admission.session_id, "conversation_id": request.conversation_id,
        "runtime_policy": request.authorized_plan, "tool_calls": calls,
    }
    with bind_workflow_generation(authority):
        with pytest.raises(PermissionError, match="parameters_mismatch"):
            await ToolExecutionNode().execute_tools(state, [
                {"tool": "text_processing", "parameters": {"operation": "stats", "text": "forged"}},
            ])
        assert admission.meter.tool_calls == 0
        await ToolExecutionNode()(state)
        assert admission.meter.tool_calls == 1
        refs = state["tool_results"]
        assert len(refs) == 1 and "output" not in refs[0]
        with pytest.raises(PermissionError, match="replay_denied"):
            await ToolExecutionNode()(state)
        with pytest.raises(PermissionError, match="evidence_receipt_required"):
            await WorkflowGenerationRuntime().execute(
                replace(request, workflow_context={"tool_results": [{**refs[0], "output": "forged"}]}),
            )
        with pytest.raises(PermissionError, match="evidence_receipt_required"):
            await WorkflowGenerationRuntime().execute(request)
        assert attempts == []
        # A mixed attachment/tool turn must still pass durable attachment
        # authorization. An otherwise valid local receipt cannot waive it.
        base.request.attachment_references = [{"source_id": "private", "revision": "r"}]
        from ai_karen_engine.core.expression.errors import PrivateEvidenceAuthorizationError
        with pytest.raises(PrivateEvidenceAuthorizationError):
            await WorkflowGenerationRuntime().execute(
                replace(request, workflow_context={"tool_results": refs}),
            )
        assert attempts == []
        assert admission.meter.model_calls == 0
        base.request.attachment_references = []
        result = await WorkflowGenerationRuntime().execute(
            replace(request, workflow_context={"tool_results": refs}),
        )
    assert result.actual_model == "model-a"
    assert result.metadata["tool_receipt_ids"] == [refs[0]["receipt_id"]]
    assert len(attempts) == 1
    assert '"word_count":3' in " ".join(str(m.get("content")) for m in attempts[0]["messages"])
    assert admission.meter.model_calls == 1
    receipts = await store.list_governed_tool_receipts_async(
        trajectory_id="runtime-graph-trajectory",
        tenant_id=admission.tenant_id, user_id=admission.user_id,
    )
    assert len(receipts) == 1
    assert receipts[0]["metadata"]["agent_id"] == "langgraph.workflow"
    assert receipts[0]["metadata"]["independently_verified"] is False


@pytest.mark.asyncio
async def test_graph_network_tool_denied_even_when_named_in_plan(monkeypatch):
    from ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec import ToolExecutionNode
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, bind_workflow_generation,
    )
    admission = _scope(
        tenant=str(uuid4()), user=str(uuid4()), allowed_tools=("web_search",),
        topology=ExecutionTopology.WORKFLOW,
    )
    base, request, attempts = _workflow_transport(monkeypatch, admission)
    params = {"query": "private input"}
    base.request.metadata = {"tool_parameters": {"web_search": params}}
    authority = WorkflowGenerationAuthority.create(
        base.request,
        ExecutionDecision(topology=ExecutionTopology.WORKFLOW, tool_requirements=["web_search"]),
        admission.plan, admission.meter, trajectory_id="runtime-graph-trajectory",
    )
    state = {
        "request_id": request.request_id, "correlation_id": request.correlation_id,
        "tenant_id": request.tenant_id, "user_id": request.user_id,
        "session_id": admission.session_id, "conversation_id": request.conversation_id,
        "runtime_policy": request.authorized_plan,
        "tool_calls": [{"tool": "web_search", "parameters": params}],
    }
    with bind_workflow_generation(authority):
        with pytest.raises(PermissionError, match="not_local_compute"):
            await ToolExecutionNode()(state)
    assert admission.meter.tool_calls == 0
    assert attempts == []


@pytest.mark.asyncio
async def test_production_tool_bootstrap_isolates_optional_import_failure(monkeypatch, caplog):
    import ai_karen_engine.tools as catalog
    from ai_karen_engine.services.tooling.tool_service import ToolInput, ToolService
    from ai_karen_engine.tools.text_processing_tool import TextProcessingTool

    real_import = catalog.import_module

    def isolated_import(name, package=None):
        if name == ".web_search_tool":
            raise ImportError("private optional dependency diagnostic")
        return real_import(name, package)

    monkeypatch.setattr(catalog, "import_module", isolated_import)
    service = ToolService()
    assert service.registry.get_tool("web_search") is None
    tool = service.registry.get_tool("text_processing")
    assert isinstance(tool, TextProcessingTool)
    assert tool.metadata.workflow_local_compute is True
    assert "private optional dependency diagnostic" not in caplog.text
    result = await service.execute_tool(ToolInput(
        tool_name="text_processing",
        parameters={"operation": "stats", "text": "one two three"},
        governed_execution=True,
        workflow_local_compute=True,
    ))
    assert result.success is True
    assert result.result["word_count"] == 3


@pytest.mark.asyncio
async def test_medusa_generation_bridge_uses_governed_local_transport(monkeypatch):
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import SpecialistExecutionContext
    from ai_karen_engine.agent_medusa.specialists.bridges import GenerationBridge

    admission = _scope(calls=1, topology=ExecutionTopology.MULTI_AGENT)
    _, _, attempts = _workflow_transport(monkeypatch, admission)
    ctx = admission.authenticated_context
    execution = SpecialistExecutionContext(
        authorized_plan=admission.plan, tenant_id=ctx.tenant_id,
        user_id=ctx.user_id, session_id=ctx.session_id,
        policy_decision_id=admission.policy_decision_id,
        trajectory_id=ctx.request_id, correlation_id=ctx.correlation_id,
        step_id="analysis-step", budget_meter=admission.meter,
        authenticated_chat_context=ctx,
        preferred_provider="ollama-local", preferred_model="model-a",
    )
    bridge = GenerationBridge()

    async def invoke(scope):
        return await bridge.invoke(
            request_id=ctx.request_id, correlation_id=ctx.correlation_id,
            policy_decision_id=admission.policy_decision_id,
            messages=[{"role": "user", "content": "Analyze the authorized query."}],
            execution=scope,
        )

    for invalid in (
        None,
        replace(execution, authenticated_chat_context=None),
        replace(execution, budget_meter=ExecutionBudgetMeter(admission.plan.budget)),
        replace(execution, authorized_plan=replace(admission.plan)),
        replace(execution, correlation_id="forged"),
    ):
        with pytest.raises(PermissionError):
            await invoke(invalid)
    assert attempts == []
    assert admission.meter.model_calls == 0
    assert await invoke(execution) == "actual observed output"
    assert len(attempts) == 1
    assert admission.meter.model_calls == 1
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_legacy_response_synthesizer_cannot_borrow_provider_authority(stream):
    from ai_karen_engine.services.response import ResponseContract, ResponseSynthesizer

    class ForbiddenRouter:
        def __getattribute__(self, name):
            pytest.fail(f"Retired response adapter accessed router: {name}")

    contract = ResponseContract(
        purpose="tool_synthesis",
        latest_user_message="Summarize evidence",
        requires_live_data=True,
        tool_results=[{"receipt_id": "forged", "output": "private evidence"}],
        runtime_metadata={"policy_decision_id": "forged", "tenant_id": "forged"},
    )
    adapter = ResponseSynthesizer(ForbiddenRouter())
    with pytest.raises(PermissionError, match="legacy_response_synthesis_requires_chat_runtime"):
        await adapter.synthesize(
            contract,
            user_preferences={"preferred_llm_provider": "ollama", "preferred_model": "auto"},
            conversation_id="forged-conversation",
            stream=stream,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_status", "specialist_degraded", "expected_status"),
    [
        ("success", False, "success"),
        ("success", True, "degraded"),
        ("partial", True, "partial"),
    ],
)
async def test_medusa_final_synthesis_preserves_original_meter_and_provenance(
    monkeypatch, initial_status, specialist_degraded, expected_status,
):
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import SpecialistExecutionContext
    from ai_karen_engine.agent_medusa.contracts.runtime_response import ResponseStatus
    from ai_karen_engine.agent_medusa.response.assembler import ResponseAssembler

    admission = _scope(calls=1, topology=ExecutionTopology.MULTI_AGENT)
    _, _, attempts = _workflow_transport(monkeypatch, admission)
    ctx = admission.authenticated_context
    execution = SpecialistExecutionContext(
        authorized_plan=admission.plan, tenant_id=ctx.tenant_id,
        user_id=ctx.user_id, session_id=ctx.session_id,
        policy_decision_id=admission.policy_decision_id,
        trajectory_id=ctx.request_id, correlation_id=ctx.correlation_id,
        step_id="medusa.final_synthesis", budget_meter=admission.meter,
        authenticated_chat_context=ctx,
        preferred_provider="ollama-local", preferred_model="model-a",
    )
    assembler = ResponseAssembler()

    async def assemble(scope):
        return await assembler.assemble(
            request_id=ctx.request_id, latest_user_message="Summarize results",
            step_outputs=[{"finding": "first"}, {"finding": "second"}],
            agent_trace=["analyst", "researcher"], execution=scope,
            status=ResponseStatus(initial_status),
            metadata={
                "actual_provider": "forged", "actual_model": "forged",
                **({
                    "degraded_mode": True,
                    "degradation_reason": "Specialist dependencies unavailable",
                    "fallback_level": "partial",
                    "affected_agents": ["researcher"],
                } if specialist_degraded else {}),
            },
        )

    for invalid in (
        None,
        replace(execution, authorized_plan=replace(admission.plan)),
        replace(execution, budget_meter=ExecutionBudgetMeter(admission.plan.budget)),
        replace(execution, trajectory_id="forged"),
    ):
        with pytest.raises(PermissionError):
            await assemble(invalid)
    assert not attempts and admission.meter.model_calls == 0
    result = await assemble(execution)
    assert result.content == "actual observed output"
    assert result.status is ResponseStatus(expected_status)
    assert result.metadata["degraded_mode"] is specialist_degraded
    assert result.metadata["synthesis"]["degraded_mode"] is False
    assert result.metadata["synthesis"]["fallback_level"] == 0
    if specialist_degraded:
        assert result.metadata["degradation_reason"] == "Specialist dependencies unavailable"
        assert result.metadata["specialist_degradation"] == {
            "degraded_mode": True,
            "degradation_reason": "Specialist dependencies unavailable",
            "fallback_level": "partial",
            "affected_agents": ["researcher"],
        }
    else:
        assert "specialist_degradation" not in result.metadata
    assert result.metadata["actual_provider"] == "ollama-local"
    assert result.metadata["actual_model"] == "model-a"
    assert result.metadata["synthesis"]["source"] == "expression_gateway"
    assert len(attempts) == admission.meter.model_calls == 1
    assert admission.meter.external_requests == 0
    # A denied reservation is terminal local admission, not a provider error.
    from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected

    with pytest.raises(ExecutionAdmissionRejected, match="budget_exhausted"):
        await assemble(execution)
    assert len(attempts) == 1
    assert admission.meter.model_calls == 1
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["budget", "deadline_after_reservation", "authorization"])
async def test_expression_local_admission_denial_never_returns_provider_attempt(
    monkeypatch, failure,
):
    from ai_karen_engine.core.expression.contracts import ExpressionTask
    from ai_karen_engine.core.expression.errors import (
        ExecutionAdmissionRejected, ExecutionDeadlineExceeded,
    )
    from ai_karen_engine.core.expression.registry import get_engine

    admission = _scope(calls=0 if failure == "budget" else 1)
    _, _, attempts = _workflow_transport(monkeypatch, admission)
    engine = get_engine("local", "openai_compatible")
    if failure == "authorization":
        admission = replace(admission, tenant_id="foreign-tenant")

    reads = 0

    async def remaining():
        nonlocal reads
        reads += 1
        if failure == "deadline_after_reservation" and reads > 1:
            return 0
        return 60000

    task = ExpressionTask(
        task_id="local-admission", kind="chat",
        messages=[{"role": "user", "content": "test"}],
        response_mode="text", required_capabilities=[], forbidden_capabilities=[],
        preferred_provider="ollama-local", preferred_model="model-a",
        max_tokens=12, temperature=0.0,
        execution_admission=admission, remaining_execution_ms=remaining,
    )
    expected = {
        "budget": ExecutionAdmissionRejected,
        "deadline_after_reservation": ExecutionDeadlineExceeded,
        "authorization": PermissionError,
    }[failure]
    with pytest.raises(expected):
        await engine.generate(task)
    assert attempts == []
    assert admission.meter.model_calls == int(failure == "deadline_after_reservation")
    assert admission.meter.external_requests == 0


@pytest.mark.asyncio
async def test_workflow_local_budget_denial_does_not_penalize_engine_or_fallback(monkeypatch):
    from unittest.mock import Mock
    from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected
    from ai_karen_engine.core.runtime import composition
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope(calls=0)
    authority, request, attempts = _workflow_transport(
        monkeypatch, admission, retry_secondary=True,
    )
    gateway = composition.get_expression_gateway()
    failures = Mock(wraps=gateway.circuits.mark_failure)
    # CircuitBreakers is slotted; replace the instance with a wrapping spy.
    circuits = Mock(wraps=gateway.circuits)
    circuits.mark_failure = failures
    gateway.circuits = circuits
    with bind_workflow_generation(authority):
        with pytest.raises(ExecutionAdmissionRejected, match="budget_exhausted"):
            await WorkflowGenerationRuntime().execute(request)
    failures.assert_not_called()
    circuits.mark_success.assert_not_called()
    assert attempts == []
    assert admission.meter.model_calls == 0


@pytest.mark.asyncio
async def test_expression_admitted_deadline_discards_late_transport_result(monkeypatch):
    from ai_karen_engine.core.expression.contracts import ExpressionTask
    from ai_karen_engine.core.expression.engines import openai_compatible_engine as module
    from ai_karen_engine.core.expression.errors import ExecutionDeadlineExceeded
    from ai_karen_engine.core.expression.registry import get_engine

    admission = _scope(calls=1)
    _, _, attempts = _workflow_transport(monkeypatch, admission)
    entered = []

    async def late(endpoint, **kwargs):
        entered.append(endpoint.provider_id)
        admission.meter._start_ms -= 61000
        return ProviderExecutionResult(
            text="late result", model="model-a", provider_id=endpoint.provider_id,
            runtime_engine=endpoint.runtime_engine.value,
        )

    async def remaining():
        # Leave deadline enforcement to the actual admitted scope, not a
        # fabricated transport timeout.
        return 60000

    monkeypatch.setattr(module, "execute_provider_endpoint", late)
    task = ExpressionTask(
        task_id="late-result", kind="chat",
        messages=[{"role": "user", "content": "test"}],
        response_mode="text", required_capabilities=[], forbidden_capabilities=[],
        preferred_provider="ollama-local", preferred_model="model-a",
        max_tokens=12, temperature=0.0,
        execution_admission=admission, remaining_execution_ms=remaining,
    )
    with pytest.raises(ExecutionDeadlineExceeded, match="execution_deadline_exhausted"):
        await get_engine("local", "openai_compatible").generate(task)
    assert entered == ["ollama-local"]
    assert attempts == []
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
async def test_direct_governed_http_does_not_duplicate_transport_health(monkeypatch):
    from unittest.mock import Mock
    from ai_karen_engine.core.model_runtime import provider_health_monitor

    manager, attempts, endpoint = _local_manager(monkeypatch, shared_health=True)
    monitor = provider_health_monitor.ProviderHealthMonitor(
        registry=SimpleNamespace(get_provider_endpoint=lambda _: endpoint),
    )
    observations = Mock(wraps=monitor.update_provider_health)
    monkeypatch.setattr(monitor, "update_provider_health", observations)
    monkeypatch.setattr(provider_health_monitor, "get_health_monitor", lambda: monitor)
    caller_observations = Mock()
    monkeypatch.setattr(manager, "_record_provider_result", caller_observations)
    admission = _scope(calls=1)
    receipt = await manager.generate_chat(
        [{"role": "user", "content": "input"}],
        execution_admission=admission, return_receipt=True,
    )
    assert receipt.text == "actual observed output"
    assert len(attempts) == 1
    observations.assert_called_once()
    caller_observations.assert_not_called()
    assert admission.meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["generation", "embedding"])
@pytest.mark.parametrize("case", ["success", "preparation_denied", "execution_failure", "cancelled", "deadline", "retirement_unverified"])
async def test_direct_native_observation_uses_actual_library_call_and_owned_terminal(
    monkeypatch, operation, case,
):
    from unittest.mock import Mock
    from ai_karen_engine.core.model_runtime import provider_health_monitor
    from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
    from ai_karen_engine.core.model_runtime.provider_contracts import NativeRetirementUnverified
    from ai_karen_engine.core.model_runtime.providers import transformers_runtime as native
    from ai_karen_engine.core.model_runtime.runtime_engine import EndpointProtocol, RuntimeEngine
    from ai_karen_engine.platform.observability import metrics

    if operation == "embedding" and case == "retirement_unverified":
        pytest.skip("Encoder has no explicit native device-retirement contract")
    manager, _, endpoint = _local_manager(monkeypatch)
    endpoint = replace(
        endpoint, provider_id="builtin_transformers", base_url=None,
        builtin=True, tenant_scoped=False,
        endpoint_type=ProviderEndpointType.BUILTIN_TRANSFORMERS,
        protocol=EndpointProtocol.NATIVE, runtime_engine=RuntimeEngine.TRANSFORMERS,
    )
    monitor = provider_health_monitor.ProviderHealthMonitor(
        registry=SimpleNamespace(get_provider_endpoint=lambda _: endpoint),
    )
    health = Mock(wraps=monitor.update_provider_health)
    monkeypatch.setattr(monitor, "update_provider_health", health)
    monkeypatch.setattr(provider_health_monitor, "get_health_monitor", lambda: monitor)
    collector = metrics.MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)
    admission = _scope(calls=1)
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()
    calls = []

    def compute(*args, **kwargs):
        calls.append(operation)
        try:
            if case in {"cancelled", "deadline"}:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("worker test release deadline")
            if case == "execution_failure":
                raise ValueError("private error body")
            if operation == "embedding":
                return SimpleNamespace(tolist=lambda: [0.1, 0.2])
            return [{"generated_text": "Actual model output"}]
        finally:
            retired.set()

    if operation == "generation":
        selection = RuntimeSelection(
            provider_id=endpoint.provider_id, display_name=endpoint.display_name,
            endpoint_type=endpoint.endpoint_type, model=endpoint.default_model,
            runtime_engine=endpoint.runtime_engine.value, base_url=None,
        )
        class Pipeline:
            device = SimpleNamespace(type="cpu")
            tokenizer = SimpleNamespace(eos_token_id=1)

            def __call__(self, *args, **kwargs):
                return compute(*args, **kwargs)

        provider = object.__new__(native.TransformersRuntime)
        provider._pipeline = Pipeline()
        provider.model_path = endpoint.default_model
        provider._transformers_available = True
        provider._generation_lock = threading.RLock()
        monkeypatch.setattr(provider, "warm", lambda *a, **kw: case != "preparation_denied")
        monkeypatch.setattr(native, "generation_checkpoint_options", lambda _: {})
        monkeypatch.setattr(native.TransformersRuntime, "_native_retirement_hold", threading.Event())
        if case == "retirement_unverified":
            def fail_retirement(_device):
                raise RuntimeError("unverified device fence")
            monkeypatch.setattr(provider, "_synchronize_native_device", fail_retirement)
        monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
        monkeypatch.setattr(manager, "_resolve_endpoint", lambda _: endpoint)
        monkeypatch.setattr(manager, "resolve_runtime", lambda _: provider)
        invoke = manager.generate_chat(
            [{"role": "user", "content": "input"}],
            return_receipt=True, execution_admission=admission,
        )
    else:
        encoder = EmbeddingManager(model_name="local-embedding-model")
        encoder.model = SimpleNamespace(encode=compute)
        encoder.model_loaded = case != "preparation_denied"
        manager.embedding_manager = encoder
        invoke = manager.generate_embedding("input", execution_admission=admission)

    task = asyncio.create_task(invoke)
    if case in {"cancelled", "deadline"}:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            if case == "cancelled":
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert not retired.is_set()
            else:
                admission.meter._start_ms -= 61000
            assert "kari_native_execution_observations_total" not in collector.snapshot()["counters"]
        finally:
            release.set()
    if case == "success":
        result = await asyncio.wait_for(task, timeout=3)
        assert result == [0.1, 0.2] if operation == "embedding" else result.text == "Actual model output"
    elif case == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
    elif case == "retirement_unverified":
        with pytest.raises(NativeRetirementUnverified):
            await asyncio.wait_for(task, timeout=3)
    else:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, timeout=3)

    counters = collector.snapshot()["counters"]
    if case == "preparation_denied":
        assert calls == []
        assert "kari_native_execution_observations_total" not in counters
    else:
        assert calls == [operation]
        assert retired.is_set()
        expected = {
            "success": "success", "cancelled": "cancelled", "deadline": "deadline_exceeded",
            "execution_failure": "execution_failed", "retirement_unverified": "retirement_unverified",
        }[case]
        assert counters["kari_native_execution_observations_total"]["values"] == {(operation, expected): 1.0}
    assert health.call_count == int(operation == "generation" and case == "success")


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["success", "budget", "cancelled", "deadline", "retirement"])
async def test_native_sequence_observation_waits_for_owner_and_excludes_preparation(
    monkeypatch, terminal,
):
    from ai_karen_engine.core.model_runtime import provider_health_monitor as health
    from ai_karen_engine.core.model_runtime.provider_contracts import NativeRetirementUnverified
    from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS
    from ai_karen_engine.platform.observability import metrics

    endpoint = next(item for item in BUILTIN_PROVIDER_ENDPOINTS
                    if item.provider_id == "builtin_transformers")
    admission = _scope(calls=4)
    monitor = health.ProviderHealthMonitor()
    monkeypatch.setattr(health, "get_health_monitor", lambda: monitor)
    collector = metrics.MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)
    sequence = health.NativeExecutionSequence()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()
    loop = asyncio.get_running_loop()

    def worker(checkpoint, reserve):
        # Preparation and even a reserved scope without a library call
        # cannot emit inference evidence.
        with sequence.attempt():
            checkpoint()
        reserve()
        with sequence.attempt():
            checkpoint()
        reserve()
        with sequence.attempt():
            with health.observe_native_compute("soft_reference"):
                pass
        reserve()
        with sequence.attempt():
            with health.observe_native_compute("soft_guided"):
                pass
        reserve()
        with sequence.attempt():
            try:
                with health.observe_native_compute("generation"):
                    if terminal in {"cancelled", "deadline", "retirement"}:
                        loop.call_soon_threadsafe(entered.set)
                        if not release.wait(5):
                            raise RuntimeError("test worker release deadline")
                        if terminal != "retirement":
                            checkpoint()
                if terminal == "retirement":
                    raise NativeRetirementUnverified()
            finally:
                retired.set()
        if terminal == "budget":
            reserve()
        return "trace"

    async def invoke():
        try:
            result = await admission.run_native_attempt_sequence(
                endpoint, model="model-a", function=worker,
            )
        except (Exception, asyncio.CancelledError) as exc:
            sequence.finish(exc)
            raise
        sequence.finish()
        return result

    task = asyncio.create_task(invoke())
    if terminal in {"cancelled", "deadline", "retirement"}:
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert "kari_native_execution_observations_total" not in collector.snapshot()["counters"]
            if terminal in {"cancelled", "retirement"}:
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert not retired.is_set()
            else:
                admission.meter._start_ms -= 61000
        finally:
            release.set()
    if terminal == "success":
        assert await asyncio.wait_for(task, timeout=3) == "trace"
    elif terminal == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
    elif terminal == "retirement":
        with pytest.raises(NativeRetirementUnverified):
            await asyncio.wait_for(task, timeout=3)
    else:
        with pytest.raises(RuntimeError, match="budget_exhausted|deadline_exhausted"):
            await asyncio.wait_for(task, timeout=3)

    sequence.finish()  # duplicate finalization must not emit again
    assert retired.is_set()
    assert admission.meter.model_calls == 4
    observed = collector.snapshot()["counters"]["kari_native_execution_observations_total"]["values"]
    completed = "success" if terminal == "success" else "sequence_aborted"
    last = {"success": "success", "budget": "sequence_aborted",
            "cancelled": "cancelled", "deadline": "sequence_aborted",
            "retirement": "retirement_unverified"}[terminal]
    assert observed == {
        ("soft_reference", completed): 1.0,
        ("soft_guided", completed): 1.0,
        ("soft_verifier", last): 1.0,
    }
    assert monitor.get_provider_health(endpoint.provider_id).health_status is health.HealthStatus.UNKNOWN


def test_native_sequence_never_certifies_multiple_computes_in_one_reserved_scope(monkeypatch):
    from ai_karen_engine.core.model_runtime import provider_health_monitor as health
    from ai_karen_engine.platform.observability import metrics

    monitor = health.ProviderHealthMonitor()
    monkeypatch.setattr(health, "get_health_monitor", lambda: monitor)
    collector = metrics.MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)
    sequence = health.NativeExecutionSequence()
    with sequence.attempt():
        with health.observe_native_compute("soft_guided"):
            pass
        with health.observe_native_compute("generation"):
            pass
    sequence.finish()
    assert collector.snapshot()["counters"]["kari_native_execution_observations_total"]["values"] == {
        ("soft_guided", "unverified_result"): 1.0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("requirements,ceiling", [
    (None, 10),
    ([], 5),
    (["first", "second"], 7),
    (["tool-" + str(index) for index in range(8)], 13),
])
@pytest.mark.parametrize("narrow", [False, True])
async def test_initial_tool_budget_is_bounded_by_real_issuer(requirements, ceiling, narrow):
    issuer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="tool-quota-user",
        tenant_id="tool-quota-tenant",
        session_id="tool-quota-session",
        correlation_id=f"tool-quota-{uuid4().hex}",
        max_model_calls=0,
        execution_topology=(
            {} if requirements is None else {"tool_requirements": requirements}
        ),
    )
    decision = await issuer.evaluate(request)
    assert decision.allowed
    assert decision.runtime_constraints["max_tool_calls"] == ceiling
    context = ChatExecutionContext(
        user_id=request.user_id, tenant_id=request.tenant_id,
        session_id=request.session_id, correlation_id=request.correlation_id,
        request_id=f"tool-quota-request-{uuid4().hex}",
        authenticated_user=UserData(
            user_id=request.user_id, tenant_id=request.tenant_id,
            roles=["user"], permissions=[], is_active=True, is_verified=True,
        ),
    )
    issuer.bind_chat_model_policy(context=context, decision=decision)
    original = decision.to_authorized_plan()
    assert original.budget.max_tool_calls == ceiling
    for widened in (ceiling + 1, -1, True):
        budget = replace(original.budget, max_tool_calls=widened)
        plan = replace(original, budget=budget)
        meter = ExecutionBudgetMeter(budget)
        with pytest.raises(PermissionError, match="runtime_model_execution_authority_invalid"):
            context.bind_runtime_model_authority(plan, meter)
        assert context.original_runtime_model_plan(meter) is None
        assert meter.tool_calls == 0

    # Altering the issuer's decision after issuance is not a grant.
    decision.runtime_constraints["max_tool_calls"] = ceiling + 1
    assert not issuer.verifies_chat_model_policy(context=context, plan=original)
    decision.runtime_constraints["max_tool_calls"] = ceiling

    limit = 1 if narrow else ceiling
    plan = replace(original, budget=replace(original.budget, max_tool_calls=limit))
    meter = ExecutionBudgetMeter(plan.budget)
    context.bind_runtime_model_authority(plan, meter)
    assert context.original_runtime_model_plan(meter) is plan
    fresh_meter = ExecutionBudgetMeter(plan.budget)
    with pytest.raises(PermissionError, match="runtime_model_execution_authority_invalid"):
        context.bind_runtime_model_authority(plan, fresh_meter)
    assert context.original_runtime_model_plan(fresh_meter) is None
    plan.budget.max_tool_calls = limit + 1
    assert context.original_runtime_model_plan(meter) is None
    plan.budget.max_tool_calls = limit
    assert context.original_runtime_model_plan(meter) is plan
    results = await asyncio.gather(*(meter.consume_tool_call() for _ in range(limit + 3)))
    assert sum(results) == limit
    assert meter.tool_calls == limit
