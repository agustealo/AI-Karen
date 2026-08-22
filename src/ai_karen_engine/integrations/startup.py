"""
LLM Provider Startup Initialization

Ensures all providers are registered and performs initial health checks on startup.
"""

import logging
import asyncio
from typing import Dict, Any

from ai_karen_engine.integrations.llm_registry import get_registry
from ai_karen_engine.integrations.llm_utils import get_llm_manager
from ai_karen_engine.core.logging import get_logger

log = get_logger("kari.kire.warmup").logger

logger = logging.getLogger("kari.llm_startup")


def initialize_llm_providers() -> Dict[str, Any]:
    """
    Initialize LLM providers on startup - SIMPLIFIED (no health checks at startup).

    Returns:
        Dict with initialization results
    """
    logger.info("Initializing LLM providers (lazy mode - no health checks)...")

    try:
        # Get registry instance (this will auto-register built-in providers)
        registry = get_registry()

        # Ensure KIRE routing predictors are registered
        try:
            import ai_karen_engine.routing.actions  # noqa: F401
        except Exception as _e:
            logger.debug(f"KIRE actions not loaded: {_e}")

        # Get list of registered providers (just registration, no health checks)
        providers = registry.list_providers()
        logger.info(f"Registered {len(providers)} providers (health checks deferred)")

        # Skip health checks - they'll happen on first use
        # Get available providers without health checks
        available_providers = registry.get_available_providers()

        result = {
            "status": "success",
            "total_providers": len(providers),
            "healthy_providers": len(providers),  # Optimistic
            "available_providers": available_providers,
        }

        logger.info(f"LLM provider initialization complete (fast startup mode)")

        # Skip routing cache warm-up at startup - too slow

        return result

    except Exception as ex:
        logger.warning(f"LLM provider initialization failed: {ex}")
        return {
            "status": "error",
            "error": str(ex),
            "total_providers": 0,
            "healthy_providers": 0,
            "available_providers": []
        }


def _warm_kire_routing_cache() -> None:
    """Warm KIRE routing by pre-resolving common task decisions.

    Uses LLMRegistry.get_provider_with_routing to exercise provider/model resolution and
    populate internal caches. Best-effort; failures are logged at debug.
    """
    async def _warm_async() -> None:
        reg = get_registry()
        user_ctx = {"user_id": "system_warmup"}
        samples = [
            {"query": "Hello!", "task_type": "chat", "step": "output_rendering"},
            {"query": "Write a Python function to add two numbers", "task_type": "code", "step": "tool_execution"},
            {"query": "Explain why the sky is blue", "task_type": "reasoning", "step": "reasoning_core"},
            {"query": "Summarize: Large text", "task_type": "summarization", "step": "output_rendering"},
        ]
        for s in samples:
            try:
                await reg.get_provider_with_routing(
                    user_ctx=user_ctx,
                    query=s["query"],
                    task_type=s["task_type"],
                    khrp_step=s["step"],
                    requirements={"expected_tokens": 512},
                )
            except Exception as e:
                log.debug(f"Warm-up failed for {s['task_type']}: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_warm_async())
        else:
            loop.run_until_complete(_warm_async())
        log.info("KIRE routing warm-up initiated")
    except Exception:
        # Last resort: run in a fresh loop
        try:
            asyncio.run(_warm_async())
            log.info("KIRE routing warm-up completed (standalone loop)")
        except Exception as e:
            log.debug(f"KIRE routing warm-up could not run: {e}")


def get_default_llm_manager():
    """Get default LLM manager with registry-based providers."""
    return get_llm_manager(use_registry=True)


async def async_health_check_all() -> Dict[str, Dict[str, Any]]:
    """Perform async health check on all providers."""
    registry = get_registry()
    
    # Run health checks concurrently
    providers = registry.list_providers()
    tasks = []
    
    async def check_provider(name: str) -> tuple[str, Dict[str, Any]]:
        # Run health check in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, registry.health_check, name)
        return name, result
    
    tasks = [check_provider(name) for name in providers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    health_results = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Health check failed: {result}")
        else:
            name, health = result
            health_results[name] = health
    
    return health_results


def validate_provider_configuration() -> Dict[str, Any]:
    """
    Validate provider configurations and API keys.
    
    Returns:
        Dict with validation results
    """
    logger.info("Validating provider configurations...")
    
    registry = get_registry()
    validation_results = {}
    
    for provider_name in registry.list_providers():
        try:
            provider_info = registry.get_provider_info(provider_name)
            if not provider_info:
                validation_results[provider_name] = {
                    "status": "error",
                    "message": "Provider info not available"
                }
                continue
            
            # Check if API key is required and available
            if provider_info.get("requires_api_key", False):
                # Try to create provider instance to check API key
                provider = registry.get_provider(provider_name)
                if provider:
                    provider_runtime_info = provider.get_provider_info()
                    has_api_key = provider_runtime_info.get("has_api_key", False)
                    
                    if has_api_key:
                        validation_results[provider_name] = {
                            "status": "valid",
                            "message": "API key configured"
                        }
                    else:
                        validation_results[provider_name] = {
                            "status": "warning",
                            "message": "API key not configured - provider may not work"
                        }
                else:
                    validation_results[provider_name] = {
                        "status": "error",
                        "message": "Could not create provider instance"
                    }
            else:
                validation_results[provider_name] = {
                    "status": "valid",
                    "message": "No API key required"
                }
                
        except Exception as ex:
            validation_results[provider_name] = {
                "status": "error",
                "message": f"Validation failed: {ex}"
            }
    
    # Log validation results
    for provider_name, result in validation_results.items():
        status = result["status"]
        message = result["message"]
        
        if status == "valid":
            logger.info(f"✓ {provider_name}: {message}")
        elif status == "warning":
            logger.warning(f"⚠ {provider_name}: {message}")
        else:
            logger.error(f"✗ {provider_name}: {message}")
    
    return validation_results


# Auto-initialize on import DISABLED by default for faster startup
# LLM providers will be initialized on first use (lazy loading)
import os
if os.getenv("KARI_AUTO_INIT_LLM", "false").lower() == "true":
    try:
        initialize_llm_providers()
    except Exception as ex:
        logger.warning(f"Auto-initialization failed: {ex}")
