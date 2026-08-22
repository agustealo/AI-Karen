"""
KIRE-KRO Integration Module - Production Wiring

This module integrates:
- KIRE (Kari Intelligent Routing Engine) for LLM selection
- KRO (Kari Reasoning Orchestrator) for explicit specialized subflows
- Model Discovery Engine for comprehensive model awareness
- CUDA Acceleration Engine for GPU offloading
- Content Optimization Engine for response improvement
- OSIRIS logging for observability

This provides a single entry point for production-grade AI-Karen request processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from ai_karen_engine.monitoring.kire_metrics import (
    KIRE_ADVISORY_OUTCOMES_TOTAL,
    KRO_SPECIALIZED_PATH_TOTAL,
)
from ai_karen_engine.routing.decision_logger import get_decision_logger
from ai_karen_engine.routing.types import RouteDecision
from ai_karen_engine.core.cortex.runtime_policy import RuntimePolicyDecision
from ai_karen_engine.agent_medusa.agent_medusa_node import medusa_node

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


@dataclass
class IntegrationConfig:
    """Configuration for KIRE-KRO integration."""

    enable_kire_routing: bool = True
    enable_cuda_acceleration: bool = True
    enable_content_optimization: bool = True
    enable_model_discovery: bool = True
    enable_degraded_mode: bool = True
    enable_metrics: bool = True
    cache_routing_decisions: bool = True
    max_concurrent_requests: int = 10
    request_timeout: float = 120.0


class KIREKROIntegration:
    """
    Production integration layer for KIRE and KRO.

    This class provides a unified interface for processing user requests through
    the complete AI-Karen pipeline with intelligent routing, reasoning, and optimization.
    """

    def __init__(self, config: Optional[IntegrationConfig] = None):
        """Initialize integration layer."""
        self.config = config or IntegrationConfig()

        # Core components
        self.kro_orchestrator = None
        self.kire_router = None
        self.model_discovery = None
        self.cuda_engine = None
        self.optimization_engine = None
        self.llm_registry = None

        # State
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._decision_logger = get_decision_logger()

        logger.info("KIRE-KRO Integration initialized")

    async def initialize(self):
        """Initialize all components asynchronously."""
        if self._initialized:
            return

        async with self._initialization_lock:
            if self._initialized:  # Double-check after acquiring lock
                return

            try:
                logger.info("Initializing KIRE-KRO integration components...")

                # Initialize canonical provider registry
                from ai_karen_engine.core.model_runtime.provider_registry_service import (
                    get_provider_registry_service,
                )

                self.llm_registry = get_provider_registry_service()

                # Check if registry has any providers
                try:
                    providers = self.llm_registry.get_all_provider_names()
                    if not providers:
                        logger.warning(
                            "⚠ Provider registry initialized but no providers are registered. "
                            "Model discovery will attempt to populate the registry."
                        )
                    else:
                        logger.info(
                            f"✓ Provider registry initialized with {len(providers)} providers"
                        )
                except Exception as e:
                    logger.warning(f"Could not check provider registry: %s", e)
                    logger.info("✓ Provider registry initialized")

                # Initialize Model Discovery
                if self.config.enable_model_discovery:
                    try:
                        from ai_karen_engine.core.model_runtime.model_discovery_service import (
                            get_model_discovery_service,
                        )

                        self.model_discovery = get_model_discovery_service()
                        await self.model_discovery.discover_all_models()
                        stats = self.model_discovery.get_discovery_statistics()
                        logger.info(
                            f"✓ Model Discovery initialized: {stats['total_models']} models discovered"
                        )

                        # Validate that at least some models were found
                        if stats.get("total_models", 0) == 0:
                            logger.warning(
                                "⚠ Model Discovery completed but found no models. "
                                "The system will operate in degraded mode. "
                                "Please ensure models are installed in the models/ directory."
                            )
                    except Exception as e:
                        logger.warning(f"Model Discovery initialization failed: {e}")

                # Initialize KIRE Router
                if self.config.enable_kire_routing:
                    try:
                        from ai_karen_engine.routing.kire_router import KIRERouter

                        self.kire_router = KIRERouter(llm_registry=self.llm_registry)
                        logger.info("✓ KIRE Router initialized")
                    except Exception as e:
                        logger.error(f"KIRE Router initialization failed: {e}")
                        raise

                # Initialize CUDA Acceleration
                if self.config.enable_cuda_acceleration:
                    try:
                        from ai_karen_engine.services.optimization.cuda_acceleration_engine import (
                            CUDAAccelerationEngine,
                        )

                        self.cuda_engine = CUDAAccelerationEngine()
                        await self.cuda_engine.initialize()
                        info = self.cuda_engine.get_cuda_info()
                        if info.available:
                            logger.info(
                                f"✓ CUDA Acceleration initialized: {info.device_count} GPU(s)"
                            )
                        else:
                            logger.info(
                                "✓ CUDA Acceleration initialized (no GPU available)"
                            )
                    except Exception as e:
                        logger.warning(f"CUDA Acceleration initialization failed: {e}")
                        self.cuda_engine = None

                # Initialize Content Optimization
                if self.config.enable_content_optimization:
                    try:
                        from ai_karen_engine.services.optimization.content_optimization_engine import (
                            ContentOptimizationEngine,
                        )

                        self.optimization_engine = ContentOptimizationEngine()
                        logger.info("✓ Content Optimization initialized")
                    except Exception as e:
                        logger.warning(
                            f"Content Optimization initialization failed: {e}"
                        )

                self._initialized = True
                logger.info("✅ KIRE-KRO integration fully initialized")

            except Exception as e:
                logger.error(
                    f"Failed to initialize KIRE-KRO integration: {e}", exc_info=True
                )
                raise

    async def process_user_request(
        self,
        user_input: str,
        user_id: str = "anon",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process a standard chat request through Karen's canonical chat runtime.

        Args:
            user_input: User's message/query
            user_id: User identifier for routing and personalization
            conversation_history: Recent conversation turns
            context: Additional context (session_id, tenant_id, etc.)

        Returns:
            Standardized response envelope shaped for KIRE/KRO-facing APIs
        """
        await self.initialize()

        try:
            from ai_karen_engine.core.langgraph_orchestrator import LangGraphOrchestrator

            t0 = time.time()
            context = dict(context or {})
            correlation_id = str(context.get("correlation_id") or uuid.uuid4())
            context["correlation_id"] = correlation_id
            conversation_id = str(
                context.get("conversation_id")
                or context.get("thread_id")
                or context.get("session_id")
                or uuid.uuid4()
            )
            session_id = (
                context.get("session_id")
                or context.get("conversation_id")
                or conversation_id
            )

            routing_advisory: Optional[Dict[str, Any]] = None
            if self.kire_router:
                try:
                    routing_advisory = await self.get_routing_decision(
                        user_input=user_input,
                        user_id=user_id,
                        task_type=context.get("task_type"),
                        context=context,
                    )
                except Exception as route_exc:
                    logger.debug(f"KIRE advisory routing unavailable: {route_exc}")

            policy_decision = RuntimePolicyDecision.from_cortex(
                context.get("cortex_policy"),
                correlation_id=correlation_id,
            )
            runtime_context = {
                "source": "kire_kro_integration",
                "channel": context.get("channel", "kro"),
                "conversation_history": conversation_history or [],
                "kire_routing_advisory": routing_advisory,
                "runtime_policy": policy_decision.to_telemetry_metadata(),
                **context,
            }

            final_state: Dict[str, Any]
            if policy_decision.requires_deep_reasoning:
                logger.info(
                    "langgraph_started",
                    extra=policy_decision.to_telemetry_metadata(),
                )
                orchestrator = LangGraphOrchestrator()
                final_state = await orchestrator.process(
                    messages=[HumanMessage(content=user_input)],
                    user_id=user_id,
                    session_id=session_id,
                    config={
                        "runtime_context": runtime_context,
                        "conversation_history": conversation_history or [],
                        "streaming_enabled": bool(
                            context.get("streaming_enabled", False)
                        ),
                        "runtime_policy": policy_decision.to_telemetry_metadata(),
                    },
                )
            else:
                logger.info(
                    "langgraph_skipped",
                    extra=policy_decision.to_telemetry_metadata(),
                )
                final_state = {
                    "response": "Processed successfully.",
                    "execution_path": "direct_chat",
                    "correlation_id": correlation_id,
                }

            if policy_decision.requires_medusa:
                logger.info(
                    "medusa_started",
                    extra=policy_decision.to_telemetry_metadata(),
                )
                final_state = await medusa_node(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "session_id": session_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "runtime_policy": policy_decision,
                        **final_state,
                    }
                )
            else:
                logger.info(
                    "medusa_skipped",
                    extra=policy_decision.to_telemetry_metadata(),
                )

            elapsed_seconds = time.time() - t0

            response_text = (
                final_state.get("formatted_response")
                or final_state.get("llm_response")
                or final_state.get("response")
                or "Processed successfully."
            )
            if isinstance(response_text, dict):
                response_text = response_text.get("final") or response_text.get("response") or str(response_text)
            if not isinstance(response_text, str):
                response_text = str(response_text)

            final_metadata = {
                "provider": final_state.get("selected_provider"),
                "model": final_state.get("selected_model"),
                "confidence": float(final_state.get("intent_confidence") or 0.0),
                "tokens_used": final_state.get("execution_metrics", {}).get("tokens_used")
                if isinstance(final_state.get("execution_metrics"), dict)
                else None,
            }

            advisory_decision = self._route_decision_from_advisory(routing_advisory)
            routing_outcome = self._determine_routing_outcome(
                advisory_provider=advisory_decision.provider
                if advisory_decision
                else None,
                advisory_model=advisory_decision.model if advisory_decision else None,
                final_provider=final_metadata.get("provider"),
                final_model=final_metadata.get("model"),
            )
            KIRE_ADVISORY_OUTCOMES_TOTAL.labels(
                outcome=routing_outcome,
                final_status="degraded" if final_state.get("degraded_mode") else "completed",
                execution_path=final_state.get("execution_path", "langgraph"),
            ).inc()
            self._decision_logger.log_outcome(
                correlation_id,
                user_id,
                context.get("task_type", "chat"),
                outcome=routing_outcome,
                final_status="degraded" if final_state.get("degraded_mode") else "completed",
                execution_path=final_state.get("execution_path"),
                advisory_decision=advisory_decision,
                final_provider=final_metadata.get("provider"),
                final_model=final_metadata.get("model"),
                metadata={
                    "assistant_message_id": final_state.get("assistant_message_id"),
                    "degraded": bool(final_state.get("degraded_mode")),
                },
            )

            response_dict = {
                "success": True,
                "message": response_text,
                "meta": {
                    "timestamp": datetime.now().isoformat(),
                    "agent": "LangGraphOrchestrator",
                    "confidence": final_metadata.get("confidence", 0.0),
                    "latency_ms": round(elapsed_seconds * 1000, 2),
                    "tokens_used": final_metadata.get("tokens_used"),
                    "provider": final_metadata.get("provider"),
                    "model": final_metadata.get("model"),
                    "degraded_mode": bool(final_state.get("degraded_mode")),
                    "status": "degraded" if final_state.get("degraded_mode") else "completed",
                    "execution_path": final_state.get("execution_path", "standard"),
                    "assistant_message_id": final_state.get("assistant_message_id"),
                    "correlation_id": final_state.get("correlation_id", correlation_id),
                },
                "routing": routing_advisory,
                "structured_content": final_state.get("structured_content"),
                "actions": final_state.get("actions"),
                "telemetry": final_state.get("telemetry"),
                "error": final_state.get("errors", [None])[-1] if final_state.get("errors") else None,
            }
            response_dict["_integration"] = {
                "authority": "chat_orchestrator",
                "kire_enabled": self.config.enable_kire_routing,
                "kro_specialized_available": bool(self.kro_orchestrator),
                "routing_advisory_used": bool(routing_advisory),
                "routing_outcome": routing_outcome,
                "correlation_id": correlation_id,
            }
            return response_dict

        except Exception as e:
            logger.error(f"Request processing failed: {e}", exc_info=True)

            # Return error response
            return {
                "success": False,
                "error": str(e),
                "message": "I apologize, but I encountered an error processing your request. Please try again.",
                "meta": {
                    "timestamp": "",
                    "agent": "ChatOrchestrator",
                    "confidence": 0.0,
                    "degraded_mode": True,
                },
            }

    async def process_specialized_request(
        self,
        user_input: str,
        user_id: str = "anon",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an explicit KRO-native specialized flow.

        This path is intentionally out-of-band from Karen's standard chat lifecycle.
        """
        await self.initialize()
        kro = await self._get_or_create_kro_orchestrator()
        ctx = dict(context or {})
        corr_id = str(ctx.get("correlation_id") or uuid.uuid4())
        ctx["correlation_id"] = corr_id
        ctx["kro_specialized"] = True

        response, ui_message = await kro.process_request(
            user_input=user_input,
            user_id=user_id,
            conversation_history=conversation_history,
            ui_context=ctx,
            correlation_id=corr_id,
        )

        response_dict = self._kro_response_to_dict(response)
        response_dict["success"] = True
        response_dict["message"] = ui_message
        response_dict["_integration"] = {
            "authority": "kro_specialized",
            "standard_chat_authority": "chat_orchestrator",
            "correlation_id": corr_id,
            "specialized_flow": True,
        }
        return response_dict

    @staticmethod
    def _route_decision_from_advisory(
        routing_advisory: Optional[Dict[str, Any]],
    ) -> Optional[RouteDecision]:
        """Rebuild a RouteDecision from a serialized advisory payload when available."""
        if not routing_advisory or routing_advisory.get("error"):
            return None
        provider = routing_advisory.get("provider")
        model = routing_advisory.get("model")
        if not provider or not model:
            return None
        return RouteDecision(
            provider=provider,
            model=model,
            reasoning=routing_advisory.get("reasoning", ""),
            confidence=float(routing_advisory.get("confidence", 0.0)),
            fallback_chain=list(routing_advisory.get("fallback_chain", [])),
            metadata=dict(routing_advisory.get("metadata", {})),
        )

    @staticmethod
    def _determine_routing_outcome(
        *,
        advisory_provider: Optional[str],
        advisory_model: Optional[str],
        final_provider: Optional[str],
        final_model: Optional[str],
    ) -> str:
        """Classify whether KIRE advisory routing was used or overridden downstream."""
        if not advisory_provider or not advisory_model:
            return "unavailable"
        if advisory_provider == final_provider and advisory_model == final_model:
            return "used"
        if final_provider or final_model:
            return "overridden"
        return "missing_final"

    def _kro_response_to_dict(self, kro_response) -> Dict[str, Any]:
        """Convert KRO response dataclass to dictionary."""
        try:
            # Use dataclasses.asdict if available
            from dataclasses import asdict

            return asdict(kro_response)
        except Exception:
            # Manual conversion fallback
            return {
                "meta": {
                    "timestamp": kro_response.meta.timestamp,
                    "agent": kro_response.meta.agent,
                    "confidence": kro_response.meta.confidence,
                    "latency_ms": kro_response.meta.latency_ms,
                    "tokens_used": kro_response.meta.tokens_used,
                    "provider": kro_response.meta.provider,
                    "model": kro_response.meta.model,
                    "degraded_mode": kro_response.meta.degraded_mode,
                },
                "classification": {
                    "intent": kro_response.classification.intent.value,
                    "category": kro_response.classification.category.value,
                    "sentiment": kro_response.classification.sentiment.value,
                    "style": kro_response.classification.style.value,
                    "importance": kro_response.classification.importance,
                    "keywords": kro_response.classification.keywords,
                },
                "reasoning_summary": kro_response.reasoning_summary,
                "plan": [
                    {
                        "step": step.step,
                        "action": step.action,
                        "detail": step.detail,
                        "name": step.name,
                        "args": step.args,
                        "why": step.why,
                    }
                    for step in kro_response.plan
                ],
                "evidence": [
                    {
                        "source": ev.source,
                        "type": ev.type,
                        "hash": ev.hash,
                        "snippet": ev.snippet,
                    }
                    for ev in kro_response.evidence
                ],
                "memory_writes": [
                    {
                        "text": mem.text,
                        "tags": mem.tags,
                        "ttl": mem.ttl,
                    }
                    for mem in kro_response.memory_writes
                ],
                "ui": kro_response.ui,
                "telemetry": {
                    "tools_called": [
                        {
                            "name": tool.name,
                            "ok": tool.ok,
                            "latency_ms": tool.latency_ms,
                            "error": tool.error,
                        }
                        for tool in kro_response.telemetry.tools_called
                    ],
                    "errors": kro_response.telemetry.errors,
                    "notes": kro_response.telemetry.notes,
                },
                "suggestions": kro_response.suggestions,
            }

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of all available models."""
        await self.initialize()

        if not self.model_discovery:
            # Fallback to LLM registry
            providers = self.llm_registry.list_providers()
            return [
                {
                    "provider": p,
                    "models": [
                        self.llm_registry.get_provider(p).get("default_model", "auto")
                    ],
                    "status": "available",
                }
                for p in providers
            ]

        # Use comprehensive model discovery
        models = self.model_discovery.get_discovered_models()
        return [
            {
                "id": model.id,
                "name": model.display_name,
                "provider": model.type.value,
                "category": model.category.value,
                "capabilities": model.capabilities,
                "status": model.status.value,
                "size_gb": model.size / (1024**3),
                "modalities": [mod.type.value for mod in model.modalities],
            }
            for model in models
        ]

    async def get_routing_decision(
        self,
        user_input: str,
        user_id: str = "anon",
        task_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Get routing decision without executing the full request."""
        await self.initialize()

        if not self.kire_router:
            return {"error": "KIRE routing not available"}

        try:
            from ai_karen_engine.routing.types import RouteRequest

            route_req = RouteRequest(
                user_id=user_id,
                query=user_input,
                task_type=task_type or "chat",
                context=context or {},
            )

            decision = await self.kire_router.route_provider_selection(route_req)

            return {
                "provider": decision.provider,
                "model": decision.model,
                "reasoning": decision.reasoning,
                "confidence": decision.confidence,
                "fallback_chain": decision.fallback_chain,
                "metadata": decision.metadata,
            }

        except Exception as e:
            logger.error(f"Routing decision failed: {e}")
            return {"error": str(e)}

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        await self.initialize()

        status = {
            "initialized": self._initialized,
            "components": {
                "kro_orchestrator": bool(self.kro_orchestrator),
                "kro_specialized_supported": self._can_initialize_kro(),
                "kire_router": bool(self.kire_router),
                "llm_registry": bool(self.llm_registry),
                "model_discovery": bool(self.model_discovery),
                "cuda_engine": bool(self.cuda_engine),
                "optimization_engine": bool(self.optimization_engine),
            },
            "config": {
                "kire_routing": self.config.enable_kire_routing,
                "cuda_acceleration": self.config.enable_cuda_acceleration,
                "content_optimization": self.config.enable_content_optimization,
                "model_discovery": self.config.enable_model_discovery,
            },
        }

        # Add CUDA info if available
        if self.cuda_engine:
            try:
                cuda_info = self.cuda_engine.get_cuda_info()
                status["cuda"] = {
                    "available": cuda_info.available,
                    "device_count": cuda_info.device_count,
                    "total_memory_gb": cuda_info.total_memory / (1024**3)
                    if cuda_info.total_memory
                    else 0,
                }
            except Exception:
                status["cuda"] = {"available": False}

        # Add model discovery stats if available
        if self.model_discovery:
            try:
                stats = self.model_discovery.get_discovery_statistics()
                status["models"] = stats
            except Exception:
                pass

        # Add LLM registry info
        if self.llm_registry:
            try:
                providers = self.llm_registry.list_providers()
                status["providers"] = {
                    "count": len(providers),
                    "names": providers,
                }
            except Exception:
                pass

        return status

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on all components."""
        try:
            await self.initialize()

            health = {
                "status": "healthy",
                "components": {},
            }

            # KRO is specialized-only and should not degrade standard chat when idle.
            if self.kro_orchestrator:
                health["components"]["kro"] = "initialized_specialized"
            elif self._can_initialize_kro():
                health["components"]["kro"] = "available_on_demand"
            else:
                health["components"]["kro"] = "unavailable"

            # Check KIRE
            if self.kire_router:
                health["components"]["kire"] = "healthy"
            else:
                health["components"]["kire"] = "unavailable"
                health["status"] = "degraded"

            # Check LLM Registry
            if self.llm_registry:
                try:
                    providers = self.llm_registry.list_providers()
                    healthy_providers = sum(
                        1
                        for p in providers
                        if self.llm_registry.health_check(p).get("status") == "healthy"
                    )
                    health["components"]["llm_registry"] = (
                        f"{healthy_providers}/{len(providers)} healthy"
                    )
                except Exception:
                    health["components"]["llm_registry"] = "error"
                    health["status"] = "degraded"

            # Check CUDA
            if self.cuda_engine:
                try:
                    cuda_info = self.cuda_engine.get_cuda_info()
                    health["components"]["cuda"] = (
                        "available" if cuda_info.available else "unavailable"
                    )
                except Exception:
                    health["components"]["cuda"] = "error"

            return health

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    def _can_initialize_kro(self) -> bool:
        """Return whether the integration has enough dependencies for specialized KRO use."""
        return self.llm_registry is not None and self.kire_router is not None

    async def _get_or_create_kro_orchestrator(self):
        """Lazily instantiate the specialized KRO orchestrator only when explicitly needed."""
        if self.kro_orchestrator is not None:
            return self.kro_orchestrator
        if not self._can_initialize_kro():
            raise RuntimeError("KRO specialized orchestrator is not available")

        from ai_karen_engine.core.reasoning.kro_orchestrator import KROOrchestrator

        self.kro_orchestrator = KROOrchestrator(
            llm_registry=self.llm_registry,
            kire_router=self.kire_router,
            enable_cuda=bool(self.cuda_engine),
            enable_optimization=bool(self.optimization_engine),
        )
        logger.info("✓ KRO Orchestrator initialized on demand for specialized flow")
        return self.kro_orchestrator


# ===================================
# FACTORY FUNCTIONS
# ===================================

_integration_instance = None


def get_integration() -> KIREKROIntegration:
    """Get singleton integration instance."""
    global _integration_instance
    if _integration_instance is None:
        _integration_instance = KIREKROIntegration()
    return _integration_instance


async def initialize_integration(config: Optional[IntegrationConfig] = None):
    """Initialize the integration layer."""
    integration = get_integration()
    if config:
        integration.config = config
    await integration.initialize()
    return integration


# ===================================
# CONVENIENCE FUNCTIONS
# ===================================


async def process_request(
    user_input: str,
    user_id: str = "anon",
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convenience function to process a request through the integrated system."""
    integration = get_integration()
    return await integration.process_user_request(
        user_input=user_input,
        user_id=user_id,
        conversation_history=conversation_history,
        context=context,
    )


async def get_available_models() -> List[Dict[str, Any]]:
    """Convenience function to get all available models."""
    integration = get_integration()
    return await integration.get_available_models()


async def get_system_status() -> Dict[str, Any]:
    """Convenience function to get system status."""
    integration = get_integration()
    return await integration.get_system_status()


async def health_check() -> Dict[str, Any]:
    """Convenience function to perform health check."""
    integration = get_integration()
    return await integration.health_check()
