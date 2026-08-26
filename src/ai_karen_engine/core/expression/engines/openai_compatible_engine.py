from __future__ import annotations

import logging
import time
from typing import Any

from .base import BaseExpressionEngine
from ..contracts import ExpressionResult, ExpressionTask
from ...model_runtime.provider_execution import execute_provider_endpoint
from ...model_runtime.provider_policy import evaluate_provider_policy
from ...model_runtime.runtime_engine import EndpointKind

logger = logging.getLogger(__name__)


class OpenAICompatibleEngine(BaseExpressionEngine):
    """Execute canonical OpenAI-compatible provider endpoints.

    Concrete provider identity belongs to the provider registry. This engine is
    intentionally provider-agnostic and accepts both first-party local endpoint
    registrations and tenant/config-defined custom OpenAI-compatible endpoints.
    """

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        started = time.perf_counter()
        is_cloud = self.engine_id == "cloud"

        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )

        registry = get_provider_registry_service()
        requested_provider = str(task.preferred_provider or "auto").strip() or "auto"
        requested_model = task.preferred_model
        provider_id = self._resolve_provider(task, is_cloud, registry)
        if not provider_id:
            return self._failure_result(
                task,
                started,
                "no_suitable_provider_found",
                requested_provider=requested_provider,
            )

        endpoint = registry.get_provider_endpoint(provider_id)
        if endpoint is None:
            return self._failure_result(
                task,
                started,
                f"provider_endpoint_not_found:{provider_id}",
                provider=provider_id,
                requested_provider=requested_provider,
            )

        model = task.preferred_model
        if model == "auto":
            model = None

        attempt_started = time.perf_counter()
        try:
            execution = await execute_provider_endpoint(
                endpoint,
                messages=task.messages,
                model=model,
                max_tokens=task.max_tokens,
                temperature=task.temperature,
            )
            text = execution.text
            actual_provider = execution.provider_id
            actual_model = execution.model
            runtime_engine = execution.runtime_engine or "openai_compatible"
        except Exception as exc:
            logger.error(
                "OpenAICompatibleEngine (%s) failed for %s: %s",
                self.engine_id,
                provider_id,
                exc,
            )
            return self._failure_result(
                task,
                started,
                str(exc),
                provider=provider_id,
                requested_provider=requested_provider,
                attempts=[
                    {
                        "provider": provider_id,
                        "model": model or requested_model,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "latency_ms": (time.perf_counter() - attempt_started) * 1000,
                    }
                ],
            )

        has_text = bool(text and text.strip())
        explicit_request = requested_provider.lower() not in {"", "auto"}
        fallback_level = (
            1
            if explicit_request
            and not self._provider_ids_equivalent(
                requested_provider,
                actual_provider,
                registry,
            )
            else 0
        )
        degraded = not has_text or fallback_level > 0
        response_source = (
            "provider_runtime"
            if has_text and fallback_level == 0
            else "fallback_provider_runtime"
            if has_text
            else "model_unavailable"
        )
        degradation_reason = (
            "empty_response"
            if not has_text
            else (
                f"Requested provider {requested_provider} was unavailable; "
                f"{actual_provider} generated the response."
                if fallback_level > 0
                else None
            )
        )
        attempts = [
            {
                "provider": actual_provider,
                "model": actual_model or model or requested_model,
                "status": "success" if has_text else "empty",
                "latency_ms": (time.perf_counter() - attempt_started) * 1000,
            }
        ]
        metadata = {
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "runtime_engine": runtime_engine,
            "response_source": response_source,
            "fallback_level": fallback_level,
            "degraded_mode": degraded,
            "degradation_type": (
                "provider_fallback"
                if fallback_level > 0
                else "empty_response"
                if not has_text
                else None
            ),
            "degradation_reason": degradation_reason,
            "provider_attempts": attempts,
        }

        return ExpressionResult(
            task_id=task.task_id,
            text=text,
            provider=actual_provider,
            model=actual_model,
            engine_id=self.engine_id,
            engine_mode="openai_compatible",
            runtime_engine=runtime_engine,
            response_source=response_source,
            attempts=attempts,
            skipped=[],
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=degraded,
            degradation_reason=degradation_reason,
            metadata=metadata,
        )

    def _resolve_provider(
        self, task: ExpressionTask, is_cloud: bool, registry: Any
    ) -> str | None:
        """Find the best healthy provider matching the engine category."""
        required_caps = {"chat_completion", "text_generation"}
        preferred = str(task.preferred_provider or "").strip()

        if preferred and preferred.lower() != "auto":
            preferred_candidates = [preferred]
            canonicalize = getattr(registry, "canonicalize_provider_id", None)
            if callable(canonicalize):
                canonical = canonicalize(preferred)
                if canonical and canonical not in preferred_candidates:
                    preferred_candidates.append(canonical)

            decision = evaluate_provider_policy(preferred)
            if decision.replacement and decision.replacement not in preferred_candidates:
                preferred_candidates.append(decision.replacement)

            for candidate_id in preferred_candidates:
                endpoint = registry.get_provider_endpoint(candidate_id)
                if endpoint is None or not endpoint.enabled:
                    continue
                if not self._matches_engine_locality(endpoint, is_cloud):
                    continue
                cap_lower = {capability.lower() for capability in endpoint.capabilities}
                if not required_caps.issubset(cap_lower):
                    continue
                status = registry.get_provider_status(candidate_id)
                if not status or status.is_available:
                    return candidate_id

        targets = registry.resolve_capable_targets(
            required_capabilities=required_caps,
            healthy_only=True,
        )
        targets = [
            target
            for target in targets
            if self._matches_engine_locality(target, is_cloud)
        ]
        return targets[0].provider_id if targets else None

    @staticmethod
    def _matches_engine_locality(endpoint: Any, is_cloud: bool) -> bool:
        if is_cloud:
            return endpoint.kind == EndpointKind.CLOUD_PROVIDER
        return endpoint.kind != EndpointKind.CLOUD_PROVIDER

    @staticmethod
    def _provider_ids_equivalent(
        requested_provider: str,
        actual_provider: str | None,
        registry: Any,
    ) -> bool:
        if not actual_provider:
            return False
        requested = requested_provider.strip()
        actual = actual_provider.strip()
        if requested == actual:
            return True

        canonicalize = getattr(registry, "canonicalize_provider_id", None)
        if callable(canonicalize):
            requested_canonical = canonicalize(requested)
            actual_canonical = canonicalize(actual)
            if requested_canonical and requested_canonical == actual_canonical:
                return True
        return False

    def _failure_result(
        self,
        task: ExpressionTask,
        started: float,
        reason: str,
        provider: str = "unknown",
        requested_provider: str | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> ExpressionResult:
        requested = requested_provider or str(task.preferred_provider or "auto")
        attempt_list = attempts or []
        metadata = {
            "requested_provider": requested,
            "requested_model": task.preferred_model,
            "actual_provider": None,
            "actual_model": None,
            "runtime_engine": None,
            "response_source": "model_unavailable",
            "fallback_level": 99,
            "degraded_mode": True,
            "degradation_type": "fallback_exhausted",
            "degradation_reason": reason,
            "provider_attempts": attempt_list,
        }
        return ExpressionResult(
            task_id=task.task_id,
            text="",
            provider=None,
            model=task.preferred_model,
            engine_id=self.engine_id,
            engine_mode="openai_compatible",
            runtime_engine=None,
            response_source="model_unavailable",
            attempts=attempt_list,
            skipped=[],
            latency_ms=(time.perf_counter() - started) * 1000,
            degraded=True,
            degradation_reason=reason,
            metadata=metadata,
        )
