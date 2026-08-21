"""
CORTEX Analysis — Intent, Sentiment, and Entity Analysis.

This module owns the text-analysis primitives that CORTEX uses to classify
user intent, sentiment, and entities. It was previously located under
``langgraph_orchestrator/``; it has been moved here because analysis is a
CORTEX responsibility, not a LangGraph workflow concern.

Public surface:
- IntentType, SentimentType, BusinessDomain
- AnalysisContext, IntentResult, SentimentResult, AnalysisResult
- SpacyAnalyzer, create_spacy_analyzer
- DecisionEngine (legacy adapter, preserved for compatibility)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable

from ai_karen_engine.core.cortex.routing_intents import resolve_routing_intent
from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService
from ai_karen_engine.core.memory.signals.spacy_service import SpacyService, ParsedMessage
from ai_karen_engine.core.reasoning.synthesis import MetacognitiveMonitor
from ai_karen_engine.models.persona_models import SYSTEM_PERSONAS

logger = logging.getLogger(__name__)

# ---- Optional deps (Prometheus, tenacity) with safe fallbacks ----
try:
    from prometheus_client import Counter, Histogram  # type: ignore
except Exception:  # pragma: no cover
    class _Noop:
        def labels(self, *_, **__): return self
        def observe(self, *_): pass
        def inc(self, *_): pass
    Counter = Histogram = _Noop  # type: ignore

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type  # type: ignore
except Exception:  # pragma: no cover
    def retry(*_, **__):  # noop decorator
        def _inner(fn): return fn
        return _inner
    def stop_after_attempt(*_): return None
    def wait_exponential(*_, **__): return None
    def retry_if_exception_type(*_): return None


# ===========================
# Enumerations & Data Models
# ===========================

class IntentType(str, Enum):
    OPTIMIZE_CODE = "optimize_code"
    DEBUG_ERROR = "debug_error"
    TECHNICAL_QUESTION = "technical_question"
    CODE_REVIEW = "code_review"
    ARCHITECTURE_DESIGN = "architecture_design"
    DEPLOYMENT_HELP = "deployment_help"
    CREATIVE_TASK = "creative_task"
    CONTENT_CREATION = "content_creation"
    DESIGN_ASSISTANCE = "design_assistance"
    BRAINSTORMING = "brainstorming"
    BUSINESS_ADVICE = "business_advice"
    STRATEGY_PLANNING = "strategy_planning"
    MARKET_RESEARCH = "market_research"
    COMPETITIVE_ANALYSIS = "competitive_analysis"
    EXPLAIN_CONCEPT = "explain_concept"
    TUTORIAL_REQUEST = "tutorial_request"
    LEARNING_PATH = "learning_path"
    TROUBLESHOOT = "troubleshoot"
    HOW_TO_GUIDE = "how_to_guide"
    DOCUMENTATION = "documentation"
    CASUAL_CHAT = "casual_chat"
    PERSONAL_ADVICE = "personal_advice"
    FEEDBACK_SHARING = "feedback_sharing"
    SYSTEM_CONFIG = "system_config"
    FEATURE_REQUEST = "feature_request"
    BUG_REPORT = "bug_report"
    GENERAL_ASSIST = "general_assist"


class SentimentType(str, Enum):
    EXCITED = "excited"
    CONFIDENT = "confident"
    SATISFIED = "satisfied"
    HOPEFUL = "hopeful"
    GRATEFUL = "grateful"
    FRUSTRATED = "frustrated"
    ANXIOUS = "anxious"
    CONFUSED = "confused"
    DISAPPOINTED = "disappointed"
    OVERWHELMED = "overwhelmed"
    URGENT = "urgent"
    CRITICAL = "critical"
    TIME_SENSITIVE = "time_sensitive"
    NEUTRAL = "neutral"
    CALM = "calm"
    CONTEMPLATIVE = "contemplative"
    CURIOUS = "curious"


class BusinessDomain(str, Enum):
    TECH_DEVELOPMENT = "tech_development"
    BUSINESS_STRATEGY = "business_strategy"
    CREATIVE_PROJECTS = "creative_projects"
    ACADEMIC_LEARNING = "academic_learning"
    PERSONAL_GROWTH = "personal_growth"
    CUSTOMER_SUPPORT = "customer_support"
    SYSTEM_ADMIN = "system_admin"


@dataclass
class AnalysisContext:
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    domain: Optional[BusinessDomain] = None
    user_tier: str = "standard"
    roles: List[str] = field(default_factory=list)
    interaction_history: List[Dict[str, Any]] = field(default_factory=list)
    system_capabilities: Dict[str, Any] = field(default_factory=dict)
    business_rules: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class IntentResult:
    primary_intent: IntentType
    confidence: float
    alternative_intents: List[Tuple[IntentType, float]] = field(default_factory=list)
    domain: Optional[BusinessDomain] = None
    triggers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SentimentResult:
    primary_sentiment: SentimentType
    confidence: float
    intensity: float = 1.0
    emotional_indicators: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    text: str
    intent: IntentResult
    sentiment: SentimentResult
    entities: Dict[str, Any]
    persona_recommendation: str
    confidence: float
    context: AnalysisContext
    processing_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===========================
# Observability (Prometheus)
# ===========================

_METRIC_ANALYZE_LATENCY = Histogram(
    "karen_analyzer_latency_seconds",
    "Latency for comprehensive analyzer",
    ["component"]
).labels(component="spacy_analyzer")

_METRIC_ANALYZE_ERRORS = Counter(
    "karen_analyzer_errors_total",
    "Total errors in comprehensive analyzer",
    ["component"]
).labels(component="spacy_analyzer")

_METRIC_REQUESTS = Counter(
    "karen_analyzer_requests_total",
    "Total requests to comprehensive analyzer",
    ["component"]
).labels(component="spacy_analyzer")


# ===========================
# Config & Circuit Breaker
# ===========================

@dataclass
class AnalyzerConfig:
    timeout_seconds: float = 10.0
    enable_caching: bool = True
    cache_ttl_seconds: int = 300
    persona_confidence_threshold: float = 0.65
    advanced_sentiment: bool = True
    domain_detection: bool = True
    multi_intent_analysis: bool = True
    cb_failure_threshold: int = 5
    cb_reset_seconds: int = 30


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_seconds: int):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._failures = 0
        self._open_until = 0.0

    def allow(self) -> bool:
        return time.time() >= self._open_until

    def record_success(self):
        self._failures = 0

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.reset_seconds
            self._failures = 0


# ===========================
# Analyzer Implementation
# ===========================

class SpacyAnalyzer:
    def __init__(
        self,
        spacy_service: Optional[SpacyService] = None,
        business_rules: Optional[Dict[str, Any]] = None,
        performance_monitoring: bool = True,
        config: Optional[AnalyzerConfig] = None,
        embedding_lookup: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
        entity_enrichment: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    ):
        self.spacy_service = spacy_service or SpacyService()
        self.performance_monitoring = performance_monitoring
        self.config = config or AnalyzerConfig()
        self.business_rules = business_rules or self._load_default_business_rules()
        self._embedding_lookup = embedding_lookup
        self._entity_enrichment = entity_enrichment
        self._intent_engine = IntentDetectionEngine(self.config)
        self._sentiment_engine = SentimentAnalysisEngine(self.config)
        self._entity_engine = EntityExtractionEngine(self.spacy_service, self.config)
        self._persona_orchestrator = PersonaOrchestrator(self.business_rules, self.config)
        self._gap_analyzer = ProfileGapAnalyzer()
        self._metrics = {
            "total_requests": 0,
            "average_processing_time": 0.0,
            "error_count": 0,
            "success_rate": 1.0,
        }
        self._cb = CircuitBreaker(
            failure_threshold=self.config.cb_failure_threshold,
            reset_seconds=self.config.cb_reset_seconds,
        )
        logger.info("SpacyAnalyzer initialized (CORTEX analysis)")

    def _load_default_business_rules(self) -> Dict[str, Any]:
        return {
            "premium_features": {
                "advanced_sentiment": True,
                "domain_detection": True,
                "multi_intent_analysis": True,
            },
            "persona_routing": {
                "enable_dynamic_routing": True,
                "fallback_persona": "support-assistant",
                "confidence_threshold": 0.7,
                "role_overrides": {
                    "super_admin": "admin-overlord",
                    "admin": "admin-ops"
                },
            },
            "performance": {
                "timeout_seconds": self.config.timeout_seconds,
                "enable_caching": self.config.enable_caching,
                "cache_ttl_seconds": self.config.cache_ttl_seconds,
            },
        }

    async def analyze_comprehensive(
        self,
        text: str,
        context: Optional[AnalysisContext] = None
    ) -> AnalysisResult:
        start = time.time()
        self._metrics["total_requests"] += 1
        _METRIC_REQUESTS.inc(1)

        if context is None:
            context = AnalysisContext()

        text = text.strip()

        try:
            async with _LatencyTimer(_METRIC_ANALYZE_LATENCY):
                async def _core():
                    intent_task = asyncio.create_task(self._intent_engine.detect(text, context))
                    sentiment_task = asyncio.create_task(self._sentiment_engine.analyze(text, context))
                    entity_task = asyncio.create_task(self._entity_engine.extract(text, context))
                    return await asyncio.gather(
                        intent_task, sentiment_task, entity_task, return_exceptions=True
                    )

                intent_result, sentiment_result, entity_result = await asyncio.wait_for(
                    _core(), timeout=self.config.timeout_seconds
                )

                if isinstance(intent_result, Exception):
                    logger.exception("Intent detection failed", exc_info=intent_result)
                    intent_result = IntentResult(IntentType.GENERAL_ASSIST, confidence=0.0)
                if isinstance(sentiment_result, Exception):
                    logger.exception("Sentiment analysis failed", exc_info=sentiment_result)
                    sentiment_result = SentimentResult(SentimentType.NEUTRAL, confidence=0.0, intensity=0.3)
                if isinstance(entity_result, Exception):
                    logger.exception("Entity extraction failed", exc_info=entity_result)
                    entity_result = {"entities": [], "metadata": {"error": str(entity_result), "confidence": 0.4}}

                if self._entity_enrichment and self._cb.allow():
                    try:
                        entity_result = await self._entity_enrichment(entity_result)
                        self._cb.record_success()
                    except Exception as e:
                        logger.warning(f"Entity enrichment failed: {e}")
                        self._cb.record_failure()

                persona_id = await self._persona_orchestrator.select_persona(
                    intent_result, sentiment_result, context
                )

                overall_conf = self._calculate_overall_confidence(
                    intent_result.confidence,
                    sentiment_result.confidence,
                    entity_result.get("metadata", {}).get("confidence", 0.5),
                )

                elapsed = time.time() - start
                self._update_metrics(elapsed, True)

                return AnalysisResult(
                    text=text,
                    intent=intent_result,
                    sentiment=sentiment_result,
                    entities=entity_result,
                    persona_recommendation=persona_id,
                    confidence=overall_conf,
                    context=context,
                    processing_time=elapsed,
                    metadata={
                        "analysis_version": "3.0",
                        "business_domain": intent_result.domain,
                        "premium_features_used": context.user_tier != "standard",
                        "cb_open": not self._cb.allow(),
                    },
                )
        except Exception as e:
            _METRIC_ANALYZE_ERRORS.inc(1)
            elapsed = time.time() - start
            self._update_metrics(elapsed, False)
            logger.error(f"Comprehensive analysis failed: {e}")
            return AnalysisResult(
                text=text,
                intent=IntentResult(IntentType.GENERAL_ASSIST, confidence=0.0),
                sentiment=SentimentResult(SentimentType.NEUTRAL, confidence=0.0, intensity=0.3),
                entities={"entities": [], "metadata": {"error": "analyzer_failure"}},
                persona_recommendation=self.business_rules["persona_routing"]["fallback_persona"],
                confidence=0.2,
                context=context,
                processing_time=elapsed,
                metadata={"analysis_version": "3.0", "degraded": True},
            )

    def _calculate_overall_confidence(self, intent_c: float, sent_c: float, ent_c: float) -> float:
        weights = {"intent": 0.5, "sentiment": 0.3, "entities": 0.2}
        return intent_c * weights["intent"] + sent_c * weights["sentiment"] + ent_c * weights["entities"]

    def _update_metrics(self, processing_time: float, success: bool):
        if not success:
            self._metrics["error_count"] += 1
        alpha = 0.1
        avg = self._metrics["average_processing_time"]
        self._metrics["average_processing_time"] = alpha * processing_time + (1 - alpha) * avg
        total = self._metrics["total_requests"]
        errors = self._metrics["error_count"]
        self._metrics["success_rate"] = (total - errors) / total if total else 1.0

    async def detect_intent(self, text: str) -> str:
        result = await self.analyze_comprehensive(text)
        return result.intent.primary_intent.value

    async def sentiment(self, text: str) -> str:
        result = await self.analyze_comprehensive(text)
        return result.sentiment.primary_sentiment.value

    async def entities(self, text: str) -> Dict[str, Any]:
        result = await self.analyze_comprehensive(text)
        return result.entities

    async def select_persona(self, intent: str, sentiment: str, **kwargs) -> str:
        context = AnalysisContext(**kwargs)
        intent_result = IntentResult(primary_intent=IntentType(intent), confidence=1.0)
        sentiment_result = SentimentResult(primary_sentiment=SentimentType(sentiment), confidence=1.0)
        return await self._persona_orchestrator.select_persona(intent_result, sentiment_result, context)

    async def detect_profile_gaps(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        return await self._gap_analyzer.analyze_gaps(text, ui_caps)

    def get_performance_metrics(self) -> Dict[str, Any]:
        return self._metrics.copy()


# ===========================
# Intent Detection Pipeline
# ===========================

class IntentDetectionEngine:
    def __init__(self, cfg: AnalyzerConfig):
        self._pattern_matcher = PatternBasedIntentDetector(cfg)
        self._ml_enhancer = MLIntentEnhancer(cfg)
        self._domain_detector = BusinessDomainDetector(cfg)

    async def detect(self, text: str, context: AnalysisContext) -> IntentResult:
        pattern_result = await self._pattern_matcher.detect(text)
        if context.user_tier in ["premium", "enterprise"]:
            ml_result = await self._ml_enhancer.enhance(text, pattern_result)
        else:
            ml_result = pattern_result
        if cfg := self._domain_detector.cfg:
            if cfg.domain_detection:
                domain = await self._domain_detector.detect(text, ml_result)
                ml_result.domain = domain
        return ml_result


class PatternBasedIntentDetector:
    def __init__(self, cfg: AnalyzerConfig):
        self.cfg = cfg
        self._patterns = self._build_patterns()

    def _build_patterns(self) -> Dict[IntentType, List[Dict[str, Any]]]:
        return {
            IntentType.OPTIMIZE_CODE: [
                {"pattern": r"\b(optimize|improve|refactor|performance)\b", "weight": 2.0},
                {"pattern": r"\b(slow|inefficient|bottleneck|memory leak)\b", "weight": 1.5},
            ],
            IntentType.BUSINESS_ADVICE: [
                {"pattern": r"\b(strategy|roadmap|business plan|market analysis)\b", "weight": 2.0},
                {"pattern": r"\b(competitor|market share|revenue|profit)\b", "weight": 1.5},
            ],
            IntentType.DEBUG_ERROR: [
                {"pattern": r"\b(error|stack trace|exception|crash|bug)\b", "weight": 2.0},
                {"pattern": r"\b(fix|debug|trace|fails|not working)\b", "weight": 1.3},
            ],
            IntentType.DEPLOYMENT_HELP: [
                {"pattern": r"\b(deploy|docker|kubernetes|helm|ci/cd|pipeline)\b", "weight": 1.8}
            ],
            IntentType.ARCHITECTURE_DESIGN: [
                {"pattern": r"\b(architecture|system design|scal(e|ing)|throughput|latency)\b", "weight": 1.7}
            ],
        }

    async def detect(self, text: str) -> IntentResult:
        lower = text.lower()
        scores: Dict[IntentType, float] = {}
        triggers: List[str] = []

        for itype, plist in self._patterns.items():
            score = 0.0
            for p in plist:
                matches = re.findall(p["pattern"], lower, flags=re.IGNORECASE)
                if matches:
                    score += len(matches) * float(p["weight"])
                    triggers.extend(matches)
            if score > 0:
                scores[itype] = score

        if not scores:
            return IntentResult(primary_intent=IntentType.GENERAL_ASSIST, confidence=0.3, triggers=[])

        total = sum(scores.values())
        norm = {k: v / total for k, v in scores.items()}
        primary, conf = max(norm.items(), key=lambda x: x[1])
        alternatives = sorted([(k, v) for k, v in norm.items() if k != primary and v > 0.1],
                              key=lambda x: x[1], reverse=True)

        return IntentResult(
            primary_intent=primary,
            confidence=conf,
            alternative_intents=alternatives,
            triggers=triggers,
            metadata={"source": "pattern_rules"},
        )


class MLIntentEnhancer:
    def __init__(self, cfg: AnalyzerConfig):
        self.cfg = cfg

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=1.0),
        retry=retry_if_exception_type(Exception),
    )
    async def enhance(self, text: str, base_result: IntentResult) -> IntentResult:
        return base_result


class BusinessDomainDetector:
    def __init__(self, cfg: AnalyzerConfig):
        self.cfg = cfg

    async def detect(self, text: str, _: IntentResult) -> Optional[BusinessDomain]:
        lower = text.lower()
        if any(k in lower for k in ["docker", "kubernetes", "api", "python", "react"]):
            return BusinessDomain.TECH_DEVELOPMENT
        if any(k in lower for k in ["revenue", "pricing", "market", "partner", "go-to-market"]):
            return BusinessDomain.BUSINESS_STRATEGY
        if any(k in lower for k in ["design", "mockup", "logo", "brand", "palette"]):
            return BusinessDomain.CREATIVE_PROJECTS
        return BusinessDomain.TECH_DEVELOPMENT


# ===========================
# Sentiment Analysis
# ===========================

class SentimentAnalysisEngine:
    def __init__(self, cfg: AnalyzerConfig):
        self.cfg = cfg
        self._lexicon = self._build_emotional_lexicon()
        self._intensity = SentimentIntensityCalculator()

    def _build_emotional_lexicon(self) -> Dict[SentimentType, Dict[str, float]]:
        return {
            SentimentType.EXCITED: {"excited": 0.9, "thrilled": 0.95, "enthusiastic": 0.85, "eager": 0.8, "energized": 0.75},
            SentimentType.FRUSTRATED: {"frustrated": 0.9, "annoyed": 0.8, "irritated": 0.75, "angry": 0.95, "mad": 0.9},
            SentimentType.CONFUSED: {"confused": 0.9, "unsure": 0.7, "lost": 0.7},
            SentimentType.URGENT: {"urgent": 0.9, "asap": 0.85, "immediately": 0.8},
            SentimentType.NEUTRAL: {"ok": 0.2, "fine": 0.2, "alright": 0.2},
        }

    async def analyze(self, text: str, context: AnalysisContext) -> SentimentResult:
        lower = text.lower()
        scores: Dict[SentimentType, float] = {}
        indicators: List[str] = []

        for s_type, words in self._lexicon.items():
            score = 0.0
            for w, wt in words.items():
                if w in lower:
                    score += wt
                    indicators.append(w)
            if score > 0:
                scores[s_type] = score

        if not scores:
            return SentimentResult(SentimentType.NEUTRAL, confidence=0.5, intensity=0.3, emotional_indicators=[])

        total = sum(scores.values())
        norm = {k: v / total for k, v in scores.items()}
        primary, conf = max(norm.items(), key=lambda x: x[1])
        intensity = await self._intensity.calculate_intensity(text, primary)

        return SentimentResult(primary, confidence=conf, intensity=intensity, emotional_indicators=indicators)


class SentimentIntensityCalculator:
    async def calculate_intensity(self, text: str, sentiment: SentimentType) -> float:
        bangs = text.count("!")
        caps = sum(1 for c in text if c.isupper())
        length = max(len(text), 1)
        raw = min(1.0, 0.3 + 0.1 * bangs + 0.2 * (caps / length))
        return round(raw, 3)


# ===========================
# Entities (spaCy + enrichment)
# ===========================

class EntityExtractionEngine:
    def __init__(self, spacy_service: SpacyService, cfg: AnalyzerConfig):
        self.spacy = spacy_service
        self.cfg = cfg

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=1.0),
        retry=retry_if_exception_type(Exception),
    )
    async def extract(self, text: str, context: AnalysisContext) -> Dict[str, Any]:
        parsed: ParsedMessage = await self.spacy.parse_text(text)
        ents = [{"text": e.text, "label": e.label_} for e in parsed.doc.ents] if getattr(parsed, "doc", None) else []
        meta: Dict[str, Any] = {"confidence": 0.6 + 0.1 * min(len(ents), 3)}
        if any(e["label"] in ("ORG", "PRODUCT", "LANGUAGE") for e in ents):
            meta["domain_hint"] = "tech/business"
        return {"entities": ents, "metadata": meta}


# ===========================
# Persona Orchestration
# ===========================

class PersonaOrchestrator:
    def __init__(self, business_rules: Dict[str, Any], cfg: AnalyzerConfig):
        self.rules = business_rules.get("persona_routing", {})
        self.cfg = cfg
        self.engine = PersonaRulesEngine(self.rules)

    async def select_persona(
        self,
        intent_result: IntentResult,
        sentiment_result: SentimentResult,
        context: AnalysisContext,
    ) -> str:
        for role, persona in (self.rules.get("role_overrides") or {}).items():
            if role in context.roles:
                return persona

        persona_id, score = await self.engine.apply_rules(intent_result, sentiment_result, context)

        threshold = float(self.rules.get("confidence_threshold", self.cfg.persona_confidence_threshold))
        if score < threshold:
            return self.rules.get("fallback_persona", "support-assistant")

        if persona_id not in SYSTEM_PERSONAS:
            return self.rules.get("fallback_persona", "support-assistant")

        return persona_id


class PersonaRulesEngine:
    def __init__(self, rules: Dict[str, Any]):
        self.rules = rules
        self._evaluators: List[
            Callable[[IntentResult, SentimentResult, AnalysisContext], Awaitable[Tuple[str, float]]]
        ] = [
            self._eval_tech_overrides,
            self._eval_urgent_overrides,
            self._eval_creative_overrides,
            self._eval_default,
        ]

    async def apply_rules(
        self, intent: IntentResult, sentiment: SentimentResult, context: AnalysisContext
    ) -> Tuple[str, float]:
        best = ("support-assistant", 0.5)
        for ev in self._evaluators:
            try:
                persona, score = await ev(intent, sentiment, context)
                if score > best[1]:
                    best = (persona, score)
            except Exception as e:
                logger.warning(f"Persona evaluator failed: {e}")
                continue
        return best

    async def _eval_tech_overrides(self, intent: IntentResult, sentiment: SentimentResult, context: AnalysisContext):
        if intent.primary_intent in {IntentType.DEBUG_ERROR, IntentType.OPTIMIZE_CODE, IntentType.DEPLOYMENT_HELP,
                                     IntentType.ARCHITECTURE_DESIGN, IntentType.CODE_REVIEW}:
            return ("tech-architect", 0.82)
        return ("support-assistant", 0.0)

    async def _eval_urgent_overrides(self, intent: IntentResult, sentiment: SentimentResult, context: AnalysisContext):
        if sentiment.primary_sentiment in {SentimentType.URGENT, SentimentType.CRITICAL, SentimentType.TIME_SENSITIVE}:
            return ("incident-commander", 0.8)
        return ("support-assistant", 0.0)

    async def _eval_creative_overrides(self, intent: IntentResult, sentiment: SentimentResult, context: AnalysisContext):
        if intent.primary_intent in {IntentType.CREATIVE_TASK, IntentType.DESIGN_ASSISTANCE, IntentType.CONTENT_CREATION}:
            return ("creative-director", 0.78)
        return ("support-assistant", 0.0)

    async def _eval_default(self, intent: IntentResult, sentiment: SentimentResult, context: AnalysisContext):
        return ("support-assistant", max(0.55, intent.confidence * 0.8))


# ===========================
# Profile Gap Analysis
# ===========================

class ProfileGapAnalyzer:
    def __init__(self):
        self._gap_detectors: Dict[str, GapDetector] = {
            "technical_context": TechnicalContextDetector(),
            "business_context": BusinessContextDetector(),
            "user_preferences": PreferenceDetector(),
            "system_integration": IntegrationDetector(),
        }
        self._suggestion_engine = SuggestionEngine()

    async def analyze_gaps(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        gaps: Dict[str, Any] = {}
        for name, det in self._gap_detectors.items():
            res = await det.detect(text, ui_caps)
            if res.get("missing"):
                gaps[name] = res
        suggestions = await self._suggestion_engine.generate_suggestions(gaps, ui_caps) if gaps else []
        return {
            "gaps": gaps,
            "suggestions": suggestions,
            "onboarding_needed": bool(gaps),
            "priority_gaps": [g for g in gaps.values() if g.get("priority") == "high"],
            "analysis_timestamp": time.time(),
        }


class GapDetector:
    async def detect(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

class TechnicalContextDetector(GapDetector):
    async def detect(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        missing = not any(k in text.lower() for k in ["language", "framework", "stack", "python", "node", "react"])
        return {"missing": missing, "priority": "medium" if missing else "low", "hint": "Specify tech stack."}

class BusinessContextDetector(GapDetector):
    async def detect(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        missing = not any(k in text.lower() for k in ["market", "revenue", "pricing", "target", "customer"])
        return {"missing": missing, "priority": "low" if not missing else "medium", "hint": "Add business goals."}

class PreferenceDetector(GapDetector):
    async def detect(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        missing = not any(k in text.lower() for k in ["tone", "style", "voice"])
        return {"missing": missing, "priority": "low", "hint": "Share preferred tone/style if relevant."}

class IntegrationDetector(GapDetector):
    async def detect(self, text: str, ui_caps: Dict[str, Any]) -> Dict[str, Any]:
        missing = not ui_caps.get("integrations_ready", False)
        return {"missing": missing, "priority": "high" if missing else "low", "hint": "Complete integration setup."}

class SuggestionEngine:
    async def generate_suggestions(self, gaps: Dict[str, Any], ui_caps: Dict[str, Any]) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        for name, gap in gaps.items():
            suggestions.append({"gap": name, "action": gap.get("hint"), "priority": gap.get("priority")})
        return suggestions


# ===========================
# Utilities
# ===========================

class _LatencyTimer:
    def __init__(self, hist):
        self.hist = hist
    async def __aenter__(self):
        self._t = time.time()
        return self
    async def __aexit__(self, exc_type, exc, tb):
        try:
            self.hist.observe(max(0.0, time.time() - self._t))
        except Exception:
            pass


# ===========================
# Factory
# ===========================

def create_spacy_analyzer(
    spacy_service: Optional[SpacyService] = None,
    business_rules: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> SpacyAnalyzer:
    return SpacyAnalyzer(
        spacy_service=spacy_service,
        business_rules=business_rules,
        performance_monitoring=kwargs.get("performance_monitoring", True),
        config=kwargs.get("config"),
        embedding_lookup=kwargs.get("embedding_lookup"),
        entity_enrichment=kwargs.get("entity_enrichment"),
    )


# ===========================
# Legacy DecisionEngine adapter
# ===========================

class DecisionEngine:
    """Adapter exposing the legacy intent-analysis surface via the reasoning stack."""

    def __init__(
        self,
        classifier: Optional[DistilBertService] = None,
    ):
        self._classifier = classifier or DistilBertService()
        self._metacognition = MetacognitiveMonitor()

    @staticmethod
    def _suggest_tools(intent: str) -> List[str]:
        mapping = {
            "greeting": [],
            "weather_query": ["web_search"],
            "time_query": ["time"],
            "book_query": ["search_books"],
            "information_retrieval": ["search_memory"],
            "technical_question": ["search_docs"],
            "debug_error": ["search_logs"],
            "documentation": ["search_docs"],
            "troubleshoot": ["search_logs"],
            "system_config": ["search_docs"],
        }
        return mapping.get(intent, [])

    @staticmethod
    def _normalize_cortex_intent(cortex_intent: str, analyzer_intent: str) -> str:
        normalized = (cortex_intent or "").strip().lower()
        if normalized in {"", "unknown", "general", "general_assist"}:
            return analyzer_intent

        cortex_to_response = {
            "greeting": "casual_chat",
            "search": "information_retrieval",
            "memory": "information_retrieval",
            "diagnostics": "troubleshoot",
            "system_status": "system_config",
            "audit_log": "documentation",
            "logout": "casual_chat",
            "routing.select": "system_config",
            "routing.profile": "system_config",
            "admin_panel": "system_config",
        }
        return cortex_to_response.get(normalized, normalized)

    @staticmethod
    def _normalize_classifier_intent(
        classifier_intent: str, analyzer_intent: str
    ) -> str:
        normalized = (classifier_intent or "").strip().lower()
        if normalized in {"", "unknown"}:
            return analyzer_intent

        classifier_to_response = {
            "information_seeking": "information_retrieval",
            "task_completion": "how_to_guide",
            "problem_solving": "troubleshoot",
            "creative_assistance": "creative_task",
            "decision_making": "business_advice",
            "social_interaction": "casual_chat",
        }
        return classifier_to_response.get(normalized, analyzer_intent)

    async def analyze_intent(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        context_dict = context or {}
        cortex_intent, cortex_meta = resolve_routing_intent(prompt, context_dict)
        cortex_confidence = 0.0
        if isinstance(cortex_meta, dict):
            raw_confidence = cortex_meta.get("confidence")
            if isinstance(raw_confidence, (int, float)):
                cortex_confidence = float(raw_confidence)

        classifier_intent = "unknown"
        classifier_confidence = 0.0
        classifier_entities: List[Dict[str, Any]] = []
        classifier_sentiment = "neutral"
        try:
            classifier_result = await self._classifier.detect_intent(prompt)
            classifier_intent = classifier_result.intent
            classifier_confidence = classifier_result.confidence
            classifier_entities = classifier_result.entities
            sentiment_result = await self._classifier.analyze_sentiment(prompt)
            classifier_sentiment = sentiment_result.sentiment
        except Exception as exc:
            logger.debug("DistilBERT intent classification unavailable: %s", exc)

        if cortex_intent and cortex_intent.lower() not in {"unknown", ""}:
            primary_intent = self._normalize_cortex_intent(
                cortex_intent, classifier_intent
            )
        else:
            primary_intent = classifier_intent

        reasoning_state = self._metacognition.monitor_reasoning_process(
            query=prompt,
            current_output=primary_intent,
            context=[
                str(context_dict.get("context_summary", "")),
            ]
            if context
            else None,
        )
        strategy = self._metacognition.select_strategy(
            query=prompt,
            task_type=primary_intent,
            current_state=reasoning_state,
        )

        normalized_entities: List[Dict[str, Any]] = []
        for entity in classifier_entities:
            if isinstance(entity, dict):
                normalized_entities.append(entity)
            elif hasattr(entity, "text"):
                normalized_entities.append(
                    {
                        "type": getattr(entity, "label_", "unknown"),
                        "value": getattr(entity, "text", ""),
                    }
                )

        return {
            "primary_intent": primary_intent,
            "intent": primary_intent,
            "confidence": max(
                classifier_confidence,
                cortex_confidence,
                reasoning_state.confidence,
            ),
            "suggested_tools": self._suggest_tools(primary_intent),
            "entities": normalized_entities,
            "requires_clarification": classifier_confidence < 0.45
            or bool(reasoning_state.knowledge_gaps),
            "sentiment": classifier_sentiment,
            "persona_recommendation": "technical" if "code" in primary_intent else "friendly",
            "metadata": {
                "intent_source": "cortex+distilbert",
                "cortex_intent": cortex_intent,
                "cortex_meta": cortex_meta,
                "classifier_intent": classifier_intent,
                "classifier_confidence": classifier_confidence,
                "reasoning_trace": [
                    f"intent={primary_intent}",
                    f"cortex={cortex_intent}",
                    f"strategy={strategy.value}",
                    f"state={reasoning_state.cognitive_state.value}",
                ],
                "strategy_used": strategy.value,
                "quality_score": reasoning_state.performance_estimate,
                "knowledge_gaps": reasoning_state.knowledge_gaps,
                "metacognitive_state": reasoning_state.cognitive_state.value,
                "reasoning_confidence": reasoning_state.confidence,
                "reasoning_certainty": reasoning_state.certainty,
            },
            "context": context_dict or {},
        }
