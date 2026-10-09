"""Regression coverage for canonical LLM defaults in user preferences."""

from types import SimpleNamespace
from unittest.mock import patch

from ai_karen_engine.config.config_manager import LLMConfig
from ai_karen_engine.services.user_prefs import get_user_prefs


def test_user_prefs_reads_canonical_llm_default_fields():
    llm = LLMConfig(default_provider="ollama", default_model="qwen-local")
    settings = SimpleNamespace(get_setting=lambda key, default=None: default)
    profiles = SimpleNamespace(list_profiles=lambda: [])
    degraded = SimpleNamespace(
        is_active=False,
        reason=None,
        activated_at=None,
        failed_providers=[],
        recovery_attempts=0,
    )
    with (
        patch("ai_karen_engine.services.user_prefs.get_config", return_value=SimpleNamespace(llm=llm, ui={})),
        patch("ai_karen_engine.services.user_prefs._get_settings_manager", return_value=settings),
        patch("ai_karen_engine.services.user_prefs._get_profiles_manager", return_value=profiles),
        patch("ai_karen_engine.services.user_prefs._resolve_profile_preferences", return_value=(None, {})),
        patch("ai_karen_engine.services.user_prefs.get_degraded_mode_manager", return_value=SimpleNamespace(get_status=lambda: degraded)),
    ):
        prefs = get_user_prefs()

    assert prefs.preferred_provider == "ollama"
    assert prefs.preferred_model == "qwen-local"
    assert prefs.show_degraded_banner is False
