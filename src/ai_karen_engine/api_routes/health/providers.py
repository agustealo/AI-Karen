"""Provider health and diagnostics endpoints."""

import logging
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health/providers", tags=["health", "providers"])



@router.get("/transformers")
async def get_transformers_health() -> Dict[str, Any]:
    """
    Get Transformers provider health and diagnostics.
    
    Returns:
        Dict with health status and available models
    """
    try:
        from ai_karen_engine.integrations.provider_registry import get_provider_registry
    except ImportError:
        return {
            "provider": "transformers",
            "enabled": False,
            "healthy": False,
            "error": "Provider registry not available"
        }
    
    registry = get_provider_registry()
    transformers_info = registry.get_provider_info("builtin_transformers")
    
    if not transformers_info:
        return {
            "provider": "transformers",
            "enabled": False,
            "healthy": False,
            "error": "Transformers not configured in provider registry"
        }
    
    result = {
        "provider": "transformers",
        "enabled": transformers_info.get("enabled", False),
        "default_model": transformers_info.get("default_model"),
        "models": transformers_info.get("models", []),
    }
    
    # Try to get provider instance and test
    try:
        provider = registry.get_provider("builtin_transformers")
        if provider:
            result["provider_instance_ok"] = True
            # Try a simple health check if available
            if hasattr(provider, "health_check"):
                health = provider.health_check()
                result["health_check"] = health
                result["healthy"] = health.get("status") == "healthy"
            else:
                result["healthy"] = True
        else:
            result["provider_instance_ok"] = False
            result["healthy"] = False
    except Exception as e:
        result["provider_instance_ok"] = False
        result["healthy"] = False
        result["error"] = str(e)
        logger.warning(f"Transformers health check failed: {e}")
    
    return result


@router.get("/all")
async def get_all_providers_health() -> Dict[str, Any]:
    """
    Get health status for all configured providers.
    
    Returns:
        Dict with health status for each provider
    """
    try:
        from ai_karen_engine.integrations.provider_registry import get_provider_registry
    except ImportError:
        return {
            "error": "Provider registry not available",
            "providers": {}
        }
    
    registry = get_provider_registry()
    providers = registry.list_providers()
    
    result = {
        "total_providers": len(providers),
        "providers": {}
    }
    
    for provider_name in providers:
        info = registry.get_provider_info(provider_name)
        if info:
            result["providers"][provider_name] = {
                "enabled": getattr(info, "enabled", True),
                "priority": getattr(info, "priority", 0),
                "provider_type": getattr(info, "provider_type", getattr(info, "category", "LLM")),
                "default_model": getattr(info, "default_model", ""),
                "health_status": getattr(info, "health_status", "unknown"),
            }
    
    return result

# Made with Bob
