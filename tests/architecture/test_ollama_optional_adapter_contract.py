from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OLLAMA_PROVIDER = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "integrations"
    / "providers"
    / "ollama_provider.py"
)
PROVIDER_CONFIG = (
    REPO_ROOT / "src" / "ai_karen_engine" / "config" / "llm_provider_config.py"
)
COMPOSE = REPO_ROOT / "docker-compose.yml"


def test_ollama_is_a_third_party_adapter_not_runtime_authority() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8")

    assert "Ollama is a third-party provider integration" in source
    assert "KARI_OLLAMA_ENABLED" not in source
    assert "DEFAULT_OLLAMA_BASE_URL" not in source
    assert "host.docker.internal" not in source
    assert "localhost:11434" not in source
    assert 'self.provider_name = "ollama"' in source


def test_ollama_requires_provider_configuration_instead_of_inventing_it() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8")

    assert 'base_url or os.getenv("OLLAMA_BASE_URL") or ""' in source
    assert "Ollama provider has no configured base URL" in source


def test_ollama_does_not_own_system_authorities() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8").lower()

    forbidden = (
        "chatruntime",
        "promptassembler",
        "neurorecall",
        "agentmedusa",
        "actionexecutiongate",
        "providerregistry(",
        "fallback_order",
        "reasoningdepth",
        "cortex",
    )
    for token in forbidden:
        assert token not in source


def test_remaining_legacy_special_cases_are_visible_until_provider_convergence() -> None:
    """Pin stale system-level Ollama treatment so it cannot be mistaken as canonical."""

    config = PROVIDER_CONFIG.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "DEFAULT_OLLAMA_BASE_URL" in config
    assert 'provider_type=ProviderType.LOCAL' in config
    assert 'default_model="deepseek-r1:1.5b"' in config
    assert 'OLLAMA_BASE_URL: "${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"' in compose
