from __future__ import annotations

import pytest

from ai_karen_engine.config.cognitive.loader import (
    CognitiveConfigValidationError,
    get_cognitive_config,
    reload_cognitive_config,
)


@pytest.fixture(autouse=True)
def _clear_cognitive_cache():
    from ai_karen_engine.config.cognitive import loader
    loader._cached_config = None
    yield
    loader._cached_config = None


def test_env_override_meta_weak_memory_threshold(monkeypatch):
    monkeypatch.setenv("KAREN_COG_META_WEAK_MEMORY_THRESHOLD", "0.5")
    config = get_cognitive_config()
    assert config.meta.weak_memory_threshold == 0.5


def test_env_override_meta_loop_repeat_threshold(monkeypatch):
    monkeypatch.setenv("KAREN_COG_META_LOOP_REPEAT_THRESHOLD", "5")
    config = get_cognitive_config()
    assert config.meta.loop_repeat_threshold == 5


def test_env_override_context_max_items(monkeypatch):
    monkeypatch.setenv("KAREN_COG_CONTEXT_MAX_ITEMS", "50")
    config = get_cognitive_config()
    assert config.context.max_items == 50


def test_env_override_context_max_tokens(monkeypatch):
    monkeypatch.setenv("KAREN_COG_CONTEXT_MAX_TOKENS", "8192")
    config = get_cognitive_config()
    assert config.context.max_tokens == 8192


def test_env_override_behavior_risk_weight(monkeypatch):
    monkeypatch.setenv("KAREN_COG_BEHAVIOR_RISK_WEIGHT", "2.5")
    config = get_cognitive_config()
    assert config.behavior.risk_penalty_weight == 2.5


def test_env_override_salience_decay_rate(monkeypatch):
    monkeypatch.setenv("KAREN_COG_SALIENCE_DECAY_RATE", "0.05")
    config = get_cognitive_config()
    assert config.salience.default_decay_rate == 0.05


def test_env_override_learning_min_samples(monkeypatch):
    monkeypatch.setenv("KAREN_COG_LEARNING_MIN_SAMPLES", "200")
    config = get_cognitive_config()
    assert config.learning.min_samples == 200


def test_env_override_memory_decay_lambda(monkeypatch):
    monkeypatch.setenv("KAREN_COG_MEMORY_DEFAULT_DECAY_LAMBDA", "0.2")
    config = get_cognitive_config()
    assert config.memory.default_decay_lambda == 0.2


def test_env_override_belief_staleness(monkeypatch):
    monkeypatch.setenv("KAREN_COG_BELIEF_STALENESS_THRESHOLD_HOURS", "48")
    config = get_cognitive_config()
    assert config.belief.staleness_threshold_hours == 48.0


def test_env_override_invalid_value(monkeypatch):
    monkeypatch.setenv("KAREN_COG_CONTEXT_MAX_ITEMS", "not_an_int")
    with pytest.raises(CognitiveConfigValidationError):
        get_cognitive_config()


def test_env_override_boolean(monkeypatch):
    monkeypatch.setenv("KAREN_COG_META_ENABLE_ADAPTIVE_THRESHOLDS", "false")
    config = get_cognitive_config()
    assert config.meta.enable_adaptive_thresholds is False


def test_reload_picks_up_new_env(monkeypatch):
    monkeypatch.setenv("KAREN_COG_BEHAVIOR_INTERRUPTION_PENALTY_WEIGHT", "3.0")
    config1 = get_cognitive_config()
    assert config1.behavior.interruption_penalty_weight == 3.0
    monkeypatch.delenv("KAREN_COG_BEHAVIOR_INTERRUPTION_PENALTY_WEIGHT")
    config2 = reload_cognitive_config()
    assert config2.behavior.interruption_penalty_weight == 1.0
