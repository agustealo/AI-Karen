"""
Runtime Provider Manager

This module provides runtime provider switching capabilities with:
- Ability to change LLM provider without restart
- Configuration reloading for provider settings
- Provider availability checking and validation
- Provider selection logic based on request type
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Union
from datetime import datetime, timedelta

from ai_karen_engine.config.llm_provider_config import (
    get_provider_config_manager,
    ProviderConfig,
    ProviderType,
    AuthenticationType
)
from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    """Provider status enumeration"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RequestType(str, Enum):
    """Request type enumeration for provider selection"""
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    GENERIC = "generic"


@dataclass
class ProviderHealthStatus:
    """Provider health status information"""
    provider_name: str
    status: ProviderStatus
    last_check: datetime
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    last_success: Optional[datetime] = None
    capabilities_verified: Set[str] = field(default_factory=set)
    
    @property
    def is_healthy(self) -> bool:
        """Check if provider is healthy"""
        return self.status == ProviderStatus.HEALTHY
    
    @property
    def is_available(self) -> bool:
        """Check if provider is available (healthy or degraded)"""
        return self.status in [ProviderStatus.HEALTHY, ProviderStatus.DEGRADED]


@dataclass
class ProviderSelectionCriteria:
    """Criteria for provider selection"""
    request_type: RequestType
    required_capabilities: Set[str] = field(default_factory=set)
    preferred_providers: List[str] = field(default_factory=list)
    exclude_providers: Set[str] = field(default_factory=set)
    max_cost_per_1k_tokens: Optional[float] = None
    require_local: bool = False
    require_streaming: bool = False
    min_context_length: int = 0
    max_response_time: Optional[float] = None


class RuntimeProviderManager:
    """
    Manager for runtime provider switching and selection.
    
    Features:
    - Runtime provider switching without restart
    - Configuration reloading
    - Provider health monitoring
    - Intelligent provider selection
    - Request type-based routing
    """
    
    def __init__(self, health_check_interval: int = 300):
        self.config_manager = get_provider_config_manager()
        self.health_check_interval = health_check_interval
        
        # Runtime state
        self._provider_health: Dict[str, ProviderHealthStatus] = {}
        self._active_providers: Set[str] = set()
        self._health_check_lock = threading.RLock()
        self._selection_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 60  # Cache selection results for 1 minute
        
        # Event handlers
        self._provider_change_handlers: List[Callable[[str, ProviderConfig], None]] = []
        self._health_change_handlers: List[Callable[[str, ProviderHealthStatus], None]] = []
        
        # Background health checking
        self._health_check_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # Initialize
        self._initialize_provider_health()
        self._register_config_change_listener()

    @staticmethod
    def canonicalize_provider_id(provider_name: Optional[str]) -> Optional[str]:
        return ProviderRegistryService.canonicalize_provider_id(provider_name)

    def get_runtime_fallback_chain(self) -> List[str]:
        configured = os.getenv("KAREN_RUNTIME_FALLBACK_CHAIN", "")
        if configured.strip():
            canonical = [self.canonicalize_provider_id(p) for p in configured.split(",")]
            normalized = [p for p in canonical if p]
            if normalized:
                return normalized
        return ["builtin_vllm", "ollama", "builtin_transformers", "fallback"]
    
    # ---------- Provider Switching ----------
    
    def switch_provider(self, provider_name: str, validate: bool = True) -> bool:
        """
        Switch to a different provider at runtime.
        
        Args:
            provider_name: Name of the provider to switch to
            validate: Whether to validate provider before switching
            
        Returns:
            True if switch was successful
        """
        try:
            # Get provider configuration
            config = self.config_manager.get_provider(provider_name)
            if not config:
                logger.error(f"Provider {provider_name} not found")
                return False
            
            if not config.enabled:
                logger.error(f"Provider {provider_name} is disabled")
                return False
            
            # Validate provider if requested
            if validate:
                health_status = self.check_provider_health(provider_name)
                if not health_status.is_available:
                    logger.error(f"Provider {provider_name} is not available: {health_status.error_message}")
                    return False
            
            # Enable the provider
            self.config_manager.enable_provider(provider_name)
            
            # Add to active providers
            self._active_providers.add(provider_name)
            
            # Notify handlers
            self._notify_provider_change_handlers(provider_name, config)
            
            logger.info(f"Successfully switched to provider: {provider_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to switch to provider {provider_name}: {e}")
            return False
    
    def enable_provider(self, provider_name: str) -> bool:
        """Enable a provider at runtime"""
        try:
            success = self.config_manager.enable_provider(provider_name)
            if success:
                self._active_providers.add(provider_name)
                
                # Trigger health check
                asyncio.create_task(self._check_provider_health_async(provider_name))
                
                logger.info(f"Enabled provider: {provider_name}")
            return success
        except Exception as e:
            logger.error(f"Failed to enable provider {provider_name}: {e}")
            return False
    
    def disable_provider(self, provider_name: str) -> bool:
        """Disable a provider at runtime"""
        try:
            success = self.config_manager.disable_provider(provider_name)
            if success:
                self._active_providers.discard(provider_name)
                
                # Update health status
                if provider_name in self._provider_health:
                    self._provider_health[provider_name].status = ProviderStatus.UNAVAILABLE
                
                logger.info(f"Disabled provider: {provider_name}")
            return success
        except Exception as e:
            logger.error(f"Failed to disable provider {provider_name}: {e}")
            return False
    
    def set_provider_priority(self, provider_name: str, priority: int) -> bool:
        """Set provider priority at runtime"""
        try:
            config = self.config_manager.update_provider(provider_name, {"priority": priority})
            if config:
                # Clear selection cache since priorities changed
                self._clear_selection_cache()
                logger.info(f"Set priority for {provider_name} to {priority}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to set priority for provider {provider_name}: {e}")
            return False
    
    # ---------- Configuration Reloading ----------
    
    def reload_provider_config(self, provider_name: str) -> bool:
        """Reload a specific provider configuration"""
        try:
            success = self.config_manager.reload_provider_config(provider_name)
            if success:
                # Clear cache and trigger health check
                self._clear_selection_cache()
                asyncio.create_task(self._check_provider_health_async(provider_name))
                
                logger.info(f"Reloaded configuration for provider: {provider_name}")
            return success
        except Exception as e:
            logger.error(f"Failed to reload config for provider {provider_name}: {e}")
            return False
    
    def reload_all_configs(self) -> int:
        """Reload all provider configurations"""
        try:
            reloaded_count = self.config_manager.reload_all_configs()
            
            # Clear cache and trigger health checks
            self._clear_selection_cache()
            self._initialize_provider_health()
            
            logger.info(f"Reloaded {reloaded_count} provider configurations")
            return reloaded_count
        except Exception as e:
            logger.error(f"Failed to reload all configurations: {e}")
            return 0
    
    # ---------- Provider Health Monitoring ----------
    
    def check_provider_health(self, provider_name: str) -> ProviderHealthStatus:
        """Check health of a specific provider"""
        with self._health_check_lock:
            try:
                config = self.config_manager.get_provider(provider_name)
                if not config:
                    return ProviderHealthStatus(
                        provider_name=provider_name,
                        status=ProviderStatus.UNAVAILABLE,
                        last_check=datetime.now(),
                        error_message="Provider not found"
                    )
                
                if not config.enabled:
                    return ProviderHealthStatus(
                        provider_name=provider_name,
                        status=ProviderStatus.UNAVAILABLE,
                        last_check=datetime.now(),
                        error_message="Provider disabled"
                    )
                
                # Perform health check based on provider type
                start_time = time.time()
                health_status = self._perform_health_check(config)
                response_time = time.time() - start_time
                
                # Update health status
                health_status.response_time = response_time
                health_status.last_check = datetime.now()
                
                # Update consecutive failures
                if health_status.is_healthy:
                    health_status.consecutive_failures = 0
                    health_status.last_success = datetime.now()
                else:
                    current_health = self._provider_health.get(provider_name)
                    if current_health:
                        health_status.consecutive_failures = current_health.consecutive_failures + 1
                    else:
                        health_status.consecutive_failures = 1
                
                # Store health status
                self._provider_health[provider_name] = health_status
                
                # Notify handlers
                self._notify_health_change_handlers(provider_name, health_status)
                
                return health_status
                
            except Exception as e:
                logger.error(f"Health check failed for provider {provider_name}: {e}")
                health_status = ProviderHealthStatus(
                    provider_name=provider_name,
                    status=ProviderStatus.UNHEALTHY,
                    last_check=datetime.now(),
                    error_message=str(e)
                )
                self._provider_health[provider_name] = health_status
                return health_status
    
    def _perform_health_check(self, config: ProviderConfig) -> ProviderHealthStatus:
        """Perform actual health check for a provider"""
        
        if config.provider_type == ProviderType.LOCAL:
            # Local providers - check if service is running
            return self._check_local_provider_health(config)
        
        elif config.provider_type in [ProviderType.REMOTE, ProviderType.HYBRID]:
            # Remote providers - check API availability
            return self._check_remote_provider_health(config)
        
        else:
            return ProviderHealthStatus(
                provider_name=config.name,
                status=ProviderStatus.UNKNOWN,
                last_check=datetime.now(),
                error_message="Unknown provider type"
            )
    
    def _check_local_provider_health(self, config: ProviderConfig) -> ProviderHealthStatus:
        """Check health of local provider"""
        try:
            canonical_name = self.canonicalize_provider_id(config.name)
            if canonical_name in ("builtin_vllm",):
                # Check if local model files exist for these specific runtimes
                try:
                    from ai_karen_engine.core.model_runtime.model_store import ModelStore
                    model_store = ModelStore()
                    local_models = model_store.scan_local_models()
                    
                    if local_models:
                        return ProviderHealthStatus(
                            provider_name=config.name,
                            status=ProviderStatus.HEALTHY,
                            last_check=datetime.now(),
                            capabilities_verified=config.capabilities
                        )
                    else:
                        return ProviderHealthStatus(
                            provider_name=config.name,
                            status=ProviderStatus.DEGRADED,
                            last_check=datetime.now(),
                            error_message="No local models found"
                        )
                except ImportError:
                    return ProviderHealthStatus(
                        provider_name=config.name,
                        status=ProviderStatus.UNAVAILABLE,
                        last_check=datetime.now(),
                        error_message="Model store not available"
                    )
            
            elif canonical_name == "builtin_transformers":
                # Transformers is assumed healthy if library is available
                # It can auto-download models if needed
                try:
                    import transformers
                    return ProviderHealthStatus(
                        provider_name=config.name,
                        status=ProviderStatus.HEALTHY,
                        last_check=datetime.now(),
                        capabilities_verified=config.capabilities
                    )
                except ImportError:
                    return ProviderHealthStatus(
                        provider_name=config.name,
                        status=ProviderStatus.UNAVAILABLE,
                        last_check=datetime.now(),
                        error_message="Transformers library not installed"
                    )
            
            else:
                return ProviderHealthStatus(
                    provider_name=config.name,
                    status=ProviderStatus.HEALTHY,
                    last_check=datetime.now(),
                    error_message="Local provider assumed healthy"
                )
                
        except Exception as e:
            return ProviderHealthStatus(
                provider_name=config.name,
                status=ProviderStatus.UNHEALTHY,
                last_check=datetime.now(),
                error_message=str(e)
            )
    
    def _check_remote_provider_health(self, config: ProviderConfig) -> ProviderHealthStatus:
        """Check health of remote provider"""
        try:
            import requests
            
            # Prepare headers
            headers = {"User-Agent": "Kari-AI/1.0"}
            
            # Add authentication if required
            if config.authentication.type == AuthenticationType.API_KEY:
                api_key = self.config_manager.get_api_key(config.name)
                if api_key:
                    if config.name == "gemini":
                        # Gemini uses query parameter
                        pass
                    else:
                        headers[config.authentication.api_key_header] = f"{config.authentication.api_key_prefix} {api_key}"
                elif config.authentication.api_key_env_var:
                    return ProviderHealthStatus(
                        provider_name=config.name,
                        status=ProviderStatus.UNAVAILABLE,
                        last_check=datetime.now(),
                        error_message="API key not configured"
                    )
            
            # Build health check URL
            if config.authentication.validation_endpoint:
                url = f"{config.endpoint.base_url}{config.authentication.validation_endpoint}"
            else:
                url = f"{config.endpoint.base_url}{config.endpoint.health_endpoint}"
            
            # Add API key to URL for Gemini
            if config.name == "gemini" and config.authentication.type == AuthenticationType.API_KEY:
                api_key = self.config_manager.get_api_key(config.name)
                if api_key:
                    url += f"?key={api_key}"
            
            # Make health check request
            response = requests.get(
                url,
                headers=headers,
                timeout=config.authentication.validation_timeout
            )
            
            if response.status_code == 200:
                return ProviderHealthStatus(
                    provider_name=config.name,
                    status=ProviderStatus.HEALTHY,
                    last_check=datetime.now(),
                    capabilities_verified=config.capabilities
                )
            elif response.status_code == 401:
                return ProviderHealthStatus(
                    provider_name=config.name,
                    status=ProviderStatus.UNAVAILABLE,
                    last_check=datetime.now(),
                    error_message="Authentication failed"
                )
            elif response.status_code == 429:
                return ProviderHealthStatus(
                    provider_name=config.name,
                    status=ProviderStatus.DEGRADED,
                    last_check=datetime.now(),
                    error_message="Rate limited"
                )
            else:
                return ProviderHealthStatus(
                    provider_name=config.name,
                    status=ProviderStatus.UNHEALTHY,
                    last_check=datetime.now(),
                    error_message=f"HTTP {response.status_code}"
                )
                
        except requests.exceptions.Timeout:
            return ProviderHealthStatus(
                provider_name=config.name,
                status=ProviderStatus.UNHEALTHY,
                last_check=datetime.now(),
                error_message="Request timeout"
            )
        except requests.exceptions.ConnectionError:
            return ProviderHealthStatus(
                provider_name=config.name,
                status=ProviderStatus.UNAVAILABLE,
                last_check=datetime.now(),
                error_message="Connection failed"
            )
        except Exception as e:
            return ProviderHealthStatus(
                provider_name=config.name,
                status=ProviderStatus.UNHEALTHY,
                last_check=datetime.now(),
                error_message=str(e)
            )
    
    async def _check_provider_health_async(self, provider_name: str) -> ProviderHealthStatus:
        """Async wrapper for health check"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.check_provider_health, provider_name)
    
    def get_provider_health(self, provider_name: str) -> Optional[ProviderHealthStatus]:
        """Get cached health status for a provider"""
        return self._provider_health.get(provider_name)
    
    def get_all_provider_health(self) -> Dict[str, ProviderHealthStatus]:
        """Get health status for all providers"""
        return self._provider_health.copy()
    
    # ---------- Provider Selection ----------
    
    def select_provider(self, criteria: ProviderSelectionCriteria) -> Optional[str]:
        """
        Select the best provider based on criteria.
        
        Args:
            criteria: Selection criteria
            
        Returns:
            Name of selected provider or None if no suitable provider found
        """
        # Check cache first
        cache_key = self._get_selection_cache_key(criteria)
        cached_result = self._selection_cache.get(cache_key)
        if cached_result and time.time() - cached_result["timestamp"] < self._cache_ttl:
            return cached_result["provider"]
        
        try:
            # Get available providers
            available_providers = self._get_available_providers(criteria)
            
            if not available_providers:
                logger.warning(f"No available providers for request type: {criteria.request_type}")
                return None
            
            # Score and rank providers
            scored_providers = self._score_providers(available_providers, criteria)
            
            if not scored_providers:
                logger.warning(f"No suitable providers for criteria: {criteria}")
                return None
            
            # Select best provider
            best_provider = scored_providers[0]["name"]
            
            # Cache result
            self._selection_cache[cache_key] = {
                "provider": best_provider,
                "timestamp": time.time()
            }
            
            logger.debug(f"Selected provider {best_provider} for {criteria.request_type}")
            return best_provider
            
        except Exception as e:
            logger.error(f"Provider selection failed: {e}")
            return None
    
    def _get_available_providers(self, criteria: ProviderSelectionCriteria) -> List[ProviderConfig]:
        """Get list of available providers matching basic criteria"""
        available = []
        
        for config in self.config_manager.list_providers(enabled_only=True):
            # Skip excluded providers
            if config.name in criteria.exclude_providers:
                continue
            
            # Check health status
            health = self.get_provider_health(config.name)
            if health and not health.is_available:
                continue
            
            # Check local requirement
            if criteria.require_local and config.provider_type != ProviderType.LOCAL:
                continue
            
            # Check required capabilities
            if criteria.required_capabilities:
                if not criteria.required_capabilities.issubset(config.capabilities):
                    continue
            
            # Check context length requirement
            if criteria.min_context_length > 0:
                max_context = max((m.context_length for m in config.models), default=0)
                if max_context < criteria.min_context_length:
                    continue
            
            available.append(config)
        
        return available
    
    def _score_providers(self, providers: List[ProviderConfig], criteria: ProviderSelectionCriteria) -> List[Dict[str, Any]]:
        """Score and rank providers based on criteria"""
        scored = []
        
        for config in providers:
            score = 0
            
            # Base priority score
            score += config.priority
            
            # Preferred provider bonus
            if config.name in criteria.preferred_providers:
                index = criteria.preferred_providers.index(config.name)
                score += (len(criteria.preferred_providers) - index) * 20
            
            # Request type specific scoring
            if criteria.request_type == RequestType.CODE:
                if "code" in config.capabilities:
                    score += 30
                if any("code" in m.capabilities for m in config.models):
                    score += 20
            
            elif criteria.request_type == RequestType.VISION:
                if "vision" in config.capabilities:
                    score += 30
                if any(m.supports_vision for m in config.models):
                    score += 20
            
            elif criteria.request_type == RequestType.FUNCTION_CALLING:
                if "function_calling" in config.capabilities:
                    score += 30
                if any(m.supports_functions for m in config.models):
                    score += 20
            
            # Streaming bonus
            if criteria.require_streaming:
                if "streaming" in config.capabilities:
                    score += 15
                if any(m.supports_streaming for m in config.models):
                    score += 10
            
            # Cost consideration
            if criteria.max_cost_per_1k_tokens:
                avg_cost = sum(m.cost_per_1k_tokens or 0 for m in config.models) / len(config.models)
                if avg_cost <= criteria.max_cost_per_1k_tokens:
                    score += 10
                else:
                    score -= 20
            
            # Health status bonus
            health = self.get_provider_health(config.name)
            if health:
                if health.status == ProviderStatus.HEALTHY:
                    score += 25
                elif health.status == ProviderStatus.DEGRADED:
                    score += 10
                
                # Response time bonus (faster is better)
                if health.response_time and criteria.max_response_time:
                    if health.response_time <= criteria.max_response_time:
                        score += 15
                    else:
                        score -= 10
            
            scored.append({
                "name": config.name,
                "config": config,
                "score": score
            })
        
        # Sort by score (highest first)
        scored.sort(key=lambda x: x["score"], reverse=True)
        
        return scored
    
    def _get_selection_cache_key(self, criteria: ProviderSelectionCriteria) -> str:
        """Generate cache key for selection criteria"""
        key_parts = [
            criteria.request_type.value,
            str(sorted(criteria.required_capabilities)),
            str(criteria.preferred_providers),
            str(sorted(criteria.exclude_providers)),
            str(criteria.max_cost_per_1k_tokens),
            str(criteria.require_local),
            str(criteria.require_streaming),
            str(criteria.min_context_length),
            str(criteria.max_response_time)
        ]
        return "|".join(key_parts)
    
    def _clear_selection_cache(self) -> None:
        """Clear the provider selection cache"""
        self._selection_cache.clear()
    
    # ---------- Background Health Monitoring ----------
    
    async def start_health_monitoring(self) -> None:
        """Start background health monitoring"""
        if self._health_check_task and not self._health_check_task.done():
            return
        
        self._shutdown_event.clear()
        self._health_check_task = asyncio.create_task(self._health_monitoring_loop())
        logger.info("Started background health monitoring")
    
    async def stop_health_monitoring(self) -> None:
        """Stop background health monitoring"""
        self._shutdown_event.set()
        
        if self._health_check_task:
            try:
                await asyncio.wait_for(self._health_check_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._health_check_task.cancel()
        
        logger.info("Stopped background health monitoring")
    
    async def _health_monitoring_loop(self) -> None:
        """Background health monitoring loop"""
        while not self._shutdown_event.is_set():
            try:
                # Check health of all enabled providers
                enabled_providers = self.config_manager.get_provider_names(enabled_only=True)
                
                # Run health checks concurrently
                tasks = [
                    self._check_provider_health_async(provider_name)
                    for provider_name in enabled_providers
                ]
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Wait for next check interval
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.health_check_interval
                )
                
            except asyncio.TimeoutError:
                # Normal timeout, continue loop
                continue
            except Exception as e:
                logger.error(f"Health monitoring loop error: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    # ---------- Event Handlers ----------
    
    def add_provider_change_handler(self, handler: Callable[[str, ProviderConfig], None]) -> None:
        """Add provider change event handler"""
        self._provider_change_handlers.append(handler)
    
    def remove_provider_change_handler(self, handler: Callable[[str, ProviderConfig], None]) -> None:
        """Remove provider change event handler"""
        if handler in self._provider_change_handlers:
            self._provider_change_handlers.remove(handler)
    
    def add_health_change_handler(self, handler: Callable[[str, ProviderHealthStatus], None]) -> None:
        """Add health change event handler"""
        self._health_change_handlers.append(handler)
    
    def remove_health_change_handler(self, handler: Callable[[str, ProviderHealthStatus], None]) -> None:
        """Remove health change event handler"""
        if handler in self._health_change_handlers:
            self._health_change_handlers.remove(handler)
    
    def _notify_provider_change_handlers(self, provider_name: str, config: ProviderConfig) -> None:
        """Notify provider change handlers"""
        for handler in self._provider_change_handlers:
            try:
                handler(provider_name, config)
            except Exception as e:
                logger.warning(f"Provider change handler failed: {e}")
    
    def _notify_health_change_handlers(self, provider_name: str, health_status: ProviderHealthStatus) -> None:
        """Notify health change handlers"""
        for handler in self._health_change_handlers:
            try:
                handler(provider_name, health_status)
            except Exception as e:
                logger.warning(f"Health change handler failed: {e}")
    
    # ---------- Initialization ----------
    
    def _initialize_provider_health(self) -> None:
        """Initialize provider health status"""
        enabled_providers = self.config_manager.get_provider_names(enabled_only=True)
        self._active_providers = set(enabled_providers)
        
        # Initialize health status for all providers
        for provider_name in enabled_providers:
            if provider_name not in self._provider_health:
                self._provider_health[provider_name] = ProviderHealthStatus(
                    provider_name=provider_name,
                    status=ProviderStatus.UNKNOWN,
                    last_check=datetime.now()
                )
    
    def _register_config_change_listener(self) -> None:
        """Register configuration change listener"""
        def on_config_change(provider_name: str, config: ProviderConfig) -> None:
            # Clear selection cache when config changes
            self._clear_selection_cache()
            
            # Update active providers set
            if config.enabled:
                self._active_providers.add(provider_name)
            else:
                self._active_providers.discard(provider_name)
        
        self.config_manager.add_change_listener(on_config_change)
    
    # ---------- Utility Methods ----------
    
    def get_runtime_status(self) -> Dict[str, Any]:
        """Get runtime status summary"""
        enabled_providers = self.config_manager.get_provider_names(enabled_only=True)
        healthy_providers = [
            name for name, health in self._provider_health.items()
            if health.is_healthy
        ]
        
        return {
            "total_providers": len(self.config_manager.list_providers()),
            "enabled_providers": len(enabled_providers),
            "healthy_providers": len(healthy_providers),
            "active_providers": list(self._active_providers),
            "provider_health": {
                name: {
                    "status": health.status.value,
                    "last_check": health.last_check.isoformat(),
                    "response_time": health.response_time,
                    "consecutive_failures": health.consecutive_failures
                }
                for name, health in self._provider_health.items()
            },
            "health_monitoring_active": self._health_check_task is not None and not self._health_check_task.done(),
            "cache_size": len(self._selection_cache)
        }


# Global instance
_runtime_provider_manager: Optional[RuntimeProviderManager] = None


def get_runtime_provider_manager() -> RuntimeProviderManager:
    """Get the global runtime provider manager instance"""
    global _runtime_provider_manager
    if _runtime_provider_manager is None:
        _runtime_provider_manager = RuntimeProviderManager()
    return _runtime_provider_manager


def reset_runtime_provider_manager() -> None:
    """Reset the global runtime provider manager (for testing)"""
    global _runtime_provider_manager
    if _runtime_provider_manager:
        asyncio.create_task(_runtime_provider_manager.stop_health_monitoring())
    _runtime_provider_manager = None
