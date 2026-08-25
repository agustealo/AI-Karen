from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .base import BaseExpressionEngine
from ..contracts import ExpressionResult, ExpressionTask
from ...model_runtime.provider_execution import get_provider_execution_registry
from ...model_runtime.provider_policy import evaluate_provider_policy
from ...model_runtime.provider_registry_service import get_provider_registry_service
from ...model_runtime.runtime_engine import EndpointKind

logger = logging.getLogger(__name__)


class OpenAICompatibleEngine(BaseExpressionEngine):
    """Route to OpenAI-compatible endpoints through Core-owned runtime ports."""

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        started = time.perf_counter()
        is_cloud = self.engine_id == "cloud"

        registry = get_provider_registry_service()
        execution_registry = get_provider_execution_registry()

        provider_id = self._resolve_provider(task, is_cloud, registry)
        if not provider_id:
            return self._failure_result(task, started, "no_suitable_provider_found")

        model = task.preferred_model
        if model == "auto":
            model = None

        try:
            endpoint = registry.get_provider_endpoint(provider_id)
            provider = execution_registry.create_provider(
                provider_id,
                model=model,
                base_url=endpoint.base_url if endpoint else None,
            )

            if not provider:
                reason = (
                    "provider_execution_not_configured"
                    if not execution_registry.is_configured()
                    else f"provider_not_found:{provider_id}"
                )
                return self._failure_result(task, started, reason, provider=provider_id)

            prompt = self._extract_prompt(task.messages)
            generation_kwargs = {
                "messages": task.messages,
                "max_tokens": task.max_tokens,
                "temperature": task.temperature,
            }

            if hasattr(provider, "generate_text_async"):
                text = await provider.generate_text_async(
                    prompt,
                    **generation_kwargs,
                )
            elif hasattr(provider, "generate_text"):
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None,
                    lambda: provider.generate_text(prompt, **generation_kwargs),
                )
            else:
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None,
                    lambda: provider.generate(prompt, **generation_kwargs),
                )

            actual_provider = provider_id
            actual_model = getattr(provider, "model", model)
            attempts: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
        except Exception as exc:
            logger.exception(
                "OpenAICompatibleEngine (%s) failed for %s",
                self.engine_id,
                provider_id,
            )
            return self._failure_result(
                task,
                started,
                str(exc),
                provider=provider_id,
            )

        text_value = str(text or "")
        return ExpressionResult(
            task_id=task.task_id,
            text=text_value,
            provider=actual_provider,
            model=str(actual_model) if actual_model else None,
            engine_id=self.engine_id,
            engine_mode="openai_compatible",
            runtime_engine="openai_compatible",
            response_source=f"{self.engine_id}_engine",
            attempts=attempts,
            skipped=skipped,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=not bool(text_value.strip()),
            degradation_reason=None if text_value.strip() else "empty_response",
        )

    def _resolve_provider(
        self,
        task: ExpressionTask,
        is_cloud: bool,
        registry: Any,
    ) -> str | None:
        """Find the best healthy provider matching the engine category."""
        required_caps = {"chat_completion", "text_generation"}

        preferred = str(task.preferred_provider or "").strip().lower()
        if preferred and preferred != "auto":
            decision = evaluate_provider_policy(preferred)
            endpoint = registry.get_provider_endpoint(decision.provider)
            if endpoint and endpoint.enabled:
                cap_lower = {c.lower() for c in endpoint.capabilities}
                if required_caps.issubset(cap_lower):
                    status = registry.get_provider_status(decision.provider)
                    if not status or status.is_available:
                        return decision.provider

        targets = registry.resolve_capable_targets(
            required_capabilities=required_caps,
            healthy_only=True,
        )
        if is_cloud:
            targets = [t for t in targets if t.kind == EndpointKind.CLOUD_PROVIDER]
        else:
            targets = [t for t in targets if t.kind != EndpointKind.CLOUD_PROVIDER]

        return targets[0].provider_id if targets else None

    def _failure_result(
        self,
        task: ExpressionTask,
        started: float,
        reason: str,
        provider: str = "unknown",
    ) -> ExpressionResult:
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

    @staticmethod
    def _extract_prompt(messages: list[dict[str, str]]) -> str:
        """Extract the final user-visible content for legacy provider adapters."""
        if not messages:
            return ""
        return messages[-1].get("content", "")
