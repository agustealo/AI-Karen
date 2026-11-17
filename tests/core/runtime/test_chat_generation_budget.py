"""Direct-chat generation limits are not prompt-context token budgets."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.config.runtime import LLMSettings, RuntimeSettings
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
)


def _resolve(monkeypatch, *, requested=None, default=512, maximum=2048, authorized=4096):
    monkeypatch.setattr(
        "ai_karen_engine.config.runtime.get_runtime_settings",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                chat_default_max_output_tokens=default,
                max_tokens=maximum,
            )
        ),
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "in detroit"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1"
        ),
        max_tokens=requested,
    )
    plan = AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="decision-1",
        budget=ExecutionBudget(max_output_tokens=authorized),
    )
    return ChatRuntime._resolve_chat_generation_max_tokens(request, plan)


def test_direct_chat_without_client_limit_uses_config_not_prompt_budget(monkeypatch):
    assert _resolve(monkeypatch) == 512


def test_explicit_client_limit_can_increase_generation_within_authority(monkeypatch):
    assert _resolve(monkeypatch, requested=1024) == 1024


def test_client_limit_cannot_exceed_provider_or_authorized_budget(monkeypatch):
    assert _resolve(monkeypatch, requested=9000, maximum=2048) == 2048
    assert _resolve(monkeypatch, requested=9000, authorized=384) == 384
    assert _resolve(monkeypatch, default=512, authorized=256) == 256


@pytest.mark.parametrize("requested", [0, -5, True, "4096"])
def test_invalid_client_generation_limit_fails_closed(monkeypatch, requested):
    with pytest.raises(ValueError, match="positive integer"):
        _resolve(monkeypatch, requested=requested)


def test_disabled_generation_budget_fails_closed(monkeypatch):
    with pytest.raises(ValueError, match="disabled"):
        _resolve(monkeypatch, maximum=0)


def test_chat_default_is_validated_in_canonical_runtime_config():
    settings = RuntimeSettings()
    settings.llm.chat_default_max_output_tokens = 0
    assert any(
        "chat_default_max_output_tokens" in issue
        for issue in settings.validate()
    )


def test_chat_generation_default_is_distinct_from_global_provider_limit():
    llm = LLMSettings()
    assert 0 < llm.chat_default_max_output_tokens < llm.max_tokens


def test_config_default_is_clamped_when_provider_limit_is_lower(monkeypatch):
    assert _resolve(monkeypatch, default=512, maximum=128) == 128


def test_environment_can_override_direct_chat_default(monkeypatch):
    monkeypatch.setenv("KARI_CHAT_DEFAULT_MAX_OUTPUT_TOKENS", "384")
    settings = RuntimeSettings()
    settings.apply_env_overrides()
    assert settings.llm.chat_default_max_output_tokens == 384


@pytest.mark.asyncio
async def test_direct_chat_gateway_receives_authorized_completion_budget(monkeypatch):
    """Exercise the real direct-chat task constructor, not only its helper."""
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    monkeypatch.setattr(
        "ai_karen_engine.config.runtime.get_runtime_settings",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(chat_default_max_output_tokens=512, max_tokens=2048)
        ),
    )
    gateway = SimpleNamespace(
        generate=AsyncMock(return_value=SimpleNamespace(
            provider="ollama-local",
            model="local-model",
            text="Detroit",
            response_source="model",
            runtime_engine="ollama",
            engine_id="ollama",
            metadata={"fallback_level": 0, "usage": {}},
            degraded=False,
            degradation_reason=None,
            attempts=[],
            latency_ms=10.0,
        ))
    )
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._composition = SimpleNamespace(expression_gateway=gateway)
    runtime._emitter = SimpleNamespace(emit=lambda *args, **kwargs: None)
    runtime._assemble_prompt_with_telemetry = AsyncMock(return_value=(
        [{"role": "user", "content": "in detroit"}],
        {"assembly_duration_ms": 0.0},
    ))
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "in detroit"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1"
        ),
    )
    decision = ExecutionDecision(token_budget=4096)
    plan = AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="decision-1",
        budget=ExecutionBudget(max_output_tokens=384),
    )
    meter = SimpleNamespace(
        consume_model_call=AsyncMock(return_value=True),
        check_duration=AsyncMock(return_value=True),
    )

    answer, metadata = await runtime._run_simple(request, decision, plan, meter)

    assert answer == "Detroit"
    assert metadata["actual_model"] == "local-model"
    gateway.generate.assert_awaited_once()
    assert gateway.generate.await_args.args[0].max_tokens == 384
    assert gateway.generate.await_args.args[0].reserve_additional_model_call is meter.consume_model_call
    assert callable(gateway.generate.await_args.args[0].authorize_external_engine_attempt)


@pytest.mark.asyncio
async def test_grounded_search_synthesis_receives_authorized_plan(monkeypatch):
    """Fetched-page synthesis must not raise NameError or bypass the cap."""
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    monkeypatch.setattr(
        "ai_karen_engine.config.runtime.get_runtime_settings",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(chat_default_max_output_tokens=512, max_tokens=2048)
        ),
    )
    monkeypatch.setattr(
        "ai_karen_engine.services.response.response_prompt_builder.ResponsePromptBuilder.build_messages",
        lambda self, contract: [{"role": "user", "content": "Summarize the evidence"}],
    )
    gateway = SimpleNamespace(
        generate=AsyncMock(return_value=SimpleNamespace(
            provider="ollama-local",
            model="local-model",
            text="Source summary",
            degraded=False,
            runtime_engine="ollama",
            engine_id="ollama",
            degradation_reason=None,
        ))
    )
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._composition = SimpleNamespace(expression_gateway=gateway)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "latest news in Detroit"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1"
        ),
    )
    decision = ExecutionDecision(intent="search.general", token_budget=4096)
    plan = AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="decision-1",
        budget=ExecutionBudget(max_output_tokens=256),
        allowed_plugins=["search.plugin"],
    )
    meter = SimpleNamespace(
        consume_model_call=AsyncMock(return_value=True),
        check_duration=AsyncMock(return_value=True),
    )
    retrieved = SimpleNamespace(
        success=True,
        degraded=False,
        source="plugin",
        source_id="search.plugin",
        attempts=[{"id": "search.plugin", "type": "plugin", "status": "success"}],
        payload={},
        sources=[{
        "url": "https://example.org/detroit",
        "evidence_level": "fetched_page",
        "content": "Grounded source evidence",
    }],
    )

    await runtime._synthesize_search_evidence(
        request, decision, plan, meter, retrieved
    )

    gateway.generate.assert_awaited_once()
    assert gateway.generate.await_args.args[0].max_tokens == 256
    assert gateway.generate.await_args.args[0].reserve_additional_model_call is meter.consume_model_call
    assert callable(gateway.generate.await_args.args[0].authorize_external_engine_attempt)

    # Invalid or cross-plan result receipts may carry realistic inline source
    # text, but must never trigger the model or spend another model call.
    for invalid in (
        {"success": False},
        {"success": 1},
        {"degraded": True},
        {"source": "manual"},
        {"source": "tool"},
        {"source_id": "not-authorized"},
        {"attempts": []},
        {"attempts": [{"id": "search.plugin", "type": "plugin", "status": "failed"}]},
        {"attempts": [{"id": "search.plugin", "type": "tool", "status": "success"}]},
    ):
        gateway.generate.reset_mock()
        meter.consume_model_call.reset_mock()
        untrusted = SimpleNamespace(**{**vars(retrieved), **invalid})
        assert await runtime._synthesize_search_evidence(
            request, decision, plan, meter, untrusted
        ) is None
        gateway.generate.assert_not_awaited()
        meter.consume_model_call.assert_not_awaited()

    # A separately admitted tool result is equally valid source evidence.
    plan.allowed_tools = ["search.tool"]
    tool_result = SimpleNamespace(**{
        **vars(retrieved),
        "source": "tool",
        "source_id": "search.tool",
        "attempts": [{"id": "search.tool", "type": "tool", "status": "success"}],
    })
    gateway.generate.reset_mock()
    await runtime._synthesize_search_evidence(
        request, decision, plan, meter, tool_result
    )
    gateway.generate.assert_awaited_once()
