"""
RETIRED: integrations/performance_adaptive_router.py

Performance-adaptive routing authority has migrated to:
    core.runtime.chat_runtime_control_plane.ChatRuntimeControlPlane
    core.model_runtime.model_selection_algorithm.ModelSelectionAlgorithm

This module intentionally contains no routing logic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _FallbackChainManagerStub:
    """Stub replacing retired integrations/fallback_chain_manager.py."""

    def register_switch_callback(self, callback: Any) -> None:
        pass

    def _create_context_bridge(self, *args: Any, **kwargs: Any) -> Any:
        return None


def _get_fallback_chain_manager_stub() -> _FallbackChainManagerStub:
    return _FallbackChainManagerStub()


@dataclass
class AdaptiveConfig:
    pass


class PerformanceAdaptiveRouter:
    """Retired performance-adaptive router."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning("PerformanceAdaptiveRouter is retired.")

    async def route(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("PerformanceAdaptiveRouter is retired.")

    async def route_request(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("PerformanceAdaptiveRouter.route_request is retired.")

    async def _get_fallback_providers(self, *args: Any, **kwargs: Any) -> List[str]:
        return []


def get_performance_adaptive_router(*args: Any, **kwargs: Any) -> PerformanceAdaptiveRouter:
    logger.warning("get_performance_adaptive_router is retired.")
    return PerformanceAdaptiveRouter()


class AdaptiveStrategy:
    BALANCED = "balanced"
    PERFORMANCE = "performance"
    COST = "cost"
    PRIVACY = "privacy"


__all__ = ["PerformanceAdaptiveRouter", "AdaptiveConfig", "AdaptiveStrategy", "get_performance_adaptive_router"]
