"""KCHAT-AUTH-05B2A: one original admission and budget across Core façades.

No HTTP requests, downloaded models or synthetic model receipts are used.
The real principal, authorization scope and shared meter are evaluated before
the model runtime or compatibility transport can be invoked.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

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
from ai_karen_engine.core.model_runtime.openai_compatible_client import (
    OpenAICompatibleRuntimeClient,
)
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
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
)


def _scope(*, calls: int = 2, tenant: str = "tenant-a") -> GovernedToolModelAdmission:
    budget = ExecutionBudget(
        max_model_calls=calls,
        max_external_requests=1,
        max_duration_ms=60000,
    )
    plan = AuthorizedExecutionPlan(
        execution_id="execution-a",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id=tenant,
        authorized_session_id="session-a",
        budget=budget,
    )
    meter = ExecutionBudgetMeter(budget)
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
        runtime_engine="ollama",
    )
    client = OpenAICompatibleRuntimeClient(
        model=observed_model,
        base_url=endpoint.base_url,
        provider_name="ollama-local",
    )
    attempts = []

    def generate_text_with_model(prompt, **kwargs):
        attempts.append(prompt)
        return ("actual observed output", observed_model)

    monkeypatch.setattr(client, "generate_text_with_model", generate_text_with_model)
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "_resolve_endpoint", lambda _: endpoint)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: client)
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
    scope = _scope()
    scope.plan.provider_constraints["eligible_providers"] = ["other-provider"]
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
    scope = _scope()
    scope.plan.provider_constraints.update(restriction)
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
    scope = _scope()
    scope.plan.provider_constraints.update(restriction)
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
    scope = _scope()
    scope.plan.provider_constraints.update(constraints)
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
