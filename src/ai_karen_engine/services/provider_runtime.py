"""Unified provider runtime service for LLM execution and fallbacks."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncIterator, TYPE_CHECKING

from ai_karen_engine.core.model_runtime.runtime_contracts import (
    ProviderRouteDecision,
    ProviderExecutionResult,
)
if TYPE_CHECKING:
    from ai_karen_engine.services.models.routing.llm_router_service import ChatRequest, LLMRouter

logger = logging.getLogger(__name__)

class ProviderRuntime:
    """
    Unified runtime for executing LLM requests based on routing decisions.
    Handles execution, retries, and fallback chains with detailed forensic tracking.
    """

    def __init__(self, router: Optional["LLMRouter"] = None):
        if router is None:
            from ai_karen_engine.services.models.routing.llm_router_service import LLMRouter
            router = LLMRouter()
        self.router = router

    @staticmethod
    def _resolve_runtime_engine(provider_name: Optional[str], provider_category: Optional[str] = None) -> Optional[str]:
        if not provider_name:
            return None

        normalized = str(provider_name).strip()
        if normalized.startswith("builtin_"):
            return normalized.removeprefix("builtin_")
        if provider_category == "builtin":
            return normalized
        return normalized

    def _resolve_actual_model(self, provider_name: Optional[str], candidate_model: Optional[str]) -> Optional[str]:
        if not provider_name:
            return None

        normalized_candidate = str(candidate_model or "").strip()
        if normalized_candidate and normalized_candidate.lower() != "auto":
            return normalized_candidate

        try:
            provider_info = self.router.registry.get_provider_info(provider_name)
        except Exception:
            provider_info = None

        if provider_info:
            if isinstance(provider_info, dict):
                resolved = self.router._effective_provider_model(provider_info)
            else:
                resolved = getattr(provider_info, "default_model", None)
            if resolved and str(resolved).strip().lower() != "auto":
                return resolved

            available_models = provider_info.get("available_models") if isinstance(provider_info, dict) else getattr(provider_info, "available_models", None)
            if isinstance(available_models, list):
                for entry in available_models:
                    if isinstance(entry, str) and entry.strip() and entry.strip().lower() != "auto":
                        return entry.strip()
                    if isinstance(entry, dict):
                        for key in ("model", "model_id", "id", "name"):
                            value = entry.get(key)
                            if isinstance(value, str) and value.strip() and value.strip().lower() != "auto":
                                return value.strip()

        return None

    @staticmethod
    def _build_emergency_result(
        *,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        correlation_id: str,
        start_time: float,
        provider_attempts: List[Dict[str, Any]],
        degraded_message: str,
    ) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            text=degraded_message,
            requested_provider=decision.requested_provider,
            requested_model=decision.requested_model,
            selected_provider=decision.selected_provider,
            selected_model=decision.selected_model,
            actual_provider=None,
            actual_model=None,
            provider_category=decision.provider_category,
            compatibility_profile=decision.compatibility_profile,
            runtime_engine=None,
            transport=decision.transport,
            response_source="emergency_static",
            fallback_level=99,
            degraded_mode=True,
            degradation_type="fallback_exhausted",
            degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
            latency_ms=(time.time() - start_time) * 1000,
            correlation_id=correlation_id,
            provider_attempts=provider_attempts,
            metadata={"source": "emergency_static", "request_message": request.message[:200]},
        )

    @staticmethod
    def _should_allow_fallback(decision: ProviderRouteDecision) -> bool:
        """Allow fallback only when the router was not executing an explicit provider/model choice."""
        requested_provider = (decision.requested_provider or "").strip()
        requested_model = (decision.requested_model or "").strip()
        selected_provider = (decision.selected_provider or "").strip()
        selected_model = (decision.selected_model or "").strip()

        if requested_provider and requested_model:
            return not (
                requested_provider == selected_provider
                and requested_model == selected_model
            )

        return True

    async def execute_chat(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> ProviderExecutionResult:
        return await self.execute(decision, request, user_preferences=user_preferences)

    async def execute(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> ProviderExecutionResult:
        """
        Execute an LLM request based on a route decision.
        If the primary provider fails, it attempts fallbacks.
        """
        correlation_id = decision.correlation_id or f"exec-{uuid.uuid4()}"
        start_time = time.time()
        provider_attempts = []
        
        current_provider = decision.selected_provider
        current_model = self._resolve_actual_model(current_provider, decision.selected_model)

        if not current_provider:
            degraded_message = await self.router._generate_degraded_fallback(request, [], reason="no_selected_provider")
            provider_attempts.append({
                "provider": None,
                "model": None,
                "status": "failed",
                "error_type": "provider_missing",
                "error_message": "No provider was selected by the router.",
                "latency_ms": 0.0,
            })
            return self._build_emergency_result(
                decision=decision,
                request=request,
                correlation_id=correlation_id,
                start_time=start_time,
                provider_attempts=provider_attempts,
                degraded_message=degraded_message or "I'm sorry, I couldn't generate a response.",
            )
        
        # Primary execution attempt
        try:
            attempt_start = time.time()
            text = ""
            captured_metadata = {}
            async for chunk in self.router._attempt_provider_with_retries(
                current_provider,
                request,
                request_id=correlation_id,
                model_name=current_model,
            ):
                if isinstance(chunk, str):
                    text += chunk
                elif isinstance(chunk, dict) and chunk.get("type") == "metadata":
                    captured_metadata.update(chunk.get("metadata") or {})
            
            latency_ms = (time.time() - start_time) * 1000
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "success",
                "latency_ms": (time.time() - attempt_start) * 1000
            })
            
            llm_metadata = captured_metadata.get("llm") or {}
            return ProviderExecutionResult(
                text=text,
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=current_provider,
                actual_model=current_model,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=decision.runtime_engine or self._resolve_runtime_engine(current_provider, decision.provider_category),
                transport=decision.transport,
                response_source="provider_runtime",
                fallback_level=decision.fallback_level,
                degraded_mode=decision.degraded_mode,
                degradation_type=decision.degradation_type,
                degradation_reason=decision.degradation_reason,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                usage=llm_metadata.get("usage") or {},
                metadata={
                    **captured_metadata,
                    "source": "primary_execution",
                    "tokens_per_second": llm_metadata.get("tokens_per_second")
                }
            )
            
        except Exception as exc:
            logger.warning(f"Primary provider {current_provider} failed: {exc}. Attempting fallbacks.")
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            if not self._should_allow_fallback(decision):
                degraded_message = await self.router._generate_degraded_fallback(
                    request,
                    [],
                    reason="explicit_provider_failure",
                )
                return self._build_emergency_result(
                    decision=decision,
                    request=request,
                    correlation_id=correlation_id,
                    start_time=start_time,
                    provider_attempts=provider_attempts,
                    degraded_message=degraded_message or "The requested provider could not generate a response.",
                )

            return await self._execute_fallback_chain(decision, request, exc, start_time, correlation_id, provider_attempts)

    async def stream_execute(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Any]:
        """
        Stream an LLM request based on a route decision.
        Handles fallbacks and yields both content chunks and final execution result.
        """
        correlation_id = decision.correlation_id or f"exec-stream-{uuid.uuid4()}"
        start_time = time.time()
        provider_attempts = []
        
        current_provider = decision.selected_provider
        current_model = self._resolve_actual_model(current_provider, decision.selected_model)

        if not current_provider:
            degraded_message = await self.router._generate_degraded_fallback(request, [], reason="no_selected_provider")
            provider_attempts.append({
                "provider": None,
                "model": None,
                "status": "failed",
                "error_type": "provider_missing",
                "error_message": "No provider was selected by the router.",
                "latency_ms": 0.0,
            })
            yield ProviderExecutionResult(
                text=degraded_message or "",
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=None,
                actual_model=None,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=None,
                transport=decision.transport,
                response_source="emergency_static",
                fallback_level=99,
                degraded_mode=True,
                degradation_type="fallback_exhausted",
                degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                latency_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                metadata={"source": "emergency_static", "request_message": request.message[:200]},
            )
            return
        
        try:
            attempt_start = time.time()
            async for chunk in self.router._attempt_provider_with_retries(
                current_provider,
                request,
                request_id=correlation_id,
                model_name=current_model,
            ):
                yield chunk
            
            latency_ms = (time.time() - start_time) * 1000
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "success",
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            yield ProviderExecutionResult(
                text="", # Content already yielded
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=current_provider,
                actual_model=current_model,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=decision.runtime_engine or self._resolve_runtime_engine(current_provider, decision.provider_category),
                transport=decision.transport,
                response_source="provider_runtime",
                fallback_level=decision.fallback_level,
                degraded_mode=decision.degraded_mode,
                degradation_type=decision.degradation_type,
                degradation_reason=decision.degradation_reason,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                metadata={"source": "primary_execution"}
            )
            
        except Exception as exc:
            logger.warning(f"Primary provider {current_provider} failed during stream: {exc}. Attempting fallbacks.")
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            if not self._should_allow_fallback(decision):
                degraded_message = await self.router._generate_degraded_fallback(
                    request,
                    [],
                    reason="explicit_provider_failure",
                )
                yield degraded_message
                yield ProviderExecutionResult(
                    text=degraded_message or "",
                    requested_provider=decision.requested_provider,
                    requested_model=decision.requested_model,
                    selected_provider=decision.selected_provider,
                    selected_model=decision.selected_model,
                    actual_provider=current_provider,
                    actual_model=current_model,
                    provider_category=decision.provider_category,
                    compatibility_profile=decision.compatibility_profile,
                    runtime_engine=self._resolve_runtime_engine(current_provider, decision.provider_category),
                    transport=decision.transport,
                    response_source="provider_failure_no_fallback",
                    fallback_level=decision.fallback_level,
                    degraded_mode=True,
                    degradation_type="requested_provider_failure",
                    degradation_reason=str(exc),
                    latency_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id,
                    provider_attempts=provider_attempts,
                    metadata={"source": "explicit_provider_failure"},
                )
                return

            fallback_providers = await self.router._get_fallback_providers(current_provider, request)
            
            for i, fallback_provider in enumerate(fallback_providers, 1):
                try:
                    fallback_info = self.router.registry.get_provider_info(fallback_provider)
                    if isinstance(fallback_info, dict):
                        fallback_candidate_model = self.router._effective_provider_model(fallback_info)
                    else:
                        fallback_candidate_model = getattr(fallback_info, "default_model", None)
                    fallback_model = self._resolve_actual_model(fallback_provider, fallback_candidate_model)
                    
                    fallback_attempt_start = time.time()
                    async for chunk in self.router._attempt_provider_with_retries(
                        fallback_provider,
                        request,
                        request_id=correlation_id,
                        model_name=fallback_model,
                    ):
                        yield chunk
                    
                    latency_ms = (time.time() - start_time) * 1000
                    provider_attempts.append({
                        "provider": fallback_provider,
                        "model": fallback_model,
                        "status": "success",
                        "latency_ms": (time.time() - fallback_attempt_start) * 1000
                    })

                    yield ProviderExecutionResult(
                        text="",
                        requested_provider=decision.requested_provider,
                        requested_model=decision.requested_model,
                        selected_provider=decision.selected_provider,
                        selected_model=decision.selected_model,
                        actual_provider=fallback_provider,
                        actual_model=fallback_model,
                        provider_category=decision.provider_category,
                        compatibility_profile=decision.compatibility_profile,
                        runtime_engine=self._resolve_runtime_engine(fallback_provider, decision.provider_category),
                        response_source="fallback_provider_runtime",
                        fallback_level=decision.fallback_level + i,
                        degraded_mode=True,
                        degradation_type="provider_fallback",
                        degradation_reason=f"primary_failed: {str(exc)}",
                        latency_ms=latency_ms,
                        correlation_id=correlation_id,
                        provider_attempts=provider_attempts,
                        metadata={"source": "fallback_execution"}
                    )
                    return
                except Exception as fall_exc:
                    provider_attempts.append({
                        "provider": fallback_provider,
                        "model": fallback_model,
                        "status": "failed",
                        "error_type": type(fall_exc).__name__,
                        "error_message": str(fall_exc),
                        "latency_ms": (time.time() - fallback_attempt_start) * 1000
                    })
                    continue
            
            # Static fallback if all else fails
            degraded_message = await self.router._generate_degraded_fallback(request, [], reason="all_failed")
            yield degraded_message
            yield ProviderExecutionResult(
                text=degraded_message,
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=None,
                actual_model=None,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=None,
                response_source="emergency_static",
                fallback_level=99,
                degraded_mode=True,
                degradation_type="fallback_exhausted",
                degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                latency_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts
            )

    async def _execute_fallback_chain(self, decision, request, primary_exc, start_time, correlation_id, provider_attempts):
        fallback_providers = await self.router._get_fallback_providers(decision.selected_provider, request)

        for i, fallback_provider in enumerate(fallback_providers, 1):
            fallback_attempt_start = time.time()
            fallback_model: Optional[str] = None
            try:
                fallback_info = self.router.registry.get_provider_info(fallback_provider)
                if isinstance(fallback_info, dict):
                    fallback_candidate_model = self.router._effective_provider_model(fallback_info)
                else:
                    fallback_candidate_model = getattr(fallback_info, "default_model", None)
                fallback_model = self._resolve_actual_model(fallback_provider, fallback_candidate_model)

                text = ""
                captured_metadata = {}
                async for chunk in self.router._attempt_provider_with_retries(
                    fallback_provider,
                    request,
                    request_id=correlation_id,
                    model_name=fallback_model,
                ):
                    if isinstance(chunk, str):
                        text += chunk
                    elif isinstance(chunk, dict) and chunk.get("type") == "metadata":
                        captured_metadata.update(chunk.get("metadata") or {})

                latency_ms = (time.time() - start_time) * 1000
                provider_attempts.append({
                    "provider": fallback_provider,
                    "model": fallback_model,
                    "status": "success",
                    "latency_ms": (time.time() - fallback_attempt_start) * 1000,
                })

                llm_metadata = captured_metadata.get("llm") or {}
                return ProviderExecutionResult(
                    text=text,
                    requested_provider=decision.requested_provider,
                    requested_model=decision.requested_model,
                    selected_provider=decision.selected_provider,
                    selected_model=decision.selected_model,
                    actual_provider=fallback_provider,
                    actual_model=fallback_model,
                    provider_category=decision.provider_category,
                    compatibility_profile=decision.compatibility_profile,
                    runtime_engine=self._resolve_runtime_engine(fallback_provider, decision.provider_category),
                    transport=decision.transport,
                    response_source="fallback_provider_runtime",
                    fallback_level=decision.fallback_level + i,
                    degraded_mode=True,
                    degradation_type="provider_fallback",
                    degradation_reason=f"primary_failed: {str(primary_exc)}",
                    latency_ms=latency_ms,
                    correlation_id=correlation_id,
                    provider_attempts=provider_attempts,
                    usage=llm_metadata.get("usage") or {},
                    metadata={
                        **captured_metadata,
                        "source": "fallback_execution",
                        "tokens_per_second": llm_metadata.get("tokens_per_second")
                    }
                )
            except Exception as fall_exc:
                provider_attempts.append({
                    "provider": fallback_provider,
                    "model": fallback_model,
                    "status": "failed",
                    "error_type": type(fall_exc).__name__,
                    "error_message": str(fall_exc),
                    "latency_ms": (time.time() - fallback_attempt_start) * 1000,
                })
                continue

        degraded_message = await self.router._generate_degraded_fallback(request, [], reason="all_failed")
        return ProviderExecutionResult(
            text=degraded_message or "I'm sorry, I'm having trouble connecting to my brain right now.",
            requested_provider=decision.requested_provider,
            requested_model=decision.requested_model,
            selected_provider=decision.selected_provider,
            selected_model=decision.selected_model,
            actual_provider=None,
            actual_model=None,
            provider_category=decision.provider_category,
            compatibility_profile=decision.compatibility_profile,
            runtime_engine=None,
            transport=decision.transport,
            response_source="emergency_static",
            fallback_level=99,
            degraded_mode=True,
            degradation_type="fallback_exhausted",
            degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
            latency_ms=(time.time() - start_time) * 1000,
            correlation_id=correlation_id,
            provider_attempts=provider_attempts,
        )
