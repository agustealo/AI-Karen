"""
RETIRED: integrations/capability_router.py

Capability-aware routing authority has migrated to:
    core.model_runtime.model_capabilities
    core.model_runtime.model_selection_algorithm
    core.runtime.policy.RuntimePolicyEnforcer

This module intentionally contains no routing logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class CapabilityCheckResult:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "CapabilityRouter is retired. "
            "Use core.model_runtime.model_capabilities instead."
        )


class RoutingCapabilityRequest:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("CapabilityRouter is retired.")


class CapabilityRoutingResult:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("CapabilityRouter is retired.")


class CapabilityRouter:
    """Retired capability router."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.warning("CapabilityRouter is retired.")

    def route_with_capabilities(self, *args: Any, **kwargs: Any) -> CapabilityRoutingResult:
        raise RuntimeError("CapabilityRouter.route_with_capabilities is retired.")

    def check_provider_capabilities(self, *args: Any, **kwargs: Any) -> CapabilityCheckResult:
        raise RuntimeError("CapabilityRouter.check_provider_capabilities is retired.")


def get_capability_router(*args: Any, **kwargs: Any) -> CapabilityRouter:
    logger.warning("get_capability_router is retired.")
    return CapabilityRouter()


__all__ = [
    "CapabilityCheckResult",
    "RoutingCapabilityRequest",
    "CapabilityRoutingResult",
    "CapabilityRouter",
    "get_capability_router",
]
