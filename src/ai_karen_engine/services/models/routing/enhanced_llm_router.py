"""
Enhanced LLM Router - Unified Routing System

This module consolidates all routing functionality from:
- services/llm_router.py (canonical)
- integrations/llm_router.py (policy-based routing)
- routing/kire_router.py (cognitive reasoning)

Provides unified routing with policy-based selection, cognitive reasoning,
and comprehensive fallback strategies.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

from ai_karen_engine.config.llm_provider_config import (
    get_openai_compatible_provider_defaults,
)

from ai_karen_engine.core.operations.routing_decision_persistence import (
    RoutingDecisionPersistence,
    get_routing_persistence,
)
from ai_karen_engine.integrations.llm_registry import get_registry, LLMRegistry
from ai_karen_engine.integrations.llm_utils import LLMProviderBase
from ai_karen_engine.services.cache import MemoryCache, get_request_deduplicator
from ai_karen_engine.core.runtime.degraded_mode import (
    get_degraded_mode_manager,
    DegradedModeReason,
)
from ai_karen_engine.routing.types import RouteRequest, RouteDecision
from ai_karen_engine.routing.profile_resolver import ProfileResolver
from ai_karen_engine.routing.decision_logger import DecisionLogger
from ai_karen_engine.routing.cognitive_reasoner import (
    CognitiveReasoner,
    RoutingCognition,
)

logger = logging.getLogger(__name__)


@dataclass
class TaskAnalysis:
    """Minimal stub for legacy routing compatibility."""

    task_type: str = "chat"
    required_capabilities: List[str] = field(default_factory=list)
    tool_intents: List[str] = field(default_factory=list)
    hints: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    user_need_state: Dict[str, Any] = field(default_factory=dict)


def _analyze_task(query: str, context: Optional[Dict[str, Any]] = None) -> TaskAnalysis:
    """Lightweight task analysis stub for legacy routing."""
    return TaskAnalysis(task_type="chat")

try:  # pragma: no cover - SecretManager may require optional deps
    from ai_karen_engine.models.secret_manager import SecretManager
except Exception:  # pragma: no cover - gracefully handle missing optional dependency
    SecretManager = None  # type: ignore[assignment]

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional
    yaml = None  # type: ignore

try:
    from prometheus_client import Counter, Histogram

    METRICS_ENABLED = True
except Exception:  # pragma: no cover - optional
    METRICS_ENABLED = False

    class _DummyMetric:
        def labels(self, **kwargs):
            return self

        def inc(self, n: int = 1):
            pass

        def observe(self, v: float):
            pass

    Counter = Histogram = _DummyMetric


class RoutingPolicy(str, Enum):
    """Routing policies for different use cases"""

    PRIVACY_FIRST = "privacy_first"
    PERFORMANCE_FIRST = "performance_first"
    COST_OPTIMIZED = "cost_optimized"
    QUALITY_FIRST = "quality_first"
    BALANCED = "balanced"
    LOCAL_FIRST = "local_first"
    INTERACTIVE = "interactive"
    BATCH = "batch"


class RuntimeLevel(str, Enum):
    """Runtime execution levels"""

    FULL = "FULL"
    REDUCED = "REDUCED"
    SAFE = "SAFE"
    EMERGENCY = "EMERGENCY"


@dataclass
class EnhancedChatRequest:
    """Enhanced chat request with routing context"""

    message: str
    context: Dict[str, Any]
    tools: Optional[List[str]] = None
    memory_context: Optional[str] = None
    user_preferences: Optional[Dict[str, Any]] = None
    preferred_model: Optional[str] = None
    conversation_id: Optional[str] = None
    stream: bool = False
    routing_policy: RoutingPolicy = RoutingPolicy.BALANCED
    runtime_level: RuntimeLevel = RuntimeLevel.FULL
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class EnhancedRouteDecision:
    """Enhanced route decision with cognitive reasoning"""

    provider: str
    model: str
    confidence: float
    reasoning: str
    cost_estimate: Optional[float] = None
    latency_estimate: Optional[float] = None
    policy_applied: RoutingPolicy = RoutingPolicy.BALANCED
    runtime_level: RuntimeLevel = RuntimeLevel.FULL
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class EnhancedLLMRouter:
    """Enhanced LLM router with unified routing capabilities"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.registry = get_registry()
        self.profile_resolver = ProfileResolver()
        self.decision_logger = DecisionLogger()
        self.cognitive_reasoner = CognitiveReasoner()
        self.degraded_mode_manager = get_degraded_mode_manager()

        # Cache for routing decisions
        self._cache = MemoryCache(max_size=2048, default_ttl=300)
        self._cache_index: Dict[str, set] = {}
        self._provider_cache_index: Dict[str, set] = {}
        self._cache_owner: Dict[str, Dict[str, str]] = {}
        self._deduper = get_request_deduplicator()

        # Metrics
        self._request_counter = Counter(
            "llm_router_requests_total", "Total LLM router requests"
        )
        self._decision_counter = Counter(
            "llm_router_decisions_total", "Total routing decisions"
        )
        self._latency_histogram = Histogram(
            "llm_router_latency_seconds", "Router latency"
        )

        # Initialize persistence
        self._persistence = get_routing_persistence()

        logger.info("Enhanced LLM Router initialized with unified capabilities")

    async def select_provider(
        self,
        request: EnhancedChatRequest,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> Optional[EnhancedRouteDecision]:
        """
        Select optimal provider using unified routing logic

        Combines:
        - Policy-based routing from integrations/llm_router.py
        - Cognitive reasoning from routing/kire_router.py
        - Health monitoring from services/llm_router.py
        """
        start_time = time.time()
        request_hash = self._hash_request(request)

        # Check cache first
        cached_result = self._cache.get(request_hash)
        if cached_result:
            self._request_counter.inc()
            self._latency_histogram.observe(time.time() - start_time)
            return cached_result

        # Check degraded mode
        degraded_mode = self.degraded_mode_manager.get_current_mode()
        if degraded_mode != DegradedModeReason.NORMAL:
            decision = await self._get_degraded_mode_decision(request, degraded_mode)
            if decision:
                self._cache.set(request_hash, decision, ttl=60)
                return decision

        # Analyze task for routing context
        task_analysis = _analyze_task(request.message, context=request.context)

        # Apply cognitive reasoning
        cognition = await self.cognitive_reasoner.reason_routing(
            request, task_analysis, user_preferences
        )

        # Apply routing policy
        policy_decision = await self._apply_routing_policy(
            request, task_analysis, cognition, user_preferences
        )

        # Validate provider health
        healthy_providers = await self._get_healthy_providers(request)

        # Select final provider
        final_decision = await self._select_final_provider(
            policy_decision, healthy_providers, request, task_analysis
        )

        # Cache the result
        if final_decision:
            self._cache.set(request_hash, final_decision, ttl=300)

        # Log the decision
        await self.decision_logger.log_decision(
            request, final_decision, task_analysis, cognition
        )

        # Update metrics
        self._request_counter.inc()
        self._decision_counter.inc()
        self._latency_histogram.observe(time.time() - start_time)

        return final_decision

    async def _get_degraded_mode_decision(
        self, request: EnhancedChatRequest, degraded_mode: DegradedModeReason
    ) -> Optional[EnhancedRouteDecision]:
        """Get routing decision for degraded mode"""

        degraded_mapping = {
            DegradedModeReason.REDUCED_PERFORMANCE: ["local", "fallback"],
            DegradedModeReason.SECURITY_RESTRICTIONS: ["local", "privacy"],
            DegradedModeReason.COST_CONSTRAINTS: ["local", "cost_optimized"],
            DegradedModeReason.EMERGENCY: ["fallback", "local"],
        }

        allowed_providers = degraded_mapping.get(degraded_mode, ["fallback"])

        for provider in allowed_providers:
            models = await self.registry.get_models_for_provider(provider)
            if models:
                return EnhancedRouteDecision(
                    provider=provider,
                    model=models[0],
                    confidence=0.8,
                    reasoning=f"Degraded mode: {degraded_mode.value}",
                    policy_applied=RoutingPolicy.LOCAL_FIRST,
                    runtime_level=request.runtime_level,
                    metadata={"degraded_mode": degraded_mode.value},
                )

        return None

    async def _apply_routing_policy(
        self,
        request: EnhancedChatRequest,
        task_analysis: TaskAnalysis,
        cognition: RoutingCognition,
        user_preferences: Optional[Dict[str, Any]],
    ) -> EnhancedRouteDecision:
        """Apply routing policy based on request context"""

        # Determine routing policy
        if request.routing_policy != RoutingPolicy.BALANCED:
            policy = request.routing_policy
        elif user_preferences and "routing_policy" in user_preferences:
            policy = RoutingPolicy(user_preferences["routing_policy"])
        else:
            # Auto-detect policy based on task analysis
            policy = self._detect_policy_from_task(task_analysis, request)

        # Apply policy logic
        if policy == RoutingPolicy.PRIVACY_FIRST:
            return await self._apply_privacy_first_policy(request, task_analysis)
        elif policy == RoutingPolicy.PERFORMANCE_FIRST:
            return await self._apply_performance_first_policy(request, task_analysis)
        elif policy == RoutingPolicy.COST_OPTIMIZED:
            return await self._apply_cost_optimized_policy(request, task_analysis)
        elif policy == RoutingPolicy.QUALITY_FIRST:
            return await self._apply_quality_first_policy(request, task_analysis)
        elif policy == RoutingPolicy.LOCAL_FIRST:
            return await self._apply_local_first_policy(request, task_analysis)
        elif policy == RoutingPolicy.INTERACTIVE:
            return await self._apply_interactive_policy(request, task_analysis)
        elif policy == RoutingPolicy.BATCH:
            return await self._apply_batch_policy(request, task_analysis)
        else:  # BALANCED
            return await self._apply_balanced_policy(request, task_analysis, cognition)

    def _detect_policy_from_task(
        self, task_analysis: TaskAnalysis, request: EnhancedChatRequest
    ) -> RoutingPolicy:
        """Auto-detect routing policy from task characteristics"""

        # Check for privacy-sensitive content
        if task_analysis.contains_sensitive_info:
            return RoutingPolicy.PRIVACY_FIRST

        # Check for interactive vs batch processing
        if request.stream and task_analysis.is_interactive:
            return RoutingPolicy.INTERACTIVE

        # Check for cost sensitivity
        if task_analysis.cost_sensitive:
            return RoutingPolicy.COST_OPTIMIZED

        # Check for quality requirements
        if task_analysis.complexity > 0.7:
            return RoutingPolicy.QUALITY_FIRST

        # Default to balanced
        return RoutingPolicy.BALANCED

    async def _apply_privacy_first_policy(
        self, request: EnhancedChatRequest, task_analysis: TaskAnalysis
    ) -> EnhancedRouteDecision:
        """Apply privacy-first routing policy"""

        # Prefer local models for privacy
        local_models = await self.registry.get_models_for_provider("local")
        if local_models:
            return EnhancedRouteDecision(
                provider="local",
                model=local_models[0],
                confidence=0.9,
                reasoning="Privacy-first policy: local model selected",
                policy_applied=RoutingPolicy.PRIVACY_FIRST,
                runtime_level=request.runtime_level,
                metadata={"privacy_reason": "local_model"},
            )

        # Fallback to privacy-focused providers
        privacy_providers = ["local_gguf", "transformers"]
        for provider in privacy_providers:
            models = await self.registry.get_models_for_provider(provider)
            if models:
                return EnhancedRouteDecision(
                    provider=provider,
                    model=models[0],
                    confidence=0.7,
                    reasoning="Privacy-first policy: privacy-focused provider selected",
                    policy_applied=RoutingPolicy.PRIVACY_FIRST,
                    runtime_level=request.runtime_level,
                    metadata={"privacy_reason": "provider_selection"},
                )

        # Final fallback
        return await self._get_fallback_decision(request)

    async def _apply_balanced_policy(
        self,
        request: EnhancedChatRequest,
        task_analysis: TaskAnalysis,
        cognition: RoutingCognition,
    ) -> EnhancedRouteDecision:
        """Apply balanced routing policy using cognitive reasoning"""

        # Use cognitive reasoning to determine best provider
        reasoning_result = cognition.reasoning_result

        # Extract provider preference from reasoning
        provider_preference = reasoning_result.get("preferred_provider")
        model_preference = reasoning_result.get("preferred_model")

        if provider_preference:
            models = await self.registry.get_models_for_provider(provider_preference)
            if models:
                return EnhancedRouteDecision(
                    provider=provider_preference,
                    model=model_preference or models[0],
                    confidence=reasoning_result.get("confidence", 0.8),
                    reasoning=reasoning_result.get(
                        "reasoning", "Balanced policy with cognitive reasoning"
                    ),
                    policy_applied=RoutingPolicy.BALANCED,
                    runtime_level=request.runtime_level,
                    metadata={"cognitive_reasoning": reasoning_result},
                )

        # Fallback to heuristic-based selection
        return await self._apply_heuristic_balanced_policy(request, task_analysis)

    async def _apply_heuristic_balanced_policy(
        self, request: EnhancedChatRequest, task_analysis: TaskAnalysis
    ) -> EnhancedRouteDecision:
        """Apply heuristic-based balanced routing policy"""

        # Score providers based on multiple factors
        providers = await self.registry.get_all_providers()
        scored_providers = []

        for provider in providers:
            models = await self.registry.get_models_for_provider(provider)
            if not models:
                continue

            # Calculate score based on task characteristics
            score = 0.0

            # Performance score
            if task_analysis.is_interactive:
                if provider in ["openai", "anthropic"]:
                    score += 0.4
                elif provider in ["local", "transformers"]:
                    score += 0.2

            # Cost score
            if task_analysis.cost_sensitive:
                if provider in ["local", "transformers"]:
                    score += 0.3
                elif provider in ["openai", "anthropic"]:
                    score += 0.1

            # Quality score
            if task_analysis.complexity > 0.5:
                if provider in ["openai", "anthropic", "claude"]:
                    score += 0.3
                elif provider in ["local", "transformers"]:
                    score += 0.2

            # Privacy score
            if task_analysis.contains_sensitive_info:
                if provider in ["local", "local_gguf"]:
                    score += 0.4
                elif provider in ["openai", "anthropic"]:
                    score += 0.1

            scored_providers.append((provider, models[0], score))

        # Select best provider
        if scored_providers:
            scored_providers.sort(key=lambda x: x[2], reverse=True)
            provider, model, score = scored_providers[0]

            return EnhancedRouteDecision(
                provider=provider,
                model=model,
                confidence=min(score, 1.0),
                reasoning=f"Balanced policy: {provider} selected (score: {score:.2f})",
                policy_applied=RoutingPolicy.BALANCED,
                runtime_level=request.runtime_level,
                metadata={"heuristic_score": score},
            )

        return await self._get_fallback_decision(request)

    async def _get_healthy_providers(self, request: EnhancedChatRequest) -> List[str]:
        """Get list of healthy providers"""
        try:
            from ai_karen_engine.integrations.provider_status import ProviderHealth

            health_checker = ProviderHealth()
            return await health_checker.get_healthy_providers()
        except ImportError:
            # Fallback to all available providers
            providers = await self.registry.get_all_providers()
            return providers

    async def _select_final_provider(
        self,
        policy_decision: EnhancedRouteDecision,
        healthy_providers: List[str],
        request: EnhancedChatRequest,
        task_analysis: TaskAnalysis,
    ) -> Optional[EnhancedRouteDecision]:
        """Select final provider considering health and availability"""

        # Check if policy decision provider is healthy
        if policy_decision.provider in healthy_providers:
            return policy_decision

        # Find alternative healthy provider
        for provider in healthy_providers:
            models = await self.registry.get_models_for_provider(provider)
            if models:
                return EnhancedRouteDecision(
                    provider=provider,
                    model=models[0],
                    confidence=0.6,
                    reasoning=f"Provider {policy_decision.provider} unavailable, using {provider}",
                    policy_applied=policy_decision.policy_applied,
                    runtime_level=request.runtime_level,
                    metadata={"fallback_reason": "provider_unavailable"},
                )

        # Final fallback
        return await self._get_fallback_decision(request)

    async def _get_fallback_decision(
        self, request: EnhancedChatRequest
    ) -> EnhancedRouteDecision:
        """Get fallback decision"""
        return EnhancedRouteDecision(
            provider="fallback",
            model="kari-fallback-v1",
            confidence=0.3,
            reasoning="Fallback decision: no suitable provider available",
            policy_applied=RoutingPolicy.BALANCED,
            runtime_level=request.runtime_level,
            metadata={"fallback_reason": "no_suitable_provider"},
        )

    def _hash_request(self, request: EnhancedChatRequest) -> str:
        """Generate hash for request caching"""
        request_data = {
            "message": request.message,
            "context": request.context,
            "tools": request.tools,
            "routing_policy": request.routing_policy.value,
            "runtime_level": request.runtime_level.value,
            "timestamp": time.time(),
        }
        return hashlib.md5(
            json.dumps(request_data, sort_keys=True).encode()
        ).hexdigest()

    # Additional methods from original services/llm_router.py
    async def select_provider_legacy(
        self, request: ChatRequest, user_preferences: Optional[Dict[str, Any]] = None
    ) -> Optional[EnhancedRouteDecision]:
        """Legacy method for backward compatibility"""
        # Convert legacy request to enhanced request
        enhanced_request = EnhancedChatRequest(
            message=request.message,
            context=request.context,
            tools=request.tools,
            memory_context=request.memory_context,
            user_preferences=user_preferences or request.user_preferences,
            preferred_model=request.preferred_model,
            conversation_id=request.conversation_id,
            stream=request.stream,
            routing_policy=RoutingPolicy.BALANCED,
            runtime_level=RuntimeLevel.FULL,
        )

        return await self.select_provider(enhanced_request, user_preferences)


# Global router instance
_router_instance: Optional[EnhancedLLMRouter] = None


async def get_enhanced_router() -> EnhancedLLMRouter:
    """Get the enhanced LLM router instance"""
    global _router_instance

    if _router_instance is None:
        _router_instance = EnhancedLLMRouter()

    return _router_instance


async def select_provider(
    request: EnhancedChatRequest, user_preferences: Optional[Dict[str, Any]] = None
) -> Optional[EnhancedRouteDecision]:
    """Select provider using enhanced router"""
    router = await get_enhanced_router()
    return await router.select_provider(request, user_preferences)


# Legacy compatibility
from .llm_router_service import ChatRequest


async def select_provider_legacy(
    request: ChatRequest, user_preferences: Optional[Dict[str, Any]] = None
) -> Optional[EnhancedRouteDecision]:
    """Legacy method for backward compatibility"""
    router = await get_enhanced_router()
    return await router.select_provider_legacy(request, user_preferences)
