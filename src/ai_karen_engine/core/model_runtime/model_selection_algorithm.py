from __future__ import annotations

"""
Model Selection Algorithm for Orchestration Agent

Implements 4-step model selection with provider health validation and fail-fast logic.
Requirements: 1.1, 1.2, 2.1, 2.2, 2.5
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


@dataclass
class SelectionResult:
    """Result of model selection algorithm."""
    provider: Optional[str]
    model: Optional[str]
    selection_path: str
    rationale: str
    fallback_attempts: int
    selection_log: List[str]
    health_checks_performed: int
    total_selection_time_ms: float


class ModelSelectionAlgorithm:
    """
    4-step model selection algorithm with health validation and fail-fast logic.
    
    Steps:
    1. User preference → 2. System defaults → 3. Hard fallback → 4. Degraded mode
    
    Requirements: 1.1, 1.2, 2.1, 2.2, 2.5
    """
    
    def __init__(
        self,
        provider_registry: ProviderRegistryService,
        config: Optional[Dict[str, Any]] = None
    ):
        self.provider_registry = provider_registry
        self.config = config or {}
        
        # Configuration
        self.default_hierarchy = self.config.get("default_hierarchy", [
            "builtin_vllm",
            "builtin_transformers",
        ])

        self.hard_final_fallback = self.config.get("hard_final_fallback", None)
        if not self.hard_final_fallback:
            self.hard_final_fallback = {
                "provider": "builtin_transformers",
                "model": "auto"
            }
        
        # Fail-fast configuration
        self.health_check_timeout = self.config.get("health_check_timeout", 5.0)  # seconds
        self.immediate_fallback_on_failure = self.config.get("immediate_fallback_on_failure", True)
        
    async def select_provider_and_model(
        self,
        user_preferences: Dict[str, str],
        context: Optional[Dict[str, Any]] = None
    ) -> SelectionResult:
        """
        Execute 4-step model selection with comprehensive logging.
        
        Args:
            user_preferences: Validated user preferences (provider, model)
            context: Additional context for selection decisions
            
        Returns:
            SelectionResult with provider, model, and detailed selection information
        """
        start_time = time.time()
        selection_log = []
        fallback_attempts = 0
        health_checks_performed = 0
        
        logger.info("Starting 4-step model selection algorithm")
        selection_log.append("Starting 4-step model selection algorithm")
        
        # Step 1: User preference (Requirement 1.1, 1.2)
        user_provider = user_preferences.get("provider")
        user_model = user_preferences.get("model")
        
        if user_provider:
            selection_log.append(f"Step 1: Trying user preference - {user_provider}:{user_model or 'default'}")
            logger.info(f"Step 1: Trying user preference - {user_provider}:{user_model or 'default'}")
            
            health_result = await self._check_provider_health_with_timeout(user_provider)
            health_checks_performed += 1
            
            if health_result["healthy"]:
                total_time = (time.time() - start_time) * 1000
                selection_log.append(f"✓ User preference '{user_provider}' is healthy and available")
                logger.info(f"✓ User preference '{user_provider}' selected successfully")
                
                return SelectionResult(
                    provider=user_provider,
                    model=user_model or self._get_default_model_for_provider(user_provider),
                    selection_path="user_preference",
                    rationale=f"User preferred provider '{user_provider}' is healthy and available",
                    fallback_attempts=fallback_attempts,
                    selection_log=selection_log,
                    health_checks_performed=health_checks_performed,
                    total_selection_time_ms=total_time
                )
            else:
                reason = health_result["failure_reason"]
                selection_log.append(f"✗ User preference '{user_provider}' failed: {reason}")
                logger.warning(f"✗ User preference '{user_provider}' failed: {reason}")
                fallback_attempts += 1
        else:
            selection_log.append("Step 1: No user preference specified, proceeding to system defaults")
            logger.info("Step 1: No user preference specified")
        
        # Step 2: System default hierarchy (Requirement 2.1, 2.2)
        selection_log.append(f"Step 2: Trying system default hierarchy - {self.default_hierarchy}")
        logger.info(f"Step 2: Trying system default hierarchy - {self.default_hierarchy}")
        
        for provider in self.default_hierarchy:
            selection_log.append(f"  Checking system default: {provider}")
            logger.debug(f"  Checking system default: {provider}")
            
            health_result = await self._check_provider_health_with_timeout(provider)
            health_checks_performed += 1
            
            if health_result["healthy"]:
                total_time = (time.time() - start_time) * 1000
                selection_log.append(f"✓ System default '{provider}' is healthy and available")
                logger.info(f"✓ System default '{provider}' selected successfully")
                
                return SelectionResult(
                    provider=provider,
                    model=self._get_default_model_for_provider(provider),
                    selection_path="system_defaults",
                    rationale=f"System default provider '{provider}' is healthy and available",
                    fallback_attempts=fallback_attempts,
                    selection_log=selection_log,
                    health_checks_performed=health_checks_performed,
                    total_selection_time_ms=total_time
                )
            else:
                reason = health_result["failure_reason"]
                selection_log.append(f"  ✗ System default '{provider}' failed: {reason}")
                logger.debug(f"  ✗ System default '{provider}' failed: {reason}")
                fallback_attempts += 1

        registry_fallback = self.provider_registry.select_provider_with_fallback(
            capability=None,
            fallback_chain_name="text_generation",
        )
        if registry_fallback and registry_fallback not in self.default_hierarchy:
            selection_log.append(
                f"Step 2b: Registry fallback selected - {registry_fallback}"
            )
            logger.info("Step 2b: Registry fallback selected - %s", registry_fallback)

            health_result = await self._check_provider_health_with_timeout(registry_fallback)
            health_checks_performed += 1

            if health_result["healthy"]:
                total_time = (time.time() - start_time) * 1000
                return SelectionResult(
                    provider=registry_fallback,
                    model=self._get_default_model_for_provider(registry_fallback),
                    selection_path="registry_fallback",
                    rationale=f"Registry fallback provider '{registry_fallback}' is healthy and available",
                    fallback_attempts=fallback_attempts,
                    selection_log=selection_log,
                    health_checks_performed=health_checks_performed,
                    total_selection_time_ms=total_time,
                )
            fallback_attempts += 1

        # Step 3: Hard final fallback (Requirement 2.2)
        hard_provider = self.hard_final_fallback["provider"]
        hard_model = self.hard_final_fallback["model"]
        
        selection_log.append(f"Step 3: Trying hard final fallback - {hard_provider}:{hard_model}")
        logger.info(f"Step 3: Trying hard final fallback - {hard_provider}:{hard_model}")
        
        health_result = await self._check_provider_health_with_timeout(hard_provider)
        health_checks_performed += 1
        
        if health_result["healthy"]:
            total_time = (time.time() - start_time) * 1000
            selection_log.append(f"✓ Hard fallback '{hard_provider}' is available")
            logger.info(f"✓ Hard fallback '{hard_provider}' selected successfully")
            
            return SelectionResult(
                provider=hard_provider,
                model=hard_model,
                selection_path="hard_fallback",
                rationale=f"Hard final fallback '{hard_provider}' is available",
                fallback_attempts=fallback_attempts,
                selection_log=selection_log,
                health_checks_performed=health_checks_performed,
                total_selection_time_ms=total_time
            )
        else:
            reason = health_result["failure_reason"]
            selection_log.append(f"✗ Hard fallback '{hard_provider}' failed: {reason}")
            logger.warning(f"✗ Hard fallback '{hard_provider}' failed: {reason}")
            fallback_attempts += 1
        
        # Step 4: Degraded mode (all providers failed)
        total_time = (time.time() - start_time) * 1000
        selection_log.append("Step 4: All providers failed - entering degraded mode")
        logger.error("Step 4: All providers failed - entering degraded mode")
        
        return SelectionResult(
            provider=None,
            model=None,
            selection_path="degraded_mode",
            rationale="All providers failed health checks or are unavailable",
            fallback_attempts=fallback_attempts,
            selection_log=selection_log,
            health_checks_performed=health_checks_performed,
            total_selection_time_ms=total_time
        )
    
    async def _check_provider_health_with_timeout(self, provider: str) -> Dict[str, Any]:
        """
        Check provider health using canonical provider registry status.
        """
        start_time = time.time()
        provider_status = self.provider_registry.get_provider_status(provider)
        check_time = (time.time() - start_time) * 1000
        
        if provider_status and provider_status.is_available:
            logger.debug(f"Provider {provider} health check passed in {check_time:.1f}ms")
            return {
                "healthy": True,
                "status": provider_status,
                "check_time_ms": check_time,
                "failure_reason": None
            }
        else:
            failure_reason = "not available"
            if not provider_status:
                failure_reason = "status unavailable"
            logger.debug(f"Provider {provider} health check failed in {check_time:.1f}ms: {failure_reason}")
            return {
                "healthy": False,
                "status": provider_status,
                "check_time_ms": check_time,
                "failure_reason": failure_reason
            }
    
    def _get_default_model_for_provider(self, provider: str) -> Optional[str]:
        """Get the default model for a given provider."""
        if provider in {"builtin_vllm", "builtin_transformers"}:
            return "auto"
        try:
            # Try to get from provider registry first
            provider_info = self.provider_registry.base_registry.get_provider_info(provider)
            if provider_info and provider_info.default_model:
                return provider_info.default_model
            
            # Fallback to centralized config defaults
            from ai_karen_engine.config.config_manager import get_provider_defaults
            default_models = get_provider_defaults()
            return default_models.get(provider)
            
        except Exception as e:
            logger.debug(f"Could not get default model for provider {provider}: {e}")
            return None
    
    def get_selection_statistics(self) -> Dict[str, Any]:
        """Get statistics about recent selection operations."""
        # This could be enhanced to track selection patterns over time
        return {
            "algorithm_version": "1.0",
            "default_hierarchy": self.default_hierarchy,
            "hard_final_fallback": self.hard_final_fallback,
            "health_check_timeout": self.health_check_timeout,
            "immediate_fallback_enabled": self.immediate_fallback_on_failure
        }
