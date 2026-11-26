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
)


def _scope(
    *, calls: int = 2, tenant: str = "tenant-a",
    provider_constraints: dict | None = None,
    meter_model_calls: int | None = None,
    max_duration_ms: int = 60000,
    degraded_allowed: bool = True,
) -> GovernedToolModelAdmission:
    budget = ExecutionBudget(
        max_model_calls=calls,
        max_external_requests=1,
        max_duration_ms=max_duration_ms,
    )
    plan = AuthorizedExecutionPlan(
        execution_id=f"execution-{uuid4().hex}",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id=tenant,
        authorized_session_id="session-a",
        provider_constraints=dict(provider_constraints or {}),
        budget=budget,
        degraded_allowed=degraded_allowed,
    )
    if meter_model_calls is not None:
        budget.max_model_calls = meter_model_calls
    meter = ExecutionBudgetMeter(budget)
    budget.max_model_calls = calls
    principal = UserData(
        user_id="user-a",
        tenant_id=tenant,
        roles=["user"],
        permissions=[],
        is_active=True,
        is_verified=True,
    )
    context = ChatExecutionContext(
        user_id="user-a",
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
        user_id="user-a",
        tenant_id=tenant,
        session_id="session-a",
        policy_decision_id="policy-a",
        request_id="request-a",
        correlation_id="correlation-a",
        authenticated_context=context,
    )


def _local_manager(monkeypatch, *, observed_model: str | None = "model-a"):
    from ai_karen_engine.core.model_runtime import model_manager as manager_module
    from ai_karen_engine.core.model_runtime import llm_adapter as adapter_module

    manager = object.__new__(ModelManager)
    endpoint = ProviderEndpoint(
        provider_id="ollama-local",
        display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:11434/v1",
        default_model=observed_model,
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
    from ai_karen_engine.core.runtime.workflow_generation import (
        WorkflowGenerationAuthority, WorkflowGenerationRequest,
        WorkflowGenerationRuntime, bind_workflow_generation,
    )

    admission = _scope()
    authority = WorkflowGenerationAuthority.create(
        ChatExecutionRequest(context=admission.authenticated_context,
                             messages=[{"role": "user", "content": "task"}]),
        SimpleNamespace(), admission.plan, admission.meter,
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
                        preferred_provider="ollama-local", disable_primary=False):
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
    registry = SimpleNamespace(
        get_provider_endpoint=lambda provider_id: (
            endpoint if provider_id == endpoint.provider_id else None
        ),
        get_provider_status=lambda _: SimpleNamespace(is_available=available),
        resolve_capable_targets=lambda **_: [endpoint],
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
