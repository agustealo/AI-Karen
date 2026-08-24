"""Tests for the central runtime configuration authority."""

from __future__ import annotations

import os

import pytest

from ai_karen_engine.config.runtime import (
    Environment,
    FeatureFlags,
    LLMSettings,
    ProviderFlags,
    RuntimeEngine,
    RuntimeSettings,
    ServiceEndpoints,
    TimeoutSettings,
    get_runtime_settings,
    reload_runtime_settings,
    validate_runtime_settings,
    validate_runtime_settings_startup,
)


def test_runtime_settings_defaults():
    settings = RuntimeSettings()
    assert settings.environment == Environment.LOCAL
    assert settings.debug is False
    assert settings.llm.default_provider == "builtin_transformers"
    assert settings.llm.default_model == "auto"
    assert settings.endpoints.database_url == "postgresql://postgres:postgres@localhost:54322/postgres"
    assert settings.endpoints.redis_url == "redis://localhost:6379/0"
    assert settings.endpoints.vllm_base_url == "http://vllm:8000/v1"
    assert settings.endpoints.ollama_base_url == "http://localhost:11434"
    assert settings.timeouts.request_timeout == 30
    assert settings.features.enable_agent_mode is True


def test_apply_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KARI_ENVIRONMENT", "production")
    monkeypatch.setenv("KARI_DEBUG_MODE", "true")
    monkeypatch.setenv("KARI_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("KARI_DEFAULT_MODEL", "gpt-4o")
    monkeypatch.setenv("KARI_FALLBACK_CHAIN", "openai,gemini,fallback")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db:5432/karen")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/1")
    monkeypatch.setenv("KARI_VLLM_BASE_URL", "http://vllm-prod:8000/v1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai-proxy.example.com/v1")
    monkeypatch.setenv("KARI_ENABLE_AGENT_MODE", "false")
    monkeypatch.setenv("KARI_ENABLE_STREAMING", "0")
    monkeypatch.setenv("KARI_LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("KARI_LLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("KARI_LLM_TIMEOUT", "60")
    monkeypatch.setenv("KARI_LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("KARI_REQUEST_TIMEOUT", "45")
    monkeypatch.setenv("KARI_ENABLED_PROVIDERS", "openai,gemini")
    monkeypatch.setenv("KARI_DISABLED_PROVIDERS", "huggingface")

    settings = RuntimeSettings()
    settings.apply_env_overrides()

    assert settings.environment == Environment.PRODUCTION
    assert settings.debug is True
    assert settings.llm.default_provider == "openai"
    assert settings.llm.default_model == "gpt-4o"
    assert settings.llm.fallback_chain == ["openai", "gemini", "fallback"]
    assert settings.endpoints.database_url == "postgresql://db:5432/karen"
    assert settings.endpoints.redis_url == "redis://redis:6379/1"
    assert settings.endpoints.vllm_base_url == "http://vllm-prod:8000/v1"
    assert settings.endpoints.ollama_base_url == "http://ollama:11434"
    assert settings.endpoints.openai_base_url == "https://openai-proxy.example.com/v1"
    assert settings.features.enable_agent_mode is False
    assert settings.features.enable_streaming is False
    assert settings.llm.temperature == 0.2
    assert settings.llm.max_tokens == 1024
    assert settings.llm.timeout == 60
    assert settings.llm.max_retries == 5
    assert settings.timeouts.request_timeout == 45
    assert settings.providers.enabled_providers == ["openai", "gemini"]
    assert settings.providers.disabled_providers == ["huggingface"]


def test_validate_runtime_settings_ok():
    settings = RuntimeSettings()
    settings.llm.fallback_chain = ["openai", "fallback"]
    issues = validate_runtime_settings(settings)
    assert issues == []


def test_validate_runtime_settings_errors():
    settings = RuntimeSettings()
    settings.llm.default_provider = ""
    settings.llm.fallback_chain = []
    settings.llm.temperature = 5.0
    settings.llm.max_tokens = 0
    settings.llm.timeout = 0
    settings.llm.max_retries = -1
    settings.environment = Environment.PRODUCTION
    settings.debug = True

    issues = validate_runtime_settings(settings)
    assert "LLM default_provider must not be empty" in issues
    assert "LLM fallback_chain must not be empty" in issues
    assert "LLM temperature 5.0 is out of range [0, 2]" in issues
    assert "LLM max_tokens must be positive" in issues
    assert "LLM timeout must be positive" in issues
    assert "LLM max_retries must not be negative" in issues
    assert any("localhost in production" in issue for issue in issues)
    assert any("Debug mode should not be enabled in production" in issue for issue in issues)


def test_validate_runtime_settings_startup_raises():
    settings = RuntimeSettings()
    settings.llm.default_provider = ""
    with pytest.raises(RuntimeError):
        validate_runtime_settings_startup(settings)


def test_get_runtime_settings_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KARI_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("KARI_DEBUG_MODE", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)

    reload_runtime_settings()
    a = get_runtime_settings()
    b = get_runtime_settings()
    assert a is b


def test_reload_runtime_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KARI_DEBUG_MODE", "true")
    settings = reload_runtime_settings()
    assert settings.debug is True

    monkeypatch.delenv("KARI_DEBUG_MODE", raising=False)
    reloaded = reload_runtime_settings()
    assert reloaded.debug is False
