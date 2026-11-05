"""Live observation model synthesis has explicit, validated central budgets."""

from ai_karen_engine.config.runtime import RuntimeSettings


def test_short_observation_default_does_not_inherit_long_chat_budget():
    settings = RuntimeSettings()
    assert settings.llm.observation_synthesis_max_output_tokens > 0
    assert (
        settings.llm.observation_synthesis_max_output_tokens
        < settings.llm.chat_default_max_output_tokens
    )
    assert 500 <= settings.llm.observation_synthesis_timeout_ms <= 30000
    assert not any("observation_synthesis" in item for item in settings.validate())


def test_invalid_observation_limits_fail_canonical_runtime_validation():
    settings = RuntimeSettings()
    settings.llm.observation_synthesis_max_output_tokens = 0
    settings.llm.observation_synthesis_timeout_ms = 0
    errors = settings.validate()
    assert any("observation_synthesis_max_output_tokens" in error for error in errors)
    assert any("observation_synthesis_timeout_ms" in error for error in errors)


def test_excessive_observation_budget_also_fails_validation():
    settings = RuntimeSettings()
    settings.llm.observation_synthesis_max_output_tokens = 1536
    settings.llm.observation_synthesis_timeout_ms = 60000
    errors = settings.validate()
    assert any("observation_synthesis_max_output_tokens" in error for error in errors)
    assert any("observation_synthesis_timeout_ms" in error for error in errors)
