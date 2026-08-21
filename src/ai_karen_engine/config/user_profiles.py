"""
User Profiles configuration management built on top of ConfigManager.

Extends config.json with a `user_profiles` section and provides CRUD,
validation, and active profile switching. Designed to interoperate with
LLMRegistry for validation but degrades gracefully if registry is unavailable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.config.config_manager import get_config_manager, ConfigManager


@dataclass
class ModelAssignment:
    task_type: str
    provider: str
    model: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserProfile:
    id: str
    name: str
    assignments: Dict[str, ModelAssignment] = field(default_factory=dict)
    fallback_chain: List[str] = field(
        default_factory=lambda: [
            "ollama",
            "builtin_transformers",
            "openai",
            "deepseek",
            "huggingface",
            "gemini",
        ]
    )
    is_active: bool = False
    updated_at: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "assignments": {
                tt: {
                    "provider": ma.provider,
                    "model": ma.model,
                    "parameters": ma.parameters,
                }
                for tt, ma in self.assignments.items()
            },
            "fallback_chain": list(self.fallback_chain),
            "is_active": self.is_active,
            "updated_at": self.updated_at or datetime.utcnow().isoformat(),
        }

    @staticmethod
    def from_json(data: Dict[str, Any]) -> UserProfile:
        assignments = {
            tt: ModelAssignment(
                task_type=tt,
                provider=spec.get("provider", ""),
                model=spec.get("model", ""),
                parameters=spec.get("parameters", {}),
            )
            for tt, spec in (data.get("assignments") or {}).items()
        }
        return UserProfile(
            id=data["id"],
            name=data.get("name", data["id"]),
            assignments=assignments,
            fallback_chain=list(data.get("fallback_chain", [])),
            is_active=bool(data.get("is_active", False)),
            updated_at=data.get("updated_at"),
        )


class UserProfilesManager:
    """CRUD and validation for user profiles persisted in config.json."""

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.cm = config_manager or get_config_manager()

    # ------------ Persistence helpers ------------
    def _ensure_section(self) -> Dict[str, Any]:
        cfg = self.cm.get_config()
        # Handle both object and dict for backward compatibility
        if isinstance(cfg, dict):
            up = cfg.get("user_profiles") or {}
            active_profile = cfg.get("active_profile")
        else:
            up = getattr(cfg, "user_profiles", {}) or {}
            active_profile = getattr(cfg, "active_profile", None)

        if "profiles" not in up:
            up["profiles"] = []
        if "active_profile" not in up:
            # Keep backwards compat with ConfigManager.active_profile if set
            up["active_profile"] = active_profile or (
                up["profiles"][0]["id"] if up["profiles"] else None
            )
        # persist back to in-memory config object
        self.cm.update_config(
            {"user_profiles": up, "active_profile": up.get("active_profile")}
        )
        return up

    def _save(self) -> None:
        # Leverage ConfigManager.save_config to write config.json
        self.cm.save_config()

    def _backup(self) -> Path:
        path = self.cm.config_path
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        backup_path = path.with_suffix(f".bak.{ts}")
        shutil.copy2(path, backup_path) if path.exists() else None
        return backup_path

    # ------------ CRUD ------------
    def list_profiles(self) -> List[UserProfile]:
        up = self._ensure_section()
        return [UserProfile.from_json(p) for p in up.get("profiles", [])]

    def get_active_profile(self) -> Optional[UserProfile]:
        up = self._ensure_section()
        active_id = up.get("active_profile")
        for p in up.get("profiles", []):
            if p.get("id") == active_id or p.get("is_active"):
                return UserProfile.from_json(p)
        return None

    def get_profile(self, profile_id: str) -> Optional[UserProfile]:
        up = self._ensure_section()
        for p in up.get("profiles", []):
            if p.get("id") == profile_id:
                return UserProfile.from_json(p)
        return None

    def create_profile(
        self, profile: UserProfile, make_active: bool = False
    ) -> UserProfile:
        up = self._ensure_section()
        if any(p.get("id") == profile.id for p in up.get("profiles", [])):
            raise ValueError(f"Profile already exists: {profile.id}")
        if make_active:
            for p in up["profiles"]:
                p["is_active"] = False
            up["active_profile"] = profile.id
            profile.is_active = True
        up["profiles"].append(profile.to_json())
        self.cm.update_config(
            {"user_profiles": up, "active_profile": up.get("active_profile")}
        )
        self._save()
        return profile

    def update_profile(self, profile: UserProfile) -> UserProfile:
        up = self._ensure_section()
        found = False
        for i, p in enumerate(up.get("profiles", [])):
            if p.get("id") == profile.id:
                up["profiles"][i] = profile.to_json()
                found = True
                break
        if not found:
            raise ValueError(f"Profile not found: {profile.id}")
        # Keep active_profile field consistent
        if profile.is_active:
            up["active_profile"] = profile.id
            for i, p in enumerate(up["profiles"]):
                up["profiles"][i]["is_active"] = p["id"] == profile.id
        self.cm.update_config(
            {"user_profiles": up, "active_profile": up.get("active_profile")}
        )
        self._save()
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        up = self._ensure_section()
        before = len(up.get("profiles", []))
        up["profiles"] = [
            p for p in up.get("profiles", []) if p.get("id") != profile_id
        ]
        if up.get("active_profile") == profile_id:
            up["active_profile"] = up["profiles"][0]["id"] if up["profiles"] else None
        self.cm.update_config(
            {"user_profiles": up, "active_profile": up.get("active_profile")}
        )
        self._save()
        return len(up.get("profiles", [])) < before

    def set_active_profile(self, profile_id: str) -> UserProfile:
        up = self._ensure_section()
        found = False
        for i, p in enumerate(up.get("profiles", [])):
            if p.get("id") == profile_id:
                up["profiles"][i]["is_active"] = True
                found = True
            else:
                up["profiles"][i]["is_active"] = False
        if not found:
            raise ValueError(f"Profile not found: {profile_id}")
        up["active_profile"] = profile_id
        self.cm.update_config({"user_profiles": up, "active_profile": profile_id})
        self._save()
        return self.get_active_profile()  # type: ignore

    # ------------ Validation ------------
    def validate_profile(self, profile: UserProfile) -> List[str]:
        errors: List[str] = []
        # Basic field checks
        if not profile.id or not profile.name:
            errors.append("Profile id and name are required")
        for tt, ma in profile.assignments.items():
            if not ma.provider:
                errors.append(f"Assignment '{tt}': provider required")
            if not ma.model:
                errors.append(f"Assignment '{tt}': model required")
        # Optional registry-based validation
        try:
            from ai_karen_engine.integrations.llm_registry import LLMRegistry

            reg = LLMRegistry()
            providers = set(reg.list_providers())
            for tt, ma in profile.assignments.items():
                if ma.provider and ma.provider not in providers:
                    errors.append(
                        f"Assignment '{tt}': provider '{ma.provider}' not registered"
                    )
        except Exception:
            # Skip registry validation if not available
            pass
        return errors

    # ------------ Utilities ------------
    def get_model_assignment(
        self, profile: UserProfile, task_type: str
    ) -> Optional[ModelAssignment]:
        return profile.assignments.get(task_type)

    def ensure_default_profile(self) -> UserProfile:
        up = self._ensure_section()
        if up.get("profiles"):
            return self.get_active_profile() or UserProfile.from_json(up["profiles"][0])
        default = UserProfile(
            id="default",
            name="Default",
            assignments={
                "chat": ModelAssignment("chat", "openai", "gpt-4o-mini"),
                "code": ModelAssignment("code", "deepseek", "deepseek-coder"),
                "reasoning": ModelAssignment("reasoning", "openai", "gpt-4o"),
                "summarization": ModelAssignment("summarization", "builtin_transformers", "auto"),
            },
            is_active=True,
        )
        self.create_profile(default, make_active=True)
        return default


# Global accessor
_global_upm: Optional[UserProfilesManager] = None


def get_user_profiles_manager() -> UserProfilesManager:
    global _global_upm
    if _global_upm is None:
        _global_upm = UserProfilesManager()
    return _global_upm
