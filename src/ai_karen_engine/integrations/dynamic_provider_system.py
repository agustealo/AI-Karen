"""
Dynamic provider system stub.

This module provides a minimal compatibility layer for the dynamic provider
management API used by model management routes. Full implementation is
deferred; the current provider registry remains the source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Minimal model metadata shape expected by management routes."""

    id: str
    name: str
    description: str = ""
    capabilities: List[str] = ""
    context_length: Optional[int] = None
    metadata: Dict[str, Any] = ""


class DynamicProviderManager:
    """Compatibility wrapper for dynamic provider operations."""

    async def validate_provider_async(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        logger.debug("Dynamic provider validation stub for %s", provider_id)
        return True

    def get_provider_models(self, provider_id: str) -> List[ModelInfo]:
        logger.debug("Dynamic provider model discovery stub for %s", provider_id)
        return []

    def get_fallback_models(self, provider_id: str) -> List[Dict[str, Any]]:
        logger.debug("Dynamic provider fallback models stub for %s", provider_id)
        return []


_global_dynamic_provider_manager: Optional[DynamicProviderManager] = None


def get_dynamic_provider_manager() -> DynamicProviderManager:
    """Return the global dynamic provider manager instance."""
    global _global_dynamic_provider_manager
    if _global_dynamic_provider_manager is None:
        _global_dynamic_provider_manager = DynamicProviderManager()
    return _global_dynamic_provider_manager
