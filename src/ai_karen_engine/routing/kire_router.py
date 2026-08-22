"""KIRE Router - intelligent LLM routing that integrates with existing LLMRegistry."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.cache import MemoryCache, get_request_deduplicator
from ai_karen_engine.monitoring.kire_metrics import (
    KIRE_CACHE_EVENTS_TOTAL,
    KIRE_DECISION_CONFIDENCE,
    KIRE_DECISIONS_TOTAL,
    KIRE_LATENCY_SECONDS,
    KIRE_PROVIDER_SELECTION_TOTAL,
)

# Use shared MemoryCache impl to align with CopilotKit infra
_cache = MemoryCache(max_size=2048, default_ttl=300)
_cache_index: Dict[str, set] = {}
_provider_cache_index: Dict[str, set] = {}
_cache_owner: Dict[str, Dict[str, str]] = {}
_deduper = get_request_deduplicator()

logger = logging.getLogger(__name__)


class TaskAnalysis:
    """Minimal stub for legacy routing compatibility."""

    def __init__(self, task_type: str = "chat", **kwargs: Any) -> None:
        self.task_type = task_type
        self.required_capabilities: List[str] = []
        self.tool_intents: List[str] = []
        self.hints: Dict[str, Any] = {}
        self.confidence: float = 0.75
        self.user_need_state: Dict[str, Any] = {}


def _analyze_task(query: str, context: Optional[Dict[str, Any]] = None) -> TaskAnalysis:
    """Lightweight task analysis stub for legacy routing."""
    return TaskAnalysis(task_type="chat")


def _provider_supports(provider: str, required_caps: List[str]) -> bool:
    """Capability check stub for legacy routing."""
    return True

from ai_karen_engine.routing.types import RouteRequest, RouteDecision
from ai_karen_engine.routing.profile_resolver import ProfileResolver
from ai_karen_engine.routing.decision_logger import DecisionLogger
from ai_karen_engine.routing.cognitive_reasoner import CognitiveReasoner, RoutingCognition

# Import existing components
try:
    from ai_karen_engine.integrations.provider_status import ProviderHealth
except ImportError:
    # Fallback if provider status not available
    class ProviderHealth:
        """Conservative provider health fallback when status integration is missing."""

        SOURCE = "fallback"
        HAS_BACKEND = False
        _warned = False

        @classmethod
        def _warn(cls) -> None:
            if cls._warned:
                return
            logger.warning(
                "Provider health integration missing; enforcing degraded routing mode"
            )
            cls._warned = True

        @staticmethod
        async def is_healthy(provider: str) -> bool:
            ProviderHealth._warn()
            return False

try:
    from ai_karen_engine.core.runtime.degraded_mode import DegradedMode
except ImportError:
    # Fallback if degraded mode not available
    class DegradedMode:
        @staticmethod
        def get_fallback_provider() -> tuple[str, str]:
            from ai_karen_engine.config.config_manager import get_default_model
            return "local_gguf", get_default_model("local_gguf")


class KIRERouter:
    """Kari Intelligent Routing Engine - integrates with existing LLMRegistry."""
    
    def __init__(self, llm_registry=None):
        from ai_karen_engine.integrations.llm_registry import LLMRegistry
        self.llm_registry = llm_registry or LLMRegistry()
        self.profile_resolver = ProfileResolver()
        self.logger = DecisionLogger()
        self.cognitive_reasoner = CognitiveReasoner()
    
    async def route_provider_selection(self, request: RouteRequest) -> RouteDecision:
        """Main routing method - returns routing decision.

        DEPRECATED: KIRE is being retired as a routing authority. Provider
        selection is owned by RuntimePolicy + ProviderRouter. This method
        remains for backward compatibility and diagnostic APIs only.
        """
        logger.warning(
            "KIRERouter.route_provider_selection is deprecated; "
            "provider selection is owned by RuntimePolicy + ProviderRouter"
        )
        t0 = time.perf_counter()
        cache_key = self._generate_cache_key(request)
        # Correlation id sourced from context if present (CopilotKit pattern)
        corr = None
        try:
            corr = (request.context or {}).get("request_metadata", {}).get("correlation_id") or (request.context or {}).get("correlation_id")
        except Exception:
            corr = None
        corr_id = corr or hashlib.md5(cache_key.encode()).hexdigest()[:10]
        
        # Emit start event
        try:
            self.logger.log_start(corr_id, request.user_id, "routing.select", {"task_type": request.task_type, "khrp_step": request.khrp_step})
        except Exception:
            pass

        # Check cache first
        cached = _cache.get(cache_key)
        if cached is not None:
            KIRE_CACHE_EVENTS_TOTAL.labels(event="hit").inc()
            return cached
        # Record cache miss
        KIRE_CACHE_EVENTS_TOTAL.labels(event="miss").inc()

        try:
            # Get user profile
            profile = self.profile_resolver.get_user_profile(request.user_id)
            assignment = self.profile_resolver.get_model_assignment(
                profile, request.task_type, request.khrp_step
            )
            # Analyze query for task hints/capabilities
            analysis = _analyze_task(request.query, context=request.context)
            cognition = self.cognitive_reasoner.evaluate(request, analysis, profile)
            task_type = request.task_type or cognition.primary_goal or analysis.task_type

            # Start from profile assignment or default config
            provider = assignment.provider if assignment else "openai"
            model = assignment.model if assignment else "gpt-4o-mini"
            chain = profile.fallback_chain if profile else ["openai", "deepseek", "local_gguf"]

            async def _decide():
                # Apply capability/constraint matching and health checks
                return await self._refine_by_requirements(
                    provider,
                    model,
                    request,
                    chain,
                    analysis.required_capabilities,
                    task_type,
                    analysis,
                    cognition,
                )

            # Deduplicate identical in-flight routing decisions (same cache key)
            provider, model, reason, conf = await _deduper.deduplicate(_decide)
        except Exception as ex:
            # DO NOT RETHROW. Instead, return a fallback that allows the system to continue.
            # This avoids "surfacing the failures" as system crashes in the UI/E2E tests.
            logger.error(f"KIRE Routing Engine internal failure: {ex}", exc_info=True)
            
            # Use safest possible fallback from degraded mode
            fallback_provider, fallback_model = DegradedMode.get_fallback_provider()
            
            decision = RouteDecision(
                provider=fallback_provider,
                model=fallback_model,
                reasoning=f"Internal routing failure ({type(ex).__name__}): {ex}. Selected emergency fallback.",
                confidence=0.55,
                fallback_chain=[],
                metadata={
                    "error": str(ex),
                    "error_type": type(ex).__name__,
                    "source": "routing_internal_failure",
                    "execution_time_ms": (time.perf_counter() - t0) * 1000,
                }
            )
            
            # Log the failure decision so it's visible in audits/metrics
            try:
                self.logger.log_decision(
                    request_id=corr_id,
                    user_id=request.user_id,
                    task_type=request.task_type,
                    khrp_step=request.khrp_step,
                    decision=decision,
                    execution_time_ms=(time.perf_counter() - t0) * 1000,
                    success=False,
                    error=str(ex)
                )
                # Metrics for failure
                KIRE_DECISIONS_TOTAL.labels(status="error", task_type=request.task_type or "chat").inc()
                KIRE_LATENCY_SECONDS.labels(task_type=request.task_type or "chat").observe((time.perf_counter() - t0))
                KIRE_PROVIDER_SELECTION_TOTAL.labels(
                    provider=decision.provider,
                    model=decision.model,
                    status="error",
                    task_type=request.task_type or "chat",
                ).inc()
            except Exception:
                pass
                
            return decision
        
        confidence_bucket = self._confidence_bucket(conf)
        reasoning_trace = reason
        if cognition.narrative and cognition.narrative not in reason:
            reasoning_trace = f"{reason}; {cognition.narrative}" if reason else cognition.narrative
        decision = RouteDecision(
            provider=provider,
            model=model,
            reasoning=reasoning_trace,
            confidence=conf,
            fallback_chain=chain,
            metadata={
                "task_type": task_type,
                "khrp_step": request.khrp_step,
                "analysis": {
                    "required_capabilities": analysis.required_capabilities,
                    "confidence": analysis.confidence,
                    "step_hint": analysis.khrp_step_hint,
                    "tool_intents": analysis.tool_intents,
                    "user_need_state": analysis.user_need_state,
                },
                "cognition": asdict(cognition),
                "confidence_bucket": confidence_bucket,
                "health_source": getattr(ProviderHealth, "SOURCE", "live"),
                "execution_time_ms": (time.perf_counter() - t0) * 1000,
            }
        )
        
        # Cache only high-confidence, non-dynamic steps
        if conf >= 0.8 and request.khrp_step not in ("evidence_gathering", "tool_execution"):
            _cache.set(cache_key, decision)
            self._register_cache_entry(cache_key, decision.provider, request.user_id)
            KIRE_CACHE_EVENTS_TOTAL.labels(event="store").inc()
        
        # Log decision
        self.logger.log_decision(
            request_id=corr_id,
            user_id=request.user_id,
            task_type=request.task_type,
            khrp_step=request.khrp_step,
            decision=decision,
            execution_time_ms=(time.perf_counter() - t0) * 1000,
            success=True
        )
        # Metrics
        try:
            KIRE_DECISIONS_TOTAL.labels(status="success", task_type=request.task_type or "chat").inc()
            KIRE_LATENCY_SECONDS.labels(task_type=request.task_type or "chat").observe((time.perf_counter() - t0))
            KIRE_PROVIDER_SELECTION_TOTAL.labels(
                provider=decision.provider,
                model=decision.model,
                status="success",
                task_type=request.task_type or "chat",
            ).inc()
            KIRE_DECISION_CONFIDENCE.labels(
                task_type=request.task_type or "chat",
                provider=decision.provider,
                model=decision.model,
            ).observe(decision.confidence)
        except Exception:
            pass
        
        return decision
    
    async def _refine_by_requirements(
        self,
        provider: str,
        model: str,
        req: RouteRequest,
        chain: List[str],
        required_caps: List[str],
        inferred_task: str,
        analysis: TaskAnalysis,
        cognition: RoutingCognition,
    ) -> tuple[str, str, str, float]:
        """Refine provider/model selection based on requirements and health."""

        reason_segments: List[str] = []

        # Ensure provider supports required capabilities or tool intents
        if not _provider_supports(provider, required_caps):
            reason_segments.append(f"{provider} lacks capabilities {required_caps}")
            for alt in chain:
                if alt == provider:
                    continue
                if _provider_supports(alt, required_caps) and await ProviderHealth.is_healthy(alt):
                    provider, model = alt, self._default_model(alt)
                    reason_segments.append(f"switching to {alt} for capabilities")
                    break

        # KHRP step-specific preferences emphasise deliberate reasoning
        if req.khrp_step in ("reasoning_core",):
            preferred = [("openai", "gpt-4o"), ("deepseek", "deepseek-chat")]
            for prov, mod in preferred:
                if await ProviderHealth.is_healthy(prov):
                    provider, model = prov, mod
                    reason_segments.append(f"reasoning_core prefers {prov}/{mod}")
                    break

        # Human-like urgency bias: escalate to reliable providers under stress
        if cognition.need_urgency == "high" and provider != "openai":
            if await ProviderHealth.is_healthy("openai"):
                provider, model = "openai", "gpt-4o"
                reason_segments.append("high urgency escalated to openai/gpt-4o")
        elif cognition.need_urgency == "elevated" and provider == "local_gguf":
            if await ProviderHealth.is_healthy("deepseek"):
                provider, model = "deepseek", "deepseek-chat"
                reason_segments.append("elevated urgency upgraded to deepseek")

        # Tool affordance routing for distributed cognition
        tool_bias = set((analysis.tool_intents or []) + (cognition.recommended_tools or []))
        if "web_browse" in tool_bias and provider not in {"openai", "huggingface"}:
            if await ProviderHealth.is_healthy("openai"):
                provider, model = "openai", "gpt-4o-mini"
                reason_segments.append("web browsing preference -> openai with tool calling")
        if "code_execution" in tool_bias and provider != "deepseek":
            if await ProviderHealth.is_healthy("deepseek"):
                provider, model = "deepseek", "deepseek-coder"
                reason_segments.append("code execution intent -> deepseek coder")

        # Task/capability-specific steering
        if "embeddings" in required_caps:
            if await ProviderHealth.is_healthy("huggingface"):
                provider, model = "huggingface", "sentence-transformers/all-MiniLM-L6-v2"
                reason_segments.append("embedding capability -> huggingface transformers")
        elif inferred_task == "summarization" and provider != "local_gguf":
            if await ProviderHealth.is_healthy("local_gguf"):
                from ai_karen_engine.config.config_manager import get_default_model
                provider, model = "local_gguf", get_default_model("local_gguf")
                reason_segments.append("summarization uses local_gguf low-latency")

        # Health gate on chosen provider
        health_source = getattr(ProviderHealth, "SOURCE", "live")
        provider_healthy = await ProviderHealth.is_healthy(provider)
        
        # Optimistic override: if this is the profile-assigned primary provider
        # and its status is unknown, allow it to proceed to avoid unnecessary fallback.
        if not provider_healthy:
            registry = self.llm_registry
            info = registry.get_provider_info(provider)
            if info and info.get("health_status", "unknown") == "unknown":
                provider_healthy = True
                reason_segments.append(f"optimistic selection for unknown-status primary {provider}")

        if not provider_healthy:
            reason_segments.append(f"{provider} reported unhealthy")
            if health_source == "fallback":
                reason = "; ".join(reason_segments + ["provider health unavailable; entering degraded mode"])
            else:
                reason = "; ".join(reason_segments + [f"{provider} unhealthy; selecting fallback"])

            for fb in chain:
                if await ProviderHealth.is_healthy(fb):
                    return fb, self._default_model(fb), reason, max(0.68, cognition.confidence * 0.8)

            degraded_provider, degraded_model = DegradedMode.get_fallback_provider()
            return degraded_provider, degraded_model, reason, 0.55

        # Apply task-specific optimizations
        if inferred_task == "code" and provider == "openai":
            if await ProviderHealth.is_healthy("deepseek"):
                reason_segments.append("code task optimized with deepseek coder")
                return "deepseek", "deepseek-coder", "; ".join(reason_segments), min(0.96, max(0.9, cognition.confidence))

        # Cost gate (simple heuristic)
        max_cost = req.requirements.get("max_cost_per_call") if req.requirements else None
        if max_cost is not None:
            est_cost = self._estimate_cost(provider, model, req)
            if est_cost is not None and est_cost > max_cost:
                for alt in chain:
                    if not await ProviderHealth.is_healthy(alt):
                        continue
                    alt_model = self._default_model(alt)
                    alt_cost = self._estimate_cost(alt, alt_model, req)
                    if alt_cost is not None and alt_cost <= max_cost:
                        reason_segments.append(
                            f"cost gate reroute {provider}/{model} -> {alt}/{alt_model}"
                        )
                        return alt, alt_model, "; ".join(reason_segments), min(0.85, cognition.confidence)
                reason_segments.append("over cost budget; honoring profile selection")
                return provider, model, "; ".join(reason_segments), min(0.78, cognition.confidence)

        base_confidence = max(0.82, min(0.95, cognition.confidence + analysis.confidence * 0.1))
        reason_segments.append(f"profile assignment for {inferred_task}")
        return provider, model, "; ".join(reason_segments), base_confidence
    
    def _default_model(self, provider: str) -> str:
        """Get default model for provider from central config."""
        from ai_karen_engine.config.config_manager import get_default_model, get_provider_defaults
        defaults = get_provider_defaults()
        return defaults.get(provider, get_default_model(provider))
    
    def _generate_cache_key(self, request: RouteRequest) -> str:
        """Generate cache key for routing request."""
        req_hash = self._stable_hash(request.requirements)[:8]
        query_fingerprint = self._stable_hash({
            "query": self._normalize_query(request.query),
            "task": request.task_type,
        })[:8]
        context_signature = self._stable_hash(self._context_signature(request.context))[:8]
        return (
            f"{request.user_id}:{request.task_type or 'chat'}:{request.khrp_step or 'none'}:"
            f"{req_hash}:{query_fingerprint}:{context_signature}"
        )

    @staticmethod
    def _context_signature(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not context:
            return {}
        allowed_keys = {
            "tenant_id",
            "session_id",
            "request_metadata",
            "task_hint",
            "capability_hints",
        }
        signature = {k: context.get(k) for k in allowed_keys if k in context}
        request_metadata = signature.get("request_metadata")
        if isinstance(request_metadata, dict):
            signature["request_metadata"] = {
                k: request_metadata.get(k)
                for k in ("correlation_id", "session_id", "tenant_id")
                if k in request_metadata
            }
        return signature

    @staticmethod
    def _normalize_query(query: str) -> str:
        return " ".join((query or "").split()).lower()

    @staticmethod
    def _stable_hash(payload: Any) -> str:
        try:
            serialized = json.dumps(payload, sort_keys=True, default=str)
        except TypeError:
            serialized = repr(payload)
        return hashlib.md5(serialized.encode()).hexdigest()

    @staticmethod
    def _confidence_bucket(confidence: float) -> str:
        if confidence >= 0.95:
            return ">=0.95"
        if confidence >= 0.9:
            return "0.90-0.95"
        if confidence >= 0.8:
            return "0.80-0.89"
        if confidence >= 0.65:
            return "0.65-0.79"
        return "<0.65"

    @staticmethod
    def _register_cache_entry(cache_key: str, provider: str, user_id: str) -> None:
        _cache_owner[cache_key] = {"provider": provider, "user_id": user_id}
        _cache_index.setdefault(user_id, set()).add(cache_key)
        _provider_cache_index.setdefault(provider, set()).add(cache_key)

    @staticmethod
    def _evict_cache_key(cache_key: str) -> None:
        _cache.delete(cache_key)
        owner = _cache_owner.pop(cache_key, None)
        if not owner:
            return
        user_keys = _cache_index.get(owner["user_id"])
        if user_keys is not None:
            user_keys.discard(cache_key)
            if not user_keys:
                _cache_index.pop(owner["user_id"], None)
        provider_keys = _provider_cache_index.get(owner["provider"])
        if provider_keys is not None:
            provider_keys.discard(cache_key)
            if not provider_keys:
                _provider_cache_index.pop(owner["provider"], None)

    def _estimate_cost(self, provider: str, model: str, req: RouteRequest) -> Optional[float]:
        """Very rough per-call cost estimate based on provider defaults.
        This is a heuristic placeholder; integrate real pricing later.
        """
        pricing = {
            "openai": 0.005,   # per 1k tokens (placeholder)
            "deepseek": 0.003,
            "gemini": 0.004,
            "huggingface": 0.002,
            "local_gguf": 0.0,
        }
        # Assume small call unless specified
        tks = int((req.requirements or {}).get("expected_tokens", 1000))
        per_1k = pricing.get(provider)
        return None if per_1k is None else per_1k * (tks / 1000.0)


# Cache invalidation helpers
def invalidate_user_cache(user_id: str):
    """Invalidate cache entries for a specific user using index."""
    keys = list(_cache_index.get(user_id, set()))
    for k in keys:
        KIRERouter._evict_cache_key(k)


def invalidate_provider_cache(_provider: str):
    """Invalidate routing cache broadly on provider health changes."""
    keys = list(_provider_cache_index.get(_provider, set()))
    for k in keys:
        KIRERouter._evict_cache_key(k)
    _provider_cache_index.pop(_provider, None)


def get_routing_cache_stats() -> Dict[str, Any]:
    """Expose routing cache stats for diagnostics."""
    return _cache.get_stats()


def get_routing_dedup_stats() -> Dict[str, Any]:
    """Expose routing request deduplicator stats for diagnostics."""
    return _deduper.get_stats()
