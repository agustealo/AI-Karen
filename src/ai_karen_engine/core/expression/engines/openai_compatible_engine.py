from __future__ import annotations

import time
import logging
from typing import Any

from .base import BaseExpressionEngine
from ..contracts import ExpressionResult, ExpressionTask
from ...model_runtime.provider_policy import evaluate_provider_policy, normalize_provider_id

logger = logging.getLogger(__name__)


class OpenAICompatibleEngine(BaseExpressionEngine):
    """
    Engine that routes to external local servers or remote cloud APIs
    using the existing provider/model system.
    """

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        started = time.perf_counter()
        
        # Determine engine category from ID
        # self.engine_id is set during registry instantiation (local or cloud)
        is_cloud = self.engine_id == "cloud"
        
        # Get all configured providers and filter by category
        from ai_karen_engine.core.model_runtime import get_provider_registry_service
        registry = get_provider_registry_service()
        
        # Find best provider for this engine category
        provider_id = self._resolve_provider(task, is_cloud, registry)
        if not provider_id:
             return self._failure_result(task, started, "no_suitable_provider_found")

        model = task.preferred_model
        if model == "auto":
             model = None
        
        try:
            # Use central registry to get the provider instance
            from ai_karen_engine.integrations.llm_registry import get_provider
            
            # Resolve endpoint settings from registry
            from ai_karen_engine.core.model_runtime import get_provider_registry_service
            registry_service = get_provider_registry_service()
            endpoint = registry_service.get_provider_endpoint(provider_id)
            
            # Get provider instance. Central registry handles API key resolution from 
            # environment or encrypted secrets if not explicitly passed.
            provider = get_provider(
                provider_id, 
                model=model,
                base_url=endpoint.base_url if endpoint else None
            )
            
            if not provider:
                return self._failure_result(task, started, f"provider_not_found:{provider_id}")

            prompt = self._extract_prompt(task.messages)
            
            # Check if generate_text_async exists, fallback to generate_text or generate
            if hasattr(provider, "generate_text_async"):
                 text = await provider.generate_text_async(prompt, messages=task.messages, max_tokens=task.max_tokens, temperature=task.temperature)
            elif hasattr(provider, "generate_text"):
                 # Offload sync call
                 import asyncio
                 loop = asyncio.get_running_loop()
                 text = await loop.run_in_executor(None, lambda: provider.generate_text(prompt, messages=task.messages, max_tokens=task.max_tokens, temperature=task.temperature))
            else:
                 # Generic generate
                 import asyncio
                 loop = asyncio.get_running_loop()
                 text = await loop.run_in_executor(None, lambda: provider.generate(prompt, **{"messages": task.messages, "max_tokens": task.max_tokens, "temperature": task.temperature}))
            
            actual_provider = provider_id
            actual_model = getattr(provider, "model", model)
            attempts = []
            skipped = []
        except Exception as exc:
            logger.error(f"OpenAICompatibleEngine ({self.engine_id}) failed for {provider_id}: {exc}")
            return self._failure_result(task, started, str(exc), provider=provider_id)

        return ExpressionResult(
            task_id=task.task_id,
            text=text,
            provider=actual_provider,
            model=str(actual_model) if actual_model else None,
            engine_id=self.engine_id,
            engine_mode="openai_compatible",
            runtime_engine="openai_compatible",
            response_source=f"{self.engine_id}_engine",
            attempts=attempts,
            skipped=skipped,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=not bool(text.strip()),
            degradation_reason=None if text.strip() else "empty_response",
        )

    def _resolve_provider(self, task: ExpressionTask, is_cloud: bool, registry: Any) -> str | None:
        """Finds the best healthy provider matching the engine category."""
        target_class = "external_provider_option" if is_cloud else "local_provider_option"
        
        # Get current policy settings
        from ..settings import get_expression_settings
        expr_settings = get_expression_settings()
        external_enabled = expr_settings.policies.allow_external_engines
        
        # 1. Try preferred provider if it matches category
        if task.preferred_provider:
            decision = evaluate_provider_policy(
                task.preferred_provider,
                local_enabled=True,
                external_enabled=external_enabled
            )
            if decision.classification == target_class:
                return decision.provider
        
        # 2. Find any healthy provider in this category
        for p_id in registry.get_all_provider_names():
            decision = evaluate_provider_policy(
                p_id,
                local_enabled=True,
                external_enabled=external_enabled
            )
            if decision.classification == target_class:
                # Check health
                status = registry.get_provider_status(p_id)
                if status and status.is_available:
                    return p_id
                    
        return None

    def _failure_result(self, task: ExpressionTask, started: float, reason: str, provider: str = "unknown") -> ExpressionResult:
        return ExpressionResult(
            task_id=task.task_id,
            text="",
            provider=provider,
            model=task.preferred_model,
            engine_id=self.engine_id,
            engine_mode="openai_compatible",
            runtime_engine="openai_compatible",
            response_source=f"{self.engine_id}_engine",
            attempts=[],
            skipped=[],
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=True,
            degradation_reason=reason,
        )

    def _extract_prompt(self, messages: list[dict[str, str]]) -> str:
        """Helper to extract a simple prompt from messages."""
        if not messages:
            return ""
        return messages[-1].get("content", "")
