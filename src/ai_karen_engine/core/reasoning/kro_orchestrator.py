"""
Kari Reasoning Orchestrator (KRO) - specialized prompt-first sub-orchestrator.

KRO is not Karen's standard chat authority. It exists for explicit, KRO-native
specialized subflows that need structured planning, reasoning artifacts, and
specialized telemetry outside the normal ChatOrchestrator lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from ai_karen_engine.monitoring.kire_metrics import KRO_SPECIALIZED_PATH_TOTAL
from ai_karen_engine.core.cortex.contracts import ReasoningRequest, ReasoningResult

logger = logging.getLogger(__name__)


# ===================================
# INTENT CLASSIFICATION
# ===================================

class Intent(str, Enum):
    """System-wide intents for routing and processing."""
    BASIC_INTERNET_SEARCH = "Basic_Internet_Search"
    ADVANCED_INTERNET_SEARCH = "Advanced_Internet_Search"
    DATA_SCRAPING = "Data_Scraping"
    MEDIA = "Media"
    PREDICTIVE = "Predictive"
    AUTOMATION = "Automation"
    MODEL_MGMT = "ModelMgmt"
    SYSTEM = "System"
    GENERAL = "General"


class Category(str, Enum):
    """Domain categories for classification."""
    TECHNICAL = "technical"
    STRATEGIC = "strategic"
    CREATIVE = "creative"
    ANALYTICAL = "analytical"
    FACTUAL = "factual"


class Sentiment(str, Enum):
    """Sentiment classification."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    MIXED = "mixed"


class Style(str, Enum):
    """Response style."""
    FACTUAL = "factual"
    STRATEGIC = "strategic"
    CREATIVE = "creative"
    ANALYTICAL = "analytical"
    TECHNICAL = "technical"


# ===================================
# DATA STRUCTURES
# ===================================

@dataclass
class Classification:
    """Classification metadata for requests."""
    intent: Intent
    category: Category
    sentiment: Sentiment
    style: Style
    importance: int  # 1-10
    keywords: str  # pipe-separated


@dataclass
class PlanStep:
    """Single step in execution plan."""
    step: int
    action: str
    detail: str
    name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    why: Optional[str] = None


@dataclass
class Evidence:
    """Evidence source for responses."""
    source: str
    type: str  # search|scrape|file|memory|model
    hash: Optional[str] = None
    snippet: str = ""


@dataclass
class MemoryWrite:
    """Memory to persist after response."""
    text: str
    tags: List[str]
    ttl: str  # ISO timestamp or policy name


@dataclass
class UIComponent:
    """UI component for rendering."""
    type: str  # text|table|image|code
    title: Optional[str] = None
    body_md: Optional[str] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[List[str]]] = None
    src: Optional[str] = None
    alt: Optional[str] = None
    code: Optional[str] = None
    language: Optional[str] = None


@dataclass
class ToolCall:
    """Tool call record for telemetry."""
    name: str
    ok: bool
    latency_ms: float
    error: Optional[str] = None


@dataclass
class Telemetry:
    """Telemetry data for observability."""
    tools_called: List[ToolCall] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ResponseMeta:
    """Response metadata."""
    timestamp: str
    agent: str = "KRO"
    confidence: float = 0.0
    latency_ms: float = 0.0
    tokens_used: int = 0
    provider: Optional[str] = None
    model: Optional[str] = None
    degraded_mode: bool = False


@dataclass
class KROResponse:
    """Complete KRO response envelope."""
    meta: ResponseMeta
    classification: Classification
    reasoning_summary: str
    plan: List[PlanStep]
    evidence: List[Evidence]
    memory_writes: List[MemoryWrite]
    ui: Dict[str, Any]
    telemetry: Telemetry
    suggestions: List[str] = field(default_factory=list)


# ===================================
# HELPER MODEL INTERFACE
# ===================================

class HelperModels:
    """Core helper models for augmenting main LLM."""

    def __init__(self):
        self.default_model_provider = None
        self.distilbert = None
        self.spacy = None
        self._initialized = False

    async def initialize(self):
        """Lazy initialization of helper models."""
        if self._initialized:
            return

        try:
            # Initialize default model for scaffolding
            from ai_karen_engine.integrations.llm_registry import get_registry
            registry = get_registry()
            self.default_model_provider = registry.get_provider("builtin_transformers")

            # Initialize DistilBERT for classification
            from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService
            self.distilbert = DistilBertService()

            # Initialize spaCy for NLP
            from ai_karen_engine.core.memory.signals.spacy_service import get_spacy_service
            self.spacy = get_spacy_service()

            self._initialized = True
            logger.info("Helper models initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize some helper models: {e}")
            # Continue with partial initialization


# ===================================
# DYNAMIC PROMPT SUGGESTIONS
# ===================================

class SuggestionEngine:
    """Generates dynamic, contextual prompt suggestions."""

    def __init__(self):
        self.recent_topics = []
        self.max_recent = 10

    async def generate_suggestions(
        self,
        user_message: str,
        conversation_history: List[Dict[str, Any]],
        user_expertise: str = "intermediate",
        context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Generate 3-5 contextual next-step prompts."""
        suggestions = []

        try:
            # Extract topics from recent conversation
            topics = self._extract_topics(conversation_history)

            # Determine user familiarity level
            familiarity = self._determine_familiarity(conversation_history, user_expertise)

            # Generate suggestions based on context
            if familiarity == "novice":
                suggestions = self._generate_novice_suggestions(user_message, topics)
            elif familiarity == "expert":
                suggestions = self._generate_expert_suggestions(user_message, topics)
            else:
                suggestions = self._generate_intermediate_suggestions(user_message, topics)

            # Limit to 3-5 suggestions
            return suggestions[:5] if suggestions else [
                "Tell me more about this",
                "Can you provide an example?",
                "What are the best practices?",
            ]

        except Exception as e:
            logger.warning(f"Suggestion generation failed: {e}")
            return ["Continue...", "Explain further", "Show examples"]

    def _extract_topics(self, history: List[Dict[str, Any]]) -> List[str]:
        """Extract key topics from conversation history."""
        topics = []
        for turn in history[-5:]:  # Last 5 turns
            content = turn.get("content", "")
            # Simple keyword extraction (can be enhanced with NLP)
            words = content.lower().split()
            topics.extend([w for w in words if len(w) > 5])
        return list(set(topics))[:10]

    def _determine_familiarity(
        self,
        history: List[Dict[str, Any]],
        default: str = "intermediate"
    ) -> str:
        """Determine user familiarity level from history."""
        if len(history) < 3:
            return "novice"

        # Analyze conversation depth and technical language
        technical_terms = 0
        total_words = 0

        for turn in history[-10:]:
            content = turn.get("content", "")
            words = content.split()
            total_words += len(words)
            # Count technical indicators
            technical_terms += sum(1 for w in words if len(w) > 8)

        if total_words == 0:
            return default

        ratio = technical_terms / total_words

        if ratio > 0.15:
            return "expert"
        elif ratio > 0.08:
            return "intermediate"
        else:
            return "novice"

    def _generate_novice_suggestions(self, message: str, topics: List[str]) -> List[str]:
        """Generate beginner-friendly suggestions."""
        return [
            "Explain this in simpler terms",
            "What do I need to know first?",
            "Can you show me a basic example?",
            "What are the fundamentals?",
            "How do I get started?",
        ]

    def _generate_intermediate_suggestions(self, message: str, topics: List[str]) -> List[str]:
        """Generate intermediate-level suggestions."""
        return [
            "Show me practical examples",
            "What are common pitfalls to avoid?",
            "How does this compare to alternatives?",
            "What are the best practices?",
            "Can you explain the tradeoffs?",
        ]

    def _generate_expert_suggestions(self, message: str, topics: List[str]) -> List[str]:
        """Generate expert-level suggestions."""
        return [
            "Explain the implementation details",
            "What are the performance implications?",
            "How does this scale?",
            "Show advanced optimization techniques",
            "Discuss edge cases and limitations",
        ]


# ===================================
# KRO ORCHESTRATOR
# ===================================

class KROOrchestrator:
    """
    Kari Reasoning Orchestrator for explicit specialized flows.

    Responsibilities:
    1. Plan specialized reasoning paths
    2. Route specialized requests to appropriate models via KIRE
    3. Coordinate helper models (default model, DistilBERT, spaCy)
    4. Implement graceful degradation for KRO-native paths
    5. Generate dynamic prompt suggestions
    6. Maintain specialized-path observability

    Non-responsibilities:
    - standard chat lifecycle ownership
    - standard chat persistence/writeback timing
    - frontend completion truth for governed chat
    """

    def __init__(
        self,
        llm_registry=None,
        enable_cuda: bool = True,
        enable_optimization: bool = True,
    ):
        """Initialize KRO with dependencies."""
        from ai_karen_engine.integrations.llm_registry import get_registry

        self.llm_registry = llm_registry or get_registry()
        self.helpers = HelperModels()
        self.suggestions = SuggestionEngine()

        # Degraded mode tracking
        self.degraded_mode = False
        self.degraded_reason = ""

        # Optional components
        self.cuda_engine = None
        self.optimization_engine = None

        if enable_cuda:
            try:
                from ai_karen_engine.services.optimization.cuda_acceleration_engine import CUDAAccelerationEngine
                self.cuda_engine = CUDAAccelerationEngine()
                logger.info("CUDA acceleration enabled")
            except Exception as e:
                logger.warning(f"CUDA acceleration unavailable: {e}")

        if enable_optimization:
            try:
                from ai_karen_engine.services.optimization.content_optimization_engine import ContentOptimizationEngine
                self.optimization_engine = ContentOptimizationEngine()
                logger.info("Content optimization enabled")
            except Exception as e:
                logger.warning(f"Content optimization unavailable: {e}")

        logger.info("KRO Orchestrator initialized")

    async def process_request(
        self,
        user_input: str,
        user_id: str = "anon",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        ui_context: Optional[Dict[str, Any]] = None,
        config_ui: Optional[Dict[str, Any]] = None,
        system_caps: Optional[Dict[str, Any]] = None,
        mem_snapshot: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[KROResponse, str]:
        """
        Process an explicit specialized request through the KRO pipeline.

        Returns:
            Tuple of (KROResponse JSON envelope, user-facing message)
        """
        start_time = time.perf_counter()
        corr_id = correlation_id or str(uuid.uuid4())[:12]

        # Initialize helper models if needed
        await self.helpers.initialize()

        # Emit OSIRIS start event
        KRO_SPECIALIZED_PATH_TOTAL.labels(path="kro_orchestrator.process_request", status="started").inc()
        await self._log_osiris_event("kro.start", {
            "correlation_id": corr_id,
            "user_id": user_id,
            "input_length": len(user_input),
        })

        try:
            # Step 1: Classify intent and requirements
            classification = await self._classify_intent(user_input, ui_context)

            # Step 2: Plan execution
            plan = await self._create_plan(user_input, classification, mem_snapshot)

            # Step 3: Route to appropriate model via KIRE
            routing_decision = await self._route_request(
                user_input,
                user_id,
                classification,
                ui_context,
            )

            # Step 4: Execute plan with tools
            evidence, telemetry = await self._execute_plan(
                plan,
                user_input,
                routing_decision,
                system_caps or {},
            )

            # Step 5: Generate response using selected model
            response_text = await self._generate_response(
                user_input,
                routing_decision,
                evidence,
                classification,
                conversation_history or [],
            )

            # Step 6: Optimize and format response
            ui_message, ui_components = await self._format_response(
                response_text,
                classification,
                evidence,
            )

            # Step 7: Generate dynamic suggestions
            suggestions = await self.suggestions.generate_suggestions(
                user_input,
                conversation_history or [],
                context=ui_context,
            )

            # Step 8: Propose memory writes
            memory_writes = await self._propose_memory_writes(
                user_input,
                response_text,
                classification,
            )

            # Build response envelope
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            meta = ResponseMeta(
                timestamp=datetime.utcnow().isoformat() + "Z",
                agent="KRO-specialized",
                confidence=routing_decision.get("confidence", 0.85),
                latency_ms=elapsed_ms,
                tokens_used=self._estimate_tokens(user_input, response_text),
                provider=routing_decision.get("provider"),
                model=routing_decision.get("model"),
                degraded_mode=self.degraded_mode,
            )

            response = KROResponse(
                meta=meta,
                classification=classification,
                reasoning_summary=self._create_reasoning_summary(plan, routing_decision),
                plan=plan,
                evidence=evidence,
                memory_writes=memory_writes,
                ui={
                    "layout_hint": "default",
                    "components": ui_components,
                },
                telemetry=telemetry,
                suggestions=suggestions,
            )
            response.telemetry.notes = "specialized_kro_path"

            # Emit OSIRIS completion event
            await self._log_osiris_event("kro.done", {
                "correlation_id": corr_id,
                "success": True,
                "latency_ms": elapsed_ms,
                "provider": routing_decision.get("provider"),
                "model": routing_decision.get("model"),
                "degraded_mode": self.degraded_mode,
            })
            KRO_SPECIALIZED_PATH_TOTAL.labels(
                path="kro_orchestrator.process_request",
                status="degraded" if self.degraded_mode else "success",
            ).inc()

            return response, ui_message

        except Exception as e:
            logger.error(f"KRO processing failed: {e}", exc_info=True)
            KRO_SPECIALIZED_PATH_TOTAL.labels(path="kro_orchestrator.process_request", status="error").inc()

            # Attempt degraded mode response
            degraded_response, degraded_message = await self._handle_degraded_mode(
                user_input,
                user_id,
                str(e),
                corr_id,
            )

            return degraded_response, degraded_message

    async def run(self, request: ReasoningRequest) -> ReasoningResult:
        """Protocol-aligned entry point for runtime reasoning invocation."""
        kro_response, ui_message = await self.process_request(
            user_input=request.message,
            user_id=request.user.user_id,
            conversation_history=request.metadata.get("conversation_history") or [],
            ui_context=request.metadata.get("ui_context"),
            config_ui=request.metadata.get("config_ui"),
            system_caps=request.metadata.get("system_caps") or {},
            mem_snapshot=request.memory_context,
            correlation_id=request.metadata.get("correlation_id"),
        )

        reasoning_modes = list(request.kire.reasoning_modes or [])
        reasoning_type = reasoning_modes[0] if reasoning_modes else "synthesis"

        evidence: List[Dict[str, Any]] = []
        evidence_source_mix: Dict[str, int] = {}
        memory_ids: List[str] = []
        graph_paths_used: List[str] = []
        contradictions_found: List[Dict[str, Any]] = []
        for item in kro_response.evidence:
            if isinstance(item, dict):
                normalized = dict(item)
            elif hasattr(item, "__dict__"):
                normalized = dict(item.__dict__)
            else:
                normalized = {"value": str(item)}

            evidence.append(normalized)

            item_id = normalized.get("id")
            if item_id is not None:
                memory_ids.append(str(item_id))

            payload = normalized.get("payload") or {}
            if isinstance(payload, dict):
                metadata = payload.get("metadata") or {}
                if isinstance(metadata, dict):
                    source = str(
                        metadata.get("store")
                        or metadata.get("source")
                        or metadata.get("context_type")
                        or "unknown"
                    ).lower()
                    evidence_source_mix[source] = evidence_source_mix.get(source, 0) + 1
                    graph_path = metadata.get("graph_path") or metadata.get("path")
                    if graph_path:
                        graph_paths_used.append(str(graph_path))
                    if metadata.get("relationship") in {"contradiction", "conflict"}:
                        contradictions_found.append(normalized)

        hypotheses: List[str] = []
        keywords = getattr(kro_response.classification, "keywords", "")
        if keywords:
            hypotheses.extend([part.strip() for part in str(keywords).split("|") if part.strip()])
        if not hypotheses:
            hypotheses.extend([step.action for step in kro_response.plan[:5] if getattr(step, "action", None)])

        verification_notes = list(kro_response.telemetry.errors)
        if kro_response.meta.degraded_mode:
            verification_notes.append("KRO degraded mode active")

        degraded = bool(kro_response.meta.degraded_mode)
        confidence = float(kro_response.meta.confidence)
        needs_human_confirmation = degraded or confidence < 0.5

        diagnostics = {
            "ui_message": ui_message,
            "classification": asdict(kro_response.classification),
            "meta": asdict(kro_response.meta),
            "plan_steps": len(kro_response.plan),
            "suggestions": list(kro_response.suggestions),
            "telemetry_notes": kro_response.telemetry.notes,
            "degraded_mode": kro_response.meta.degraded_mode,
            "reasoning_type": reasoning_type,
            "reasoning_modes": reasoning_modes,
            "memory_ids": list(memory_ids),
            "graph_paths_used": list(graph_paths_used),
            "evidence_source_mix": dict(evidence_source_mix),
        }

        return ReasoningResult(
            summary=kro_response.reasoning_summary,
            evidence=evidence,
            hypotheses=hypotheses,
            confidence=confidence,
            verification_notes=verification_notes,
            refined_answer=ui_message,
            diagnostics=diagnostics,
            success=True,
            degraded=degraded,
            reasoning_type=reasoning_type,
            memory_ids=memory_ids,
            graph_paths_used=graph_paths_used,
            contradictions_found=contradictions_found,
            needs_human_confirmation=needs_human_confirmation,
            fallback_used="kro_degraded_mode" if degraded else None,
            evidence_source_mix=evidence_source_mix,
        )

    async def _classify_intent(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]],
    ) -> Classification:
        """Classify user intent using DistilBERT if available."""
        try:
            # Use DistilBERT for classification if available
            if self.helpers.distilbert:
                # Classification logic here
                pass

            # Fallback to rule-based classification
            intent = Intent.GENERAL
            category = Category.FACTUAL
            sentiment = Sentiment.NEUTRAL
            style = Style.FACTUAL
            importance = 5

            # Simple heuristics
            lower_input = user_input.lower()

            if any(k in lower_input for k in ["search", "find", "look up"]):
                intent = Intent.BASIC_INTERNET_SEARCH
            elif any(k in lower_input for k in ["analyze", "research", "investigate"]):
                intent = Intent.ADVANCED_INTERNET_SEARCH
                category = Category.ANALYTICAL
            elif any(k in lower_input for k in ["scrape", "extract", "collect data"]):
                intent = Intent.DATA_SCRAPING
            elif any(k in lower_input for k in ["image", "video", "audio"]):
                intent = Intent.MEDIA
                category = Category.CREATIVE
            elif any(k in lower_input for k in ["predict", "forecast", "estimate"]):
                intent = Intent.PREDICTIVE
                category = Category.ANALYTICAL
            elif any(k in lower_input for k in ["automate", "schedule", "workflow"]):
                intent = Intent.AUTOMATION
                category = Category.STRATEGIC

            # Extract keywords
            keywords = "|".join(user_input.split()[:5])

            return Classification(
                intent=intent,
                category=category,
                sentiment=sentiment,
                style=style,
                importance=importance,
                keywords=keywords,
            )

        except Exception as e:
            logger.warning(f"Classification failed: {e}")
            return Classification(
                intent=Intent.GENERAL,
                category=Category.FACTUAL,
                sentiment=Sentiment.NEUTRAL,
                style=Style.FACTUAL,
                importance=5,
                keywords="general",
            )

    async def _create_plan(
        self,
        user_input: str,
        classification: Classification,
        mem_snapshot: Optional[Dict[str, Any]],
    ) -> List[PlanStep]:
        """Create minimal execution plan."""
        plan = [
            PlanStep(
                step=1,
                action="classify",
                detail=f"Classified as {classification.intent.value}",
            ),
        ]

        # Add tool steps based on intent
        if classification.intent == Intent.BASIC_INTERNET_SEARCH:
            plan.append(PlanStep(
                step=2,
                action="tool",
                name="search.basic",
                args={"query": user_input},
                why="User requested search",
            ))
        elif classification.intent == Intent.ADVANCED_INTERNET_SEARCH:
            plan.append(PlanStep(
                step=2,
                action="tool",
                name="search.advanced",
                args={"query": user_input},
                why="Complex research query",
            ))

        # Add synthesis step
        plan.append(PlanStep(
            step=len(plan) + 1,
            action="synthesize",
            detail="Compose final answer from evidence and reasoning",
        ))

        return plan

    async def _route_request(
        self,
        user_input: str,
        user_id: str,
        classification: Classification,
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Route request to appropriate model.

        KIRE retired: provider selection is owned by RuntimePolicy + ProviderRouter.
        This method returns a default routing decision for backward compatibility.
        """
        return {
            "provider": "builtin_vllm",
            "model": "auto",
            "reasoning": "Provider selection is owned by RuntimePolicy + ProviderRouter",
            "confidence": 0.5,
            "fallback_chain": ["builtin_vllm", "builtin_transformers"],
        }

    async def _execute_plan(
        self,
        plan: List[PlanStep],
        user_input: str,
        routing_decision: Dict[str, Any],
        system_caps: Dict[str, Any],
    ) -> Tuple[List[Evidence], Telemetry]:
        """Execute plan steps and gather evidence."""
        evidence = []
        tool_calls = []
        errors = []

        for step in plan:
            if step.action == "tool" and step.name:
                tool_start = time.perf_counter()
                try:
                    # Execute tool (placeholder - integrate actual tools)
                    result = f"Tool {step.name} executed successfully"
                    evidence.append(Evidence(
                        source=step.name,
                        type="tool",
                        snippet=result,
                    ))
                    tool_calls.append(ToolCall(
                        name=step.name,
                        ok=True,
                        latency_ms=(time.perf_counter() - tool_start) * 1000,
                    ))
                except Exception as e:
                    errors.append(f"Tool {step.name} failed: {e}")
                    tool_calls.append(ToolCall(
                        name=step.name,
                        ok=False,
                        latency_ms=(time.perf_counter() - tool_start) * 1000,
                        error=str(e),
                    ))

        telemetry = Telemetry(
            tools_called=tool_calls,
            errors=errors,
        )

        return evidence, telemetry

    async def _generate_response(
        self,
        user_input: str,
        routing_decision: Dict[str, Any],
        evidence: List[Evidence],
        classification: Classification,
        history: List[Dict[str, Any]],
    ) -> str:
        """Generate response using routed model."""
        try:
            provider = routing_decision["provider"]
            model = routing_decision["model"]

            # Get provider from registry
            provider_instance = self.llm_registry.get_provider(provider)

            if not provider_instance:
                raise ValueError(f"Provider {provider} not available")

            # Build context from evidence
            context_parts = []
            for ev in evidence:
                context_parts.append(f"[{ev.source}]: {ev.snippet}")
            context_str = "\n".join(context_parts)

            # Build prompt
            prompt = f"""Context: {context_str}

User Question: {user_input}

Provide a clear, concise, and actionable answer."""

            # Generate response
            # Note: This is simplified - actual implementation should handle streaming, tokens, etc.
            response = await self._call_model(provider_instance, model, prompt)

            return response

        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            return f"I apologize, but I encountered an error generating a response: {str(e)}"

    async def _call_model(
        self,
        provider_instance: Any,
        model: str,
        prompt: str,
    ) -> str:
        """Call model with proper error handling."""
        try:
            # Attempt to use CUDA acceleration if available
            if self.cuda_engine:
                # Offload to GPU if supported
                pass

            # Call provider (simplified - needs proper implementation)
            if hasattr(provider_instance, 'generate'):
                result = await provider_instance.generate(prompt, model=model)
                return result.get("text", result.get("content", ""))
            else:
                return "Model call not yet implemented for this provider"

        except Exception as e:
            logger.error(f"Model call failed: {e}")
            raise

    async def _format_response(
        self,
        response_text: str,
        classification: Classification,
        evidence: List[Evidence],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Format response for UI delivery."""
        # Use optimization engine if available
        if self.optimization_engine:
            try:
                # Optimize content
                pass
            except Exception:
                pass

        # Build UI components
        components = [
            {
                "type": "text",
                "title": None,
                "body_md": response_text,
            }
        ]

        # Add evidence sources if available
        if evidence:
            sources_md = "**Sources:**\n" + "\n".join([
                f"- {ev.source}: {ev.snippet[:100]}..."
                for ev in evidence[:3]
            ])
            components.append({
                "type": "text",
                "title": "Sources",
                "body_md": sources_md,
            })

        return response_text, components

    async def _propose_memory_writes(
        self,
        user_input: str,
        response_text: str,
        classification: Classification,
    ) -> List[MemoryWrite]:
        """Propose memories to persist (requires user consent)."""
        # Only propose stable, relevant memories
        memories = []

        # Extract key facts from response
        if classification.importance >= 7:
            memories.append(MemoryWrite(
                text=f"User asked about {classification.keywords}: {response_text[:100]}",
                tags=["conversation", classification.category.value],
                ttl="30d",
            ))

        return memories

    def _create_reasoning_summary(
        self,
        plan: List[PlanStep],
        routing_decision: Dict[str, Any],
    ) -> str:
        """Create 1-2 sentence reasoning summary."""
        return (
            f"Classified intent and routed to {routing_decision['provider']}/{routing_decision['model']}. "
            f"Executed {len(plan)} steps to gather evidence and synthesize response."
        )

    def _estimate_tokens(self, user_input: str, response: str) -> int:
        """Rough token estimation."""
        return (len(user_input) + len(response)) // 4

    async def _handle_degraded_mode(
        self,
        user_input: str,
        user_id: str,
        error: str,
        corr_id: str,
    ) -> Tuple[KROResponse, str]:
        """Handle degraded mode response using helper models."""
        self.degraded_mode = True
        self.degraded_reason = error

        logger.warning(f"Entering degraded mode: {error}")

        # Emit degraded mode event
        await self._log_osiris_event("kro.degraded", {
            "correlation_id": corr_id,
            "reason": error,
            "user_id": user_id,
        })

        # Use default model if available
        degraded_text = "I apologize, but I'm currently operating in degraded mode due to system issues. "

        try:
            if self.helpers.default_model_provider:
                # Use default model for basic response
                degraded_text += "I can still help with basic queries. Please try rephrasing your question."
            else:
                degraded_text += "Please try again shortly or contact support."
        except Exception:
            pass

        # Build minimal response
        classification = Classification(
            intent=Intent.SYSTEM,
            category=Category.FACTUAL,
            sentiment=Sentiment.NEUTRAL,
            style=Style.FACTUAL,
            importance=8,
            keywords="error|degraded",
        )

        meta = ResponseMeta(
            timestamp=datetime.utcnow().isoformat() + "Z",
            agent="KRO",
            confidence=0.3,
            latency_ms=0,
            tokens_used=0,
            degraded_mode=True,
        )

        response = KROResponse(
            meta=meta,
            classification=classification,
            reasoning_summary=f"System degraded: {error}",
            plan=[],
            evidence=[],
            memory_writes=[],
            ui={
                "layout_hint": "default",
                "components": [{
                    "type": "text",
                    "body_md": degraded_text,
                }],
            },
            telemetry=Telemetry(errors=[error]),
            suggestions=["Try again", "Contact support", "Check system status"],
        )
        response.telemetry.notes = "specialized_kro_path"

        return response, degraded_text

    async def _log_osiris_event(self, event_type: str, data: Dict[str, Any]):
        """Log structured OSIRIS event for observability."""
        try:
            # Integrate with OSIRIS logging system
            logger.info(f"OSIRIS[{event_type}]: {json.dumps(data)}")

            # Emit metrics if Prometheus available
            try:
                from prometheus_client import Counter
                kro_events = Counter(
                    "kro_events_total",
                    "KRO orchestrator events",
                    ["event_type", "status"],
                )
                status = "success" if "success" in data and data["success"] else "info"
                kro_events.labels(event_type=event_type, status=status).inc()
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"OSIRIS logging failed: {e}")


# ===================================
# FACTORY FUNCTION
# ===================================

_kro_instance = None

def get_kro_orchestrator() -> KROOrchestrator:
    """Get singleton KRO orchestrator instance."""
    global _kro_instance
    if _kro_instance is None:
        _kro_instance = KROOrchestrator()
    return _kro_instance
