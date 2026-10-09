"""Utilities for loading web UI user preference defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional
import logging

from ai_karen_engine.config.user_profiles import UserProfilesManager
from ai_karen_engine.config.config_manager import get_config
from ai_karen_engine.core.runtime.degraded_mode import get_degraded_mode_manager
from ai_karen_engine.services.formatting.settings_manager import SettingsManager


logger = logging.getLogger(__name__)


@dataclass
class UserPrefs:
    """Materialised preference payload returned to the web UI."""

    preferred_provider: str
    preferred_model: str
    show_degraded_banner: bool
    ui: Dict[str, Any] = field(default_factory=dict)
    degraded_status: Dict[str, Any] = field(default_factory=dict)
    active_profile: Optional[str] = None
    available_profiles: List[str] = field(default_factory=list)
    profile_assignments: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _get_settings_manager() -> SettingsManager:
    """Return a cached SettingsManager instance."""

    return SettingsManager()


@lru_cache(maxsize=1)
def _get_profiles_manager() -> UserProfilesManager:
    """Return a cached user profiles manager."""

    return UserProfilesManager()


def _resolve_profile_preferences() -> tuple[Optional[str], Dict[str, Dict[str, Any]]]:
    """Fetch the active profile id and serialised assignments."""

    profile_manager = _get_profiles_manager()
    active_profile = profile_manager.get_active_profile()
    if not active_profile:
        return None, {}

    assignments: Dict[str, Dict[str, Any]] = {}
    for task_type, assignment in active_profile.assignments.items():
        assignments[task_type] = {
            "provider": assignment.provider,
            "model": assignment.model,
            "parameters": assignment.parameters,
        }

    return active_profile.id, assignments


def _choose_provider_and_model(
    *,
    default_provider: str,
    default_model: str,
    profile_assignments: Dict[str, Dict[str, Any]],
) -> tuple[str, str]:
    """Select a provider/model tuple honouring profile overrides."""

    # Chat first, otherwise fall back to the first configured assignment
    chat_assignment = profile_assignments.get("chat")
    if chat_assignment:
        provider = chat_assignment.get("provider") or default_provider
        model = chat_assignment.get("model") or default_model
        return provider, model

    for assignment in profile_assignments.values():
        provider = assignment.get("provider") or default_provider
        model = assignment.get("model") or default_model
        if provider or model:
            return provider, model

    return default_provider, default_model


def _build_ui_preferences(
    settings: SettingsManager, base_ui: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge persisted UI preferences with runtime defaults."""

    ui_preferences: Dict[str, Any] = {
        "theme": base_ui.get("theme", "dark"),
        "show_debug_info": bool(base_ui.get("show_debug_info", False)),
        "features": settings.get_setting("features", {}),
    }

    # Include additional web UI toggles when present in the config.json payload.
    for key in ("use_memory", "context_length", "decay"):
        value = settings.get_setting(key)
        if value is not None:
            ui_preferences[key] = value

    return ui_preferences


def get_user_prefs() -> UserPrefs:
    """Return the computed user preferences for the Kari web UI."""

    config = get_config()
    settings_manager = _get_settings_manager()

    # Determine routing profile overrides (if any)
    active_profile_id, assignments = _resolve_profile_preferences()
    preferred_provider, preferred_model = _choose_provider_and_model(
        default_provider=config.llm.default_provider,
        default_model=config.llm.default_model,
        profile_assignments=assignments,
    )

    # When no explicit profile is configured fall back to settings.json overrides
    if not active_profile_id:
        preferred_provider = (
            settings_manager.get_setting("provider") or preferred_provider
        )
        preferred_model = settings_manager.get_setting("model") or preferred_model
        logger.debug(
            "No active routing profile configured; falling back to settings.json defaults",
        )

    degraded_status = get_degraded_mode_manager().get_status()
    degraded_payload = {
        "is_active": degraded_status.is_active,
        "reason": degraded_status.reason.value if degraded_status.reason else None,
        "activated_at": degraded_status.activated_at.isoformat()
        if degraded_status.activated_at
        else None,
        "failed_providers": degraded_status.failed_providers,
        "recovery_attempts": degraded_status.recovery_attempts,
    }

    ui_preferences = _build_ui_preferences(settings_manager, config.ui)

    profiles_manager = _get_profiles_manager()
    available_profiles = [profile.id for profile in profiles_manager.list_profiles()]

    return UserPrefs(
        preferred_provider=preferred_provider,
        preferred_model=preferred_model,
        show_degraded_banner=degraded_status.is_active,
        ui=ui_preferences,
        degraded_status=degraded_payload,
        active_profile=active_profile_id,
        available_profiles=available_profiles,
        profile_assignments=assignments,
    )
