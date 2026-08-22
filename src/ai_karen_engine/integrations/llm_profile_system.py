"""
RETIRED: integrations/llm_profile_system.py

LLM profile management has migrated to:
    core.model_runtime.provider_registry_service.ProviderRegistryService
    core.runtime.policy.RuntimePolicyEnforcer

This module intentionally contains no profile management logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class RouterPolicy(Enum):
    PERFORMANCE = "performance"
    QUALITY = "quality"
    COST = "cost"
    PRIVACY = "privacy"
    BALANCED = "balanced"


class GuardrailLevel(Enum):
    STRICT = "strict"
    MODERATE = "moderate"
    RELAXED = "relaxed"


@dataclass
class ProviderPreference:
    name: str = ""
    priority: int = 50
    enabled: bool = True
    api_key_env: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)


@dataclass
class GuardrailConfig:
    level: GuardrailLevel = GuardrailLevel.MODERATE
    max_tokens: int = 4096
    blocked_capabilities: List[str] = field(default_factory=list)


@dataclass
class MemoryBudget:
    max_context_tokens: int = 8192
    reserved_output_tokens: int = 1024
    max_conversation_turns: int = 50


class _RetiredProfileManager:
    """No-op profile manager for retired module."""

    def get_profile(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def set_profile(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_profiles(self, *args: Any, **kwargs: Any) -> List[str]:
        return []

    def create_profile(self, *args: Any, **kwargs: Any) -> str:
        return ""

    def delete_profile(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def update_profile(self, *args: Any, **kwargs: Any) -> None:
        pass


class LLMProfileManager:
    """Retired profile manager."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning("LLMProfileManager is retired.")

    def get_profile(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def set_profile(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_profiles(self, *args: Any, **kwargs: Any) -> List[str]:
        return []

    def create_profile(self, *args: Any, **kwargs: Any) -> str:
        return ""

    def delete_profile(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def update_profile(self, *args: Any, **kwargs: Any) -> None:
        pass


def get_profile_manager(*args: Any, **kwargs: Any) -> LLMProfileManager:
    logger.warning("get_profile_manager is retired.")
    return LLMProfileManager()


__all__ = [
    "RouterPolicy",
    "GuardrailLevel",
    "ProviderPreference",
    "GuardrailConfig",
    "MemoryBudget",
    "LLMProfileManager",
    "get_profile_manager",
]
