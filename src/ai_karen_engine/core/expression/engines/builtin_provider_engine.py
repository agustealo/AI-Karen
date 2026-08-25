from __future__ import annotations

import logging
import time
from typing import Any

from .base import BaseExpressionEngine
from ..contracts import ExpressionResult, ExpressionTask
from ...model_runtime.provider_execution import execute_provider_endpoint
from ...model_runtime.provider_policy import evaluate_provider_policy

logger = logging.getLogger(__name__)


class BuiltinProviderEngine(BaseExpressionEngine):
    """Execute text generation through first-party local model runtimes.

    Provider selection remains owned by the canonical Core registry. Execution
    uses Core-owned endpoint protocols rather than importing integration/plugin
    implementations back into the AI machine.
    """

    engine_id = "builtin"

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        started = time.perf_counter()
        prompt = self._extract_prompt(task.messages)

        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )

        registry = get_provider_registry_service()
        required_caps = {"chat_completion", "text_generation"}
        preferred = str(task.preferred_provider or "").strip().lower()

        endpoint = registry.select_best_target(
            required_capabilities=required_caps,
            kind=None,
            preferred_target_id=preferred if preferred else None,
            healthy_only=True,
        )

        attempts: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        text = ""
        actual_provider: str | None = None
        model: str | None = None
        runtime_engine: str | None = None

        if not endpoint:
            return self._failure_result(
                task,
                started,
                "no_capable_builtin_target",
                attempts=attempts,
                skipped=skipped,
            )

        provider_ids = [endpoint.provider_id]
        capable_ids = [
            item.provider_id
            for item in registry.resolve_capable_targets(
                required_caps, healthy_only=True
            )
        ]
        for fallback_id in ("builtin_vllm", "lmstudio-desktop", "llamacpp-server", "ollama-local"):
            if fallback_id in capable_ids and fallback_id not in provider_ids:
                provider_ids.append(fallback_id)

        for provider_id in provider_ids:
            attempt_start = time.perf_counter()
            model_id = task.preferred_model
            if model_id == "auto":
                model_id = None

            try:
                decision = evaluate_provider_policy(provider_id)
                if decision.classification != "builtin_engine" and provider_id == endpoint.provider_id:
                    skipped.append({"provider": provider_id, "reason": "not_builtin"})
                    continue

                target = registry.get_provider_endpoint(provider_id)
                if target is None:
                    attempts.append(
                        {
                            "provider": provider_id,
                            "model": model_id,
                            "status": "failed",
                            "error_type": "provider_endpoint_not_found",
                            "latency_ms": (time.perf_counter() - attempt_start) * 1000,
                        }
                    )
                    continue

                execution = await execute_provider_endpoint(
                    target,
                    messages=task.messages,
                    model=model_id,
                    max_tokens=task.max_tokens,
                    temperature=task.temperature,
                )
                text = execution.text
                actual_provider = execution.provider_id
                model = execution.model
                runtime_engine = execution.runtime_engine
                attempts.append(
                    {
                        "provider": actual_provider,
                        "model": model or model_id or "auto",
                        "status": "success",
                        "latency_ms": (time.perf_counter() - attempt_start) * 1000,
                    }
                )
                break
            except Exception as exc:
                attempts.append(
                    {
                        "provider": provider_id,
                        "model": model_id,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "latency_ms": (time.perf_counter() - attempt_start) * 1000,
                    }
                )

        degraded = not bool(text)
        fallback_level = 0
        if actual_provider and preferred and preferred != "auto" and actual_provider != preferred:
            fallback_level = 1

        response_source = (
            "provider_runtime"
            if actual_provider and fallback_level == 0
            else "fallback_provider_runtime"
            if actual_provider
            else "model_unavailable"
        )
        degradation_reason = (
            None
            if actual_provider and fallback_level == 0
            else f"{preferred} failed; {actual_provider} generated the response."
            if actual_provider
            else "No built-in provider could generate a response."
        )

        metadata = {
            "requested_provider": task.preferred_provider,
            "requested_model": task.preferred_model,
            "actual_provider": actual_provider,
            "actual_model": model,
            "runtime_engine": runtime_engine,
            "response_source": response_source,
            "fallback_level": fallback_level if actual_provider else 99,
            "degraded_mode": degraded or fallback_level > 0,
            "degradation_type": (
                None
                if actual_provider and fallback_level == 0
                else "provider_unavailable"
                if actual_provider
                else "fallback_exhausted"
            ),
            "degradation_reason": degradation_reason,
            "provider_attempts": attempts,
        }

        return ExpressionResult(
            task_id=task.task_id,
            text=text,
            provider=actual_provider,
            model=model,
            engine_id=self.engine_id,
            engine_mode="builtin_provider_engine",
            runtime_engine=runtime_engine,
            response_source=response_source,
            attempts=attempts,
            skipped=skipped,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=metadata["degraded_mode"],
            degradation_reason=degradation_reason,
            metadata=metadata,
        )

    @staticmethod
    def _extract_prompt(messages: list[dict[str, str]]) -> str:
        if not messages:
            return ""
        return messages[-1].get("content", "")

    def _failure_result(
        self,
        task: ExpressionTask,
        started: float,
        reason: str,
        attempts: list[dict[str, Any]] | None = None,
        skipped: list[dict[str, Any]] | None = None,
    ) -> ExpressionResult:
        return ExpressionResult(
            task_id=task.task_id,
            text="",
            provider=None,
            model=task.preferred_model,
            engine_id=self.engine_id,
            engine_mode="builtin_provider_engine",
            runtime_engine=None,
            response_source="model_unavailable",
            attempts=attempts or [],
            skipped=skipped or [],
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=True,
            degradation_reason=reason,
            metadata={
                "requested_provider": task.preferred_provider,
                "requested_model": task.preferred_model,
                "actual_provider": None,
                "actual_model": None,
                "runtime_engine": None,
                "response_source": "model_unavailable",
                "fallback_level": 99,
                "degraded_mode": True,
                "degradation_type": "fallback_exhausted",
                "degradation_reason": reason,
                "provider_attempts": attempts or [],
            },
        )
