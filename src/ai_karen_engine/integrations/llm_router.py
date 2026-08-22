"""
RETIRED: integrations/llm_router.py

This module was the legacy IntelligentLLMRouter. Provider/model selection
authority has migrated to:

    ChatRuntimeControlPlane / ProviderRouter
        -> ProviderRegistryService
        -> RuntimeResilience
        -> ExpressionGateway

All routing decisions now flow through the canonical control plane. This
module intentionally contains no selection logic. Any import or call returns
an explicit unavailable result so dead callers surface immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _RetiredModule:
    """Mixin that marks a class as retired from the legacy routing cluster."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning(
            "integrations.llm_router is retired. "
            "Routing authority is ChatRuntimeControlPlane / ProviderRouter."
        )

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"integrations.llm_router.{name} is retired. "
            f"Use core.runtime.chat_runtime_control_plane or "
            f"core.model_runtime.provider_registry_service instead."
        )


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
class RoutingRequest:
    prompt: str
    task_type: TaskType = TaskType.CHAT
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    performance_req: PerformanceRequirement = PerformanceRequirement.INTERACTIVE
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    preferred_runtime: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    context_length: Optional[int] = None
    requires_streaming: bool = False
    requires_function_calling: bool = False
    requires_vision: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    capability_requirements: Optional[Any] = None
    allow_capability_degradation: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDecision:
    provider: str = ""
    runtime: str = ""
    model_id: str = ""
    reason: str = "retired"
    confidence: float = 0.0
    fallback_chain: List[str] = field(default_factory=list)
    estimated_cost: Optional[float] = None
    estimated_latency: Optional[float] = None
    privacy_compliant: bool = False
    capabilities: List[str] = field(default_factory=list)


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


class IntelligentLLMRouter(_RetiredModule):
    """Retired. Use ChatRuntimeControlPlane / ProviderRouter."""

    def route(self, request: RoutingRequest) -> RouteDecision:
        raise RuntimeError(
            "IntelligentLLMRouter is retired. "
            "Route through ChatRuntimeControlPlane instead."
        )

    def route_with_fallback(self, request: RoutingRequest) -> RouteDecision:
        raise RuntimeError(
            "IntelligentLLMRouter.route_with_fallback is retired. "
            "Fallback is owned by RuntimeResilience."
        )

    def dry_run(self, request: RoutingRequest) -> Dict[str, Any]:
        raise RuntimeError("IntelligentLLMRouter.dry_run is retired.")


class LLMProfileRouter(_RetiredModule):
    """Retired profile-based router shim."""

    def route(self, request: Any) -> Any:
        raise RuntimeError("LLMProfileRouter is retired.")


def get_llm_router() -> IntelligentLLMRouter:
    """Return a retired router stub. Routing must go through the control plane."""
    logger.warning("get_llm_router() is retired. Use ChatRuntimeControlPlane.")
    return IntelligentLLMRouter()


def create_intelligent_router(policy: Optional[RoutingPolicy] = None) -> IntelligentLLMRouter:
    raise RuntimeError("create_intelligent_router is retired.")


__all__ = [
    "IntelligentLLMRouter",
    "LLMProfileRouter",
    "RoutingRequest",
    "RouteDecision",
    "TaskType",
    "PrivacyLevel",
    "PerformanceRequirement",
    "RoutingPolicy",
    "get_llm_router",
    "create_intelligent_router",
]
