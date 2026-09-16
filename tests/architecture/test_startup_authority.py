from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_STARTUP = REPO_ROOT / "server" / "startup.py"
SERVER_APP = REPO_ROOT / "server" / "app.py"
CANONICAL_STARTUP = (
    REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
)
CANONICAL_CONFIG = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "config.py"


def test_root_server_startup_authority_is_retired() -> None:
    assert not LEGACY_STARTUP.exists()


def test_transitional_app_uses_canonical_lifespan_directly() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    assert "from ai_karen_engine.server.startup import create_lifespan" in source
    assert "register_startup_tasks" not in source
    assert "register_shutdown_tasks" not in source
    assert "from .startup" not in source


def test_transitional_app_does_not_own_provider_or_memory_startup_policy() -> None:
    source = SERVER_APP.read_text(encoding="utf-8").lower()

    forbidden = (
        "kari_warm_local_llm_on_startup",
        "builtin_vllm",
        "builtin_transformers",
        "get_settings_manager",
        "initialize_services()",
        "memory_runtime_manager",
        "initialize_extension_service_recovery_manager",
        "force_recovery(",
    )
    for token in forbidden:
        assert token not in source


def test_canonical_lifespan_owner_exists() -> None:
    source = CANONICAL_STARTUP.read_text(encoding="utf-8")

    assert "create_lifespan" in source


def test_model_registry_refresh_is_opt_in() -> None:
    startup = CANONICAL_STARTUP.read_text(encoding="utf-8")
    config = CANONICAL_CONFIG.read_text(encoding="utf-8")

    assert 'llm_refresh_interval: int = Field(default=0, validation_alias="KARI_LLM_REFRESH_INTERVAL")' in config
    assert "if settings.llm_refresh_interval > 0:" in startup
    assert "asyncio.create_task(_periodic_refresh())" in startup
