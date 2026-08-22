"""
KIRE-KRO Integration Module - RETIRED

This module has been retired. Routing authority belongs to ProviderRouter.
Reasoning belongs to ReasoningExecutor. Execution belongs to Runtime.

Previous behavior that lived here:
- provider selection
- model discovery initialization
- CUDA acceleration initialization
- content optimization initialization
- deep-reasoning → LangGraph mapping
- Medusa invocation
- canned "Processed successfully." responses
- fallback/error response manufacturing

All of those responsibilities now have canonical owners.

Migration:
- Standard chat: ChatRuntime → ExpressionGateway
- Reasoning: CORTEX → RuntimePolicy → ReasoningExecutor → PromptRuntime
- Workflow: CORTEX → RuntimePolicy → WorkflowRuntime
- Multi-agent: CORTEX → RuntimePolicy → Medusa
- Provider selection: RuntimePolicy → ProviderRouter
- Memory: Runtime → NeuroRecall / MemoryManager
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class IntegrationConfig:
    """Retired configuration. Kept for import compatibility only."""

    def __init__(self, **kwargs: Any) -> None:
        warnings.warn(
            "IntegrationConfig is retired. Use RuntimePolicy and canonical runtime configs.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.enable_kire_routing = False
        self.enable_cuda_acceleration = False
        self.enable_content_optimization = False
        self.enable_model_discovery = False
        self.enable_degraded_mode = True
        self.enable_metrics = False
        self.cache_routing_decisions = False
        self.max_concurrent_requests = kwargs.get("max_concurrent_requests", 10)
        self.request_timeout = kwargs.get("request_timeout", 120.0)


class KIREKROIntegration:
    """Retired integration. Raises on any operation."""

    def __init__(self, config: Optional[IntegrationConfig] = None) -> None:
        warnings.warn(
            "KIREKROIntegration is retired. "
            "Use ChatRuntime, ReasoningExecutor, WorkflowRuntime, and Medusa directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.config = config or IntegrationConfig()

    async def initialize(self) -> None:
        raise RuntimeError(
            "KIREKROIntegration is retired. "
            "Use canonical runtime initialization instead."
        )

    async def process_user_request(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError(
            "KIREKROIntegration.process_user_request is retired. "
            "Use ChatRuntime.execute() instead."
        )

    async def process_specialized_request(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError(
            "KIREKROIntegration.process_specialized_request is retired. "
            "Use ReasoningExecutor.execute() instead."
        )

    async def get_available_models(self) -> List[Dict[str, Any]]:
        raise RuntimeError(
            "KIREKROIntegration.get_available_models is retired. "
            "Use ProviderRouter or ProviderRegistry directly."
        )

    async def get_routing_decision(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError(
            "KIREKROIntegration.get_routing_decision is retired. "
            "Routing advisory is produced by CORTEX IntelligenceRuntime."
        )

    async def get_system_status(self) -> Dict[str, Any]:
        raise RuntimeError(
            "KIREKROIntegration.get_system_status is retired."
        )

    async def health_check(self) -> Dict[str, Any]:
        raise RuntimeError(
            "KIREKROIntegration.health_check is retired."
        )


def get_integration() -> KIREKROIntegration:
    """Retired factory. Returns a stub that raises on use."""
    return KIREKROIntegration()


async def initialize_integration(config: Optional[IntegrationConfig] = None) -> KIREKROIntegration:
    """Retired initializer."""
    integration = get_integration()
    if config:
        integration.config = config
    return integration


async def process_request(
    user_input: str,
    user_id: str = "anon",
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retired convenience function."""
    raise RuntimeError(
        "process_request is retired. Use ChatRuntime.execute() or ReasoningExecutor.execute()."
    )


async def get_available_models() -> List[Dict[str, Any]]:
    """Retired convenience function."""
    raise RuntimeError(
        "get_available_models is retired. Use ProviderRouter or ProviderRegistry directly."
    )


async def get_system_status() -> Dict[str, Any]:
    """Retired convenience function."""
    raise RuntimeError("get_system_status is retired.")


async def health_check() -> Dict[str, Any]:
    """Retired convenience function."""
    raise RuntimeError("health_check is retired.")
