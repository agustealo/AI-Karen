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
