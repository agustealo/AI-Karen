from __future__ import annotations

import time
import logging
import asyncio
from typing import Any

from .base import BaseExpressionEngine
from ..contracts import ExpressionResult, ExpressionTask
from ...model_runtime.provider_policy import evaluate_provider_policy

logger = logging.getLogger(__name__)


class BuiltinProviderEngine(BaseExpressionEngine):
    """
    Engine that uses first-party vLLM or Transformers runtimes.
    Strictly limited to 'vllm' and 'transformers' providers.
    """
    engine_id = "builtin"

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        started = time.perf_counter()
        payload = self._build_payload(task)

        providers_to_try = ["builtin_vllm", "builtin_transformers", "fallback"]
        pref = str(task.preferred_provider or "").lower()
        if "transformers" in pref:
            providers_to_try = ["builtin_transformers", "builtin_vllm", "fallback"]
        elif "vllm" in pref:
            providers_to_try = ["builtin_vllm", "builtin_transformers", "fallback"]

        text = ""
        actual_provider = None
        model = None
        attempts = []
        skipped = []

        prompt = self._extract_prompt(payload["messages"])

        for idx, provider_id in enumerate(providers_to_try):
            attempt_start = time.perf_counter()
            model_id = payload.get("model")
            if model_id == "auto":
                 model_id = None
            
            try:
                decision = evaluate_provider_policy(provider_id)
                if decision.classification != "builtin_engine":
                    skipped.append({"provider": provider_id, "reason": "not_builtin"})
                    continue

                from ai_karen_engine.integrations.llm_registry import get_provider
                provider = get_provider(provider_id, model=model_id)
                if not provider:
                    attempts.append({"provider": provider_id, "model": model_id, "status": "failed", "error_type": "provider_not_found", "latency_ms": (time.perf_counter()-attempt_start)*1000})
                    continue

                if hasattr(provider, "generate_text_async"):
                    out = await provider.generate_text_async(prompt, **payload)
                elif hasattr(provider, "generate_text"):
                    loop = asyncio.get_running_loop()
                    out = await loop.run_in_executor(None, lambda: provider.generate_text(prompt, **payload))
                else:
                    loop = asyncio.get_running_loop()
                    out = await loop.run_in_executor(None, lambda: provider.generate(prompt, **payload))

                resp_text = str(out or "").strip()
                if not resp_text:
                    attempts.append({"provider": provider_id, "model": model_id, "status": "failed", "error_type": "empty_response", "latency_ms": (time.perf_counter()-attempt_start)*1000})
                    continue

                text = resp_text
                actual_provider = provider_id
                model = getattr(provider, "model", model_id)
                attempts.append({"provider": provider_id, "model": str(model or model_id or "auto"), "status": "success", "latency_ms": (time.perf_counter()-attempt_start)*1000})
                break
            except Exception as exc:
                attempts.append({"provider": provider_id, "model": model_id, "status": "failed", "error_type": type(exc).__name__, "error_message": str(exc), "latency_ms": (time.perf_counter()-attempt_start)*1000})

        runtime_engine = "vllm" if actual_provider == "builtin_vllm" else ("transformers" if actual_provider == "builtin_transformers" else None)
        degraded = not bool(text.strip())
        fallback_level = 0
        if actual_provider and pref and pref != "auto" and actual_provider != pref:
            fallback_level = 1

        response_source = "provider_runtime" if actual_provider and fallback_level == 0 else ("fallback_provider_runtime" if actual_provider else "emergency_static")

        metadata = {
            "requested_provider": task.preferred_provider,
            "requested_model": task.preferred_model,
            "actual_provider": actual_provider,
            "actual_model": str(model) if model else None,
            "runtime_engine": runtime_engine,
            "response_source": response_source,
            "fallback_level": fallback_level if actual_provider else 99,
            "degraded_mode": degraded or fallback_level > 0,
            "degradation_type": None if actual_provider and fallback_level == 0 else ("provider_unavailable" if actual_provider else "fallback_exhausted"),
            "degradation_reason": None if actual_provider and fallback_level == 0 else (f"{pref} failed; {actual_provider} generated the response." if actual_provider else "No built-in provider could generate a response."),
            "provider_attempts": attempts,
        }

        return ExpressionResult(
            task_id=task.task_id,
            text=text,
            provider=actual_provider,
            model=str(model) if model else None,
            engine_id=self.engine_id,
            engine_mode="builtin_provider_engine",
            runtime_engine=runtime_engine,
            response_source=response_source,
            attempts=attempts,
            skipped=skipped,
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=metadata["degraded_mode"],
            degradation_reason=metadata["degradation_reason"],
            metadata=metadata,
        )

    def _extract_prompt(self, messages: list[dict[str, str]]) -> str:
        """Helper to extract a simple prompt from messages."""
        if not messages:
            return ""
        return messages[-1].get("content", "")

    def _build_payload(self, task: ExpressionTask) -> dict[str, Any]:
        return {
            "messages": task.messages,
            "provider": task.preferred_provider,
            "model": task.preferred_model,
            "max_tokens": task.max_tokens,
            "temperature": task.temperature,
            "timeout_ms": task.timeout_ms,
        }
