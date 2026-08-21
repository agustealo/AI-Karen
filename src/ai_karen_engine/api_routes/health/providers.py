"""Provider health and diagnostics endpoints."""

import logging
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health/providers", tags=["health", "providers"])


@router.get("/vllm")
async def get_vllm_health() -> Dict[str, Any]:
    """
    Get vLLM provider health and diagnostics.
    
    Tests:
    - vLLM server connectivity
    - Model availability
    - Generation capability
    
    Returns:
        Dict with health status, available models, and test results
    """
    try:
        from ai_karen_engine.integrations.provider_registry import get_provider_registry
    except ImportError:
        return {
            "provider": "builtin_vllm",
            "provider_id": "builtin_vllm",
            "enabled": False,
            "healthy": False,
            "error": "Provider registry not available"
        }
    
    registry = get_provider_registry()
    vllm_info = registry.get_provider_info("builtin_vllm")
    
    if not vllm_info:
        return {
            "provider": "builtin_vllm",
            "provider_id": "builtin_vllm",
            "enabled": False,
            "healthy": False,
            "error": "vLLM not configured in provider registry"
        }
    
    # ProviderRegistration metadata dict or info dict
    metadata = vllm_info.metadata if hasattr(vllm_info, "metadata") else vllm_info
    
    base_url = (
        os.getenv("KAREN_BUILTIN_VLLM_BASE_URL")
        or metadata.get("base_url")
        or "http://vllm:8000/v1"
    ).rstrip("/")
    health_url = (
        os.getenv("KAREN_BUILTIN_VLLM_HEALTH_URL")
        or metadata.get("health_url")
        or metadata.get("health_check_url")
        or "http://vllm:8000/health"
    )
    default_model = (
        os.getenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME")
        or metadata.get("default_model")
        or metadata.get("model")
        or "auto"
    )
    
    result = {
        "provider": "builtin_vllm",
        "provider_id": "builtin_vllm",
        "runtime_engine": "vllm",
        "enabled": metadata.get("enabled", False),
        "base_url": base_url,
        "health_check_url": health_url,
        "default_model": default_model,
        "streaming_supported": metadata.get("streaming_supported", True),
    }
    
    # Test health endpoint
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health_response = await client.get(health_url)
            result["health_endpoint_ok"] = health_response.status_code == 200
            if health_response.status_code == 200:
                result["health_response"] = health_response.json()
    except Exception as e:
        result["health_endpoint_ok"] = False
        result["health_error"] = str(e)
        logger.warning(f"vLLM health check failed: {e}")
    
    # Test models endpoint
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            models_response = await client.get(f"{base_url}/models")
            if models_response.status_code == 200:
                models_data = models_response.json()
                result["models_endpoint_ok"] = True
                result["available_models"] = [
                    m.get("id") for m in models_data.get("data", [])
                ]
                result["served_model_available"] = default_model in result["available_models"]
            else:
                result["models_endpoint_ok"] = False
                result["models_status_code"] = models_response.status_code
    except Exception as e:
        result["models_endpoint_ok"] = False
        result["models_error"] = str(e)
        logger.warning(f"vLLM models endpoint failed: {e}")
    
    # Test generation (only if models endpoint succeeded)
    if result.get("models_endpoint_ok") and result.get("served_model_available"):
        try:
            test_model = default_model
            async with httpx.AsyncClient(timeout=10.0) as client:
                gen_response = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": test_model,
                        "messages": [
                            {"role": "user", "content": "Say 'test' in one word."}
                        ],
                        "max_tokens": 10,
                        "temperature": 0.1,
                    }
                )
                if gen_response.status_code == 200:
                    gen_data = gen_response.json()
                    content = gen_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    result["generation_test_ok"] = bool(content.strip())
                    result["generation_test_response"] = content.strip()
                    result["generation_test_model"] = test_model
                else:
                    result["generation_test_ok"] = False
                    result["generation_status_code"] = gen_response.status_code
        except Exception as e:
            result["generation_test_ok"] = False
            result["generation_error"] = str(e)
            logger.warning(f"vLLM generation test failed: {e}")
    else:
        result["generation_test_ok"] = False
        result["generation_test_skipped"] = "models_endpoint_failed"
    
    # Overall health assessment
    result["healthy"] = (
        result.get("health_endpoint_ok", False)
        and result.get("models_endpoint_ok", False)
        and result.get("served_model_available", False)
        and result.get("generation_test_ok", False)
    )
    
    # Add recommendations
    if not result["healthy"]:
        recommendations = []
        if not result.get("health_endpoint_ok"):
            recommendations.append("Check if vLLM server is running")
            recommendations.append(f"Verify health URL: {health_url}")
        if not result.get("models_endpoint_ok"):
            recommendations.append("Check if models are loaded in vLLM")
            recommendations.append(f"Verify models URL: {base_url}/models")
        if not result.get("generation_test_ok"):
            recommendations.append("Check vLLM server logs for errors")
            recommendations.append("Verify model is properly loaded")
        result["recommendations"] = recommendations
    
    return result


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
