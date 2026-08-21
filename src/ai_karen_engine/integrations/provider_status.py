"""Utilities for collecting runtime provider status information."""

from __future__ import annotations

import time
from typing import Any, Dict

from .llm_registry import get_registry


class ProviderHealth:
    """Provider health checking utility that integrates with the LLM registry."""
    
    SOURCE = "registry"
    
    @staticmethod
    async def is_healthy(provider_name: str) -> bool:
        """Check if a provider is healthy based on registry status."""
        try:
            registry = get_registry()
            provider_info = registry.get_provider_info(provider_name)
            if not provider_info:
                return False
            
            # Check health status from registry
            health_status = provider_info.get("health_status", "unknown")
            
            # Consider built-in local runtimes and common cloud providers healthy 
            # when their status is 'unknown' so routing can prefer them before 
            # falling back to degraded modes.
            if health_status in ["healthy", "unknown", "degraded"]:
                if provider_name in {
                    "local_gguf",
                    "builtin_vllm",
                    "builtin_transformers",
                    "openai",
                    "gemini",
                    "deepseek",
                    "anthropic",
                }:
                    return True
            
            return health_status == "healthy"
        except Exception:
            # If we can't check health, assume unhealthy for safety
            return False


def collect_provider_statuses() -> Dict[str, Any]:
    """Ping each registered provider and gather basic statistics."""

    registry = get_registry()
    statuses: Dict[str, Any] = {}

    for name in registry.list_providers():
        provider = registry.get_provider(name)
        if not provider:
            continue
        start = time.perf_counter()
        healthy = False
        try:
            healthy = bool(getattr(provider, "ping", lambda: False)())
        except Exception:
            healthy = False
        latency = int((time.perf_counter() - start) * 1000)
        models: list[str] = []
        try:
            models = list(getattr(provider, "available_models", lambda: [])())
        except Exception:
            pass
        statuses[name] = {
            "healthy": healthy,
            "latency_ms": latency,
            "models": models,
            "model_count": len(models),
        }

    return statuses


__all__ = ["collect_provider_statuses", "ProviderHealth"]
