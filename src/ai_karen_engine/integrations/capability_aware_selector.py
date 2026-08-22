"""
RETIRED: integrations/capability_aware_selector.py

Provider selection authority has migrated to:
    core.model_runtime.model_selection_algorithm.ModelSelectionAlgorithm
    core.runtime.policy.RuntimePolicyEnforcer
    core.model_runtime.provider_registry_service.ProviderRegistryService

This module intentionally contains no selection logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SelectionStrategy(Enum):
    CAPABILITY_FIRST = auto()
    PERFORMANCE_FIRST = auto()
    COST_FIRST = auto()
    RELIABILITY_FIRST = auto()
    LOCAL_FIRST = auto()
    ADAPTIVE = auto()


class RequestContext(Enum):
    REALTIME = auto()
    BATCH = auto()
    CREATIVE = auto()
    ANALYTICAL = auto()
    CODE = auto()
    CONVERSATION = auto()
    EMBEDDING = auto()


@dataclass
class CapabilityRequirement:
    name: str
    priority: float = 1.0
    min_quality: float = 0.7
    preferred_providers: List[str] = field(default_factory=list)
    excluded_providers: List[str] = field(default_factory=list)
    max_latency: Optional[float] = None
    max_cost: Optional[float] = None


@dataclass
class SelectionCriteria:
    required_capabilities: List[CapabilityRequirement]
    context: RequestContext = RequestContext.REALTIME
    strategy: SelectionStrategy = SelectionStrategy.ADAPTIVE
    network_preference: str = "auto"
    cost_sensitivity: float = 0.5
    performance_weight: float = 0.5
    reliability_weight: float = 0.5
    local_preference: float = 0.5
    excluded_providers: List[str] = field(default_factory=list)


@dataclass
class ProviderScore:
    provider_name: str
    total_score: float = 0.0
    capability_score: float = 0.0
    performance_score: float = 0.0
    cost_score: float = 0.0
    reliability_score: float = 0.0
    network_score: float = 0.0
    context_score: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)


class CapabilityAwareSelector:
    """Retired capability-aware selector."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning("CapabilityAwareSelector is retired.")

    def select_provider(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "CapabilityAwareSelector.select_provider is retired. "
            "Use ModelSelectionAlgorithm instead."
        )


def get_capability_selector(*args: Any, **kwargs: Any) -> CapabilityAwareSelector:
    logger.warning("get_capability_selector is retired.")
    return CapabilityAwareSelector()


def initialize_capability_selector(*args: Any, **kwargs: Any) -> CapabilityAwareSelector:
    logger.warning("initialize_capability_selector is retired.")
    return CapabilityAwareSelector()


__all__ = [
    "SelectionStrategy",
    "RequestContext",
    "CapabilityRequirement",
    "SelectionCriteria",
    "ProviderScore",
    "CapabilityAwareSelector",
    "get_capability_selector",
    "initialize_capability_selector",
]
