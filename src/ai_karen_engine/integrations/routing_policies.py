"""
RETIRED: integrations/routing_policies.py

Routing policy authority has migrated to:
    core.runtime.policy.RuntimePolicyEnforcer
    core.model_runtime.provider_registry_service.ProviderRegistryService

This module intentionally contains no policy logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskType(Enum):
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    CREATIVE = "creative"
    ANALYSIS = "analysis"


class PrivacyLevel(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PerformanceRequirement(Enum):
    INTERACTIVE = "interactive"
    BATCH = "batch"
    BACKGROUND = "background"


@dataclass
class RoutingPolicy:
    name: str = "retired"
    description: str = ""
    task_provider_map: Dict[Any, Any] = field(default_factory=dict)
    task_runtime_map: Dict[Any, Any] = field(default_factory=dict)
    privacy_provider_map: Dict[Any, Any] = field(default_factory=dict)
    privacy_runtime_map: Dict[Any, Any] = field(default_factory=dict)
    performance_provider_map: Dict[Any, Any] = field(default_factory=dict)
    performance_runtime_map: Dict[Any, Any] = field(default_factory=dict)
    fallback_providers: List[str] = field(default_factory=list)
    fallback_runtimes: List[str] = field(default_factory=list)
    privacy_weight: float = 0.0
    performance_weight: float = 0.0
    cost_weight: float = 0.0
    availability_weight: float = 0.0


@dataclass
class PolicyRule:
    name: str = ""
    description: str = ""
    conditions: Dict[str, Any] = field(default_factory=dict)
    provider_preference: Optional[str] = None
    runtime_preference: Optional[str] = None
    confidence_boost: float = 0.0
    priority: int = 50


@dataclass
class PolicyTemplate:
    name: str = ""
    description: str = ""
    base_policy: Optional[str] = None
    rules: List[PolicyRule] = field(default_factory=list)
    overrides: Dict[str, Any] = field(default_factory=dict)


class RoutingPolicyManager:
    """Retired routing policy manager."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning("RoutingPolicyManager is retired.")

    def get_policy(self, *args: Any, **kwargs: Any) -> Optional[RoutingPolicy]:
        return None

    def list_policies(self, *args: Any, **kwargs: Any) -> List[str]:
        return []


def get_policy_manager() -> RoutingPolicyManager:
    logger.warning("get_policy_manager is retired.")
    return RoutingPolicyManager()


def get_routing_policy(*args: Any, **kwargs: Any) -> Optional[RoutingPolicy]:
    return None


def list_routing_policies(*args: Any, **kwargs: Any) -> List[str]:
    return []


__all__ = [
    "PolicyRule",
    "PolicyTemplate",
    "RoutingPolicyManager",
    "get_policy_manager",
    "get_routing_policy",
    "list_routing_policies",
]
