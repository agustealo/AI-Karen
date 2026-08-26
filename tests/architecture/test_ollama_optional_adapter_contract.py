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


def test_ollama_is_an_optional_integration_not_core_runtime() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8")

    assert 'self.enabled = _env_flag("KARI_OLLAMA_ENABLED", False)' in source
    assert "Ollama is an integration, not a core runtime dependency" in source
    assert "_require_enabled" in source
    assert '"status": "disabled"' in source


def test_disabled_ollama_cannot_reach_network() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8")

    request_body = source.split("def _request", 1)[1].split("def _record_usage", 1)[0]
    assert "self._require_enabled()" in request_body

    model_body = source.split("def get_models", 1)[1].split("def get_provider_info", 1)[0]
    assert "self._require_enabled()" in model_body


def test_ollama_does_not_own_runtime_authorities() -> None:
    source = OLLAMA_PROVIDER.read_text(encoding="utf-8").lower()

    forbidden = (
        "chatruntime",
        "promptassembler",
        "neurorecall",
        "agentmedusa",
        "actionexecutiongate",
        "providerregistry(",
        "fallback_order",
    )
    for token in forbidden:
        assert token not in source


def test_compose_ollama_service_remains_profile_gated() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    ollama_block = source.split("\n  ollama:\n", 1)[1].split("\n  # ─", 1)[0]

    assert "profiles:" in ollama_block
    assert "- ollama" in ollama_block


def test_known_legacy_defaults_are_explicitly_bounded_for_followup() -> None:
    """Pin the two remaining configuration leaks until config convergence removes them.

    Runtime safety does not rely on these defaults because the adapter now fails
    closed unless KARI_OLLAMA_ENABLED=true. This test makes the debt visible so
    a future provider-config rewrite cannot accidentally treat it as canonical.
    """

    config = PROVIDER_CONFIG.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert 'name="ollama"' in config
    assert "DEFAULT_OLLAMA_BASE_URL" in config
    assert 'OLLAMA_BASE_URL: "${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"' in compose
