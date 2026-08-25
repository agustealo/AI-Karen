"""Integrated Cognitive Engine (ICE) wrapper — Premium Enterprise v3.1 (Hybrid-ready)

Adds:
- SR Retriever Adapter (drop-in LlamaIndex/Milvus/etc.)
- ICE Sub-Engines (LangGraph/DSPy) for synthesis orchestration (optional)
- Same policy, telemetry, budget, circuit breaker as v3.0
"""

from __future__ import annotations

import time
import asyncio
import statistics
import logging
import threading
import zlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Literal, Callable
from enum import Enum
from contextlib import contextmanager

from ai_karen_engine.core.reasoning.retrieval.adapters import SRRetriever
from ai_karen_engine.core.reasoning.synthesis.subengines import SynthesisSubEngine
from ai_karen_engine.core.reasoning.soft_reasoning.engine import SoftReasoningEngine
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry

# Optional memory_hub for cross-modal retrieval
try:
    from ai_karen_engine.core import memory_hub
except ImportError:
    memory_hub = None  # type: ignore

logger = logging.getLogger("ai_karen.reasoning.ice_premium")

# ---- Prometheus (graceful if not installed) ----
try:
    from prometheus_client import Counter, Histogram, Gauge  # type: ignore
    METRICS = True
    M_LAT = Histogram("kari_ice_latency_ms", "ICE latency (ms)", buckets=(10, 20, 50, 100, 200, 400, 800, 1600, 3200))
    M_STRAT = Counter("kari_ice_recall_strategy_total", "Recall strategy usage", labelnames=("strategy",))
    M_WB = Counter("kari_ice_writebacks_total", "Writebacks", labelnames=("tier",))
    M_FB = Counter("kari_ice_fallbacks_total", "Fallbacks", labelnames=("type",))
    M_TOK = Counter("kari_ice_token_usage_total", "Token usage approx", labelnames=("mode",))
    M_CB = Gauge("kari_ice_cb_state", "Circuit breaker state (0=closed,1=half,2=open)")
except Exception:  # pragma: no cover
    METRICS = False
    class _Noop:
        def labels(self, *_, **__): return self
        def observe(self, *_): pass
        def inc(self, *_): pass
        def set(self, *_): pass
    M_LAT = M_STRAT = M_WB = M_FB = M_TOK = M_CB = _Noop()


class RecallStrategy(Enum):
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    HYBRID = "hybrid"
    CASCADE = "cascade"


class SynthesisMode(Enum):
    CONCISE = "concise"
    ANALYTICAL = "analytical"
    ACTION_ORIENTED = "action_oriented"
    MULTI_PERSPECTIVE = "multi_perspective"


@dataclass
class ICEPerformanceBaseline:
    avg_entropy: float = 0.0
    entropy_std: float = 0.0
    p95_latency: float = 0.0
    success_rate: float = 1.0
    sample_count: int = 0
    last_calibrated: float = field(default_factory=time.time)
    _lat: list[float] = field(default_factory=list)

    def update(self, entropy: float, latency_ms: float, success: bool) -> None:
        self.sample_count += 1
        a = 0.1
        self.avg_entropy = a * entropy + (1 - a) * self.avg_entropy
        try:
            self.entropy_std = max(1e-6, statistics.stdev([self.avg_entropy, entropy]))
        except statistics.StatisticsError:
            self.entropy_std = max(1e-6, abs(self.avg_entropy - entropy))
        self.success_rate = a * (1.0 if success else 0.0) + (1 - a) * self.success_rate
        self._lat.append(float(latency_ms))
        self._lat = self._lat[-200:]
        if len(self._lat) >= 10:
            p = sorted(self._lat)
            self.p95_latency = p[int(0.95 * (len(p) - 1))]
        self.last_calibrated = time.time()


@dataclass
class ICEWritebackPolicy:
    enable: bool = True
    adaptive_entropy: bool = True
    base_entropy_threshold: float = 0.30

    dynamic_threshold: bool = True
    min_entropy_threshold: float = 0.15
    max_entropy_threshold: float = 0.65
    latency_sensitivity: float = 0.3

    max_tokens_summary: int = 128
    cost_aware_synthesis: bool = True
    budget_per_hour: Optional[int] = None

    summary_style: SynthesisMode = SynthesisMode.CONCISE
    include_confidence: bool = True
    include_alternatives: bool = False

    force_writeback: bool = False
    ttl_seconds_hint: Optional[float] = None
    importance_boosters: List[str] = field(default_factory=lambda: ["action", "decision", "critical", "todo", "deadline"])

    enable_cross_modal: bool = False
    cross_modal_confidence_threshold: float = 0.7

    mirror_callback: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None
    actor_role: Optional[str] = None
    audit_callback: Optional[Callable[[Dict[str, Any]], None]] = None


@dataclass
class ICECircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_requests: int = 3
    state: Literal["closed", "open", "half_open"] = "closed"
    failure_count: int = 0
    last_failure_time: Optional[float] = None

    def _m(self) -> int:
        return {"closed": 0, "half_open": 1, "open": 2}[self.state]

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time and (time.time() - self.last_failure_time > self.recovery_timeout):
                self.state = "half_open"; self.failure_count = 0
                M_CB.set(self._m())
                return True
            return False
        return self.failure_count < self.half_open_requests

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == "half_open" or self.failure_count >= self.failure_threshold:
            self.state = "open"
        M_CB.set(self._m())

    def record_success(self) -> None:
        if self.state in ("half_open", "open"):
            self.state = "closed"; self.failure_count = 0
        M_CB.set(self._m())


@dataclass
class ReasoningTrace:
    request_text: str
    entropy: float
    top_score: float
    normalized_entropy: float
    memory_matches: List[Dict[str, Any]]
    synthesis: str
    writeback_applied: bool

    recall_strategy_used: RecallStrategy
    synthesis_mode: SynthesisMode
    cross_modal_matches: Optional[List[Dict[str, Any]]] = None
    confidence_estimate: float = 0.0
    alternative_syntheses: List[str] = field(default_factory=list)

    writeback_record_id: Optional[int] = None
    latency_ms: float = 0.0
    token_usage: int = 0
    cost_estimate: float = 0.0
    circuit_breaker_state: str = "closed"

    policy_snapshot: Dict[str, Any] = field(default_factory=dict)
    performance_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for m in d.get("memory_matches", []):
            p = m.get("payload", {})
            t = p.get("text")
            if isinstance(t, str) and len(t) > 300:
                p["text"] = t[:300] + "…"
        return d


class PremiumICEWrapper:
    """Premium ICE with SR/ICE adapters and policy orchestration."""

    def __init__(
        self,
        *,
        sr: Optional[SRRetriever] = None,
        subengine: Optional[SynthesisSubEngine] = None,
        llm: Optional[LLMUtils] = None,
        policy: Optional[ICEWritebackPolicy] = None,
        recall_strategy: RecallStrategy = RecallStrategy.CASCADE,
        enable_telemetry: bool = True,
    ) -> None:
        # If no SR adapter injected, fall back to SoftReasoningEngine's native API via an internal adapter
        self._engine = SoftReasoningEngine()
        self.sr = sr or _SoftEngineAdapter(self._engine)
        self.subengine = subengine  # optional
        self.llm = llm or (get_registry().get_active() or LLMUtils())  # type: ignore[attr-defined]
        self.policy = policy or ICEWritebackPolicy()
        self.recall_strategy = recall_strategy

        self.baseline = ICEPerformanceBaseline()
        self.cb = ICECircuitBreaker()
        self.telemetry = enable_telemetry
        self._token_budget_used = 0
        self._budget_reset_time = time.time()
        self._lock = threading.RLock()

        logger.info("Premium ICE v3.1 initialized (strategy=%s, subengine=%s)", recall_strategy.value, type(subengine).__name__ if subengine else "None")

    # ---------- Public API ----------

    def process(self, text: str, *, metadata: Optional[Dict[str, Any]] = None) -> ReasoningTrace:
        with self._lock:
            with self._cb_guard():
                return self._process_internal(text, metadata=metadata)

    async def aprocess(self, text: str, *, metadata: Optional[Dict[str, Any]] = None) -> ReasoningTrace:
        return await asyncio.to_thread(self.process, text, metadata=metadata)

    # ---------- Core ----------

    def _process_internal(self, text: str, *, metadata: Optional[Dict[str, Any]] = None) -> ReasoningTrace:
        t0 = time.time()
        try:
            matches, strategy = self._recall(text, metadata)
            cross = self._cross_modal(text)

            entropy, top = self._entropy(matches)
            norm = self._z_entropy(entropy)

            thr = self._threshold()
            if callable(self.policy.mirror_callback):
                try: self.policy.mirror_callback(text, matches)
                except Exception: pass

            context = "\n".join(f"- {m.get('payload', {}).get('text', '')}" for m in matches if m.get("payload")).strip()
            conf = self._confidence(top, norm, len(matches))
            mode = self._mode(entropy, conf, text)

            max_tok = int(self.policy.max_tokens_summary)
            synthesis, alt, tok = self._synthesize(text, context, mode, conf, max_tok)

            wb_applied, wb_id = self._writeback(text, entropy, thr, synthesis, metadata)

            trace = ReasoningTrace(
                request_text=text,
                entropy=entropy,
                top_score=top,
                normalized_entropy=norm,
                memory_matches=matches,
                synthesis=synthesis,
                writeback_applied=wb_applied,
                recall_strategy_used=strategy,
                synthesis_mode=mode,
                cross_modal_matches=cross or None,
                confidence_estimate=conf,
                alternative_syntheses=alt,
                writeback_record_id=wb_id,
                latency_ms=(time.time() - t0) * 1000.0,
                token_usage=tok,
                cost_estimate=float(tok) * 0.0001,
                circuit_breaker_state=self.cb.state,
                policy_snapshot={
                    "effective_threshold": thr,
                    "strategy": self.recall_strategy.value,
                    "mode": mode.value,
                    "actor_role": self.policy.actor_role,
                },
                performance_context={
                    "avg_entropy": self.baseline.avg_entropy,
                    "entropy_std": self.baseline.entropy_std,
                    "success_rate": self.baseline.success_rate,
                    "p95_latency": self.baseline.p95_latency,
                    "sample_count": self.baseline.sample_count,
                },
            )

            self.baseline.update(entropy, trace.latency_ms, True)
            if METRICS: M_LAT.observe(trace.latency_ms)
            self._audit(trace)

            logger.info("ICE v3.1: ent=%.3f norm=%.3f mode=%s wb=%s lat=%.1fms", entropy, norm, mode.value, wb_applied, trace.latency_ms)
            return trace

        except Exception as e:
            lat = (time.time() - t0) * 1000.0
            self.baseline.update(0.0, lat, False)
            logger.error("ICE process failed: %s", e)
            raise

    # ---------- Recall ----------

    def _recall(self, text: str, metadata: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], RecallStrategy]:
        strategies = [RecallStrategy.HYBRID, RecallStrategy.SEMANTIC, RecallStrategy.TEMPORAL] if self.recall_strategy == RecallStrategy.CASCADE else [self.recall_strategy]
        last_err: Optional[Exception] = None
        for s in strategies:
            try:
                if s == RecallStrategy.SEMANTIC:
                    out = self.sr.query(text, top_k=5, metadata_filter=metadata)
                elif s == RecallStrategy.TEMPORAL:
                    out = self.sr.query(text, top_k=5, metadata_filter=metadata)
                    for m in out:
                        sc = float(m.get("score", 0.0))
                        m["score"] = min(1.0, sc + (1.0 - sc) * 0.15)
                    out.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
                else:  # HYBRID
                    sem = self.sr.query(text, top_k=4, metadata_filter=metadata)
                    tmp = self.sr.query(text, top_k=4, metadata_filter=metadata)
                    for m in tmp:
                        sc = float(m.get("score", 0.0))
                        m["score"] = min(1.0, sc + (1.0 - sc) * 0.10)
                    allm = {id(x): x for x in (sem + tmp)}
                    out = sorted(allm.values(), key=lambda r: float(r.get("score", 0.0)), reverse=True)[:5]
                if METRICS: M_STRAT.labels(strategy=s.value).inc()
                return out, s
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("Recall failed")

    # ---------- Cross-modal (optional hook) ----------

    def _cross_modal(self, text: str) -> List[Dict[str, Any]]:
        if not self.policy.enable_cross_modal or memory_hub is None:
            return []
        try:
            matches = memory_hub.get_cross_modal(text) or []
            thr = float(self.policy.cross_modal_confidence_threshold)
            return [m for m in matches if float(m.get("confidence", 1.0)) >= thr]
        except Exception:
            return []

    # ---------- Synthesis ----------

    def _prompt(self, text: str, context: str, mode: SynthesisMode, conf: float, include_alts: bool) -> str:
        header = "You are Kari's Premium Reasoning Engine. Provide accurate, nuanced analysis."
        style = {
            SynthesisMode.CONCISE: "Provide 2-3 crisp sentences with key insights.",
            SynthesisMode.ANALYTICAL: "Analyze patterns and relationships. Include reasoning steps.",
            SynthesisMode.ACTION_ORIENTED: "Focus on actionable insights and next steps. Use imperative language.",
            SynthesisMode.MULTI_PERSPECTIVE: "Consider both sides: 'On one hand...' and 'On the other hand...'.",
        }[mode]
        conf_s = f"\nConfidence: {conf:.1%}" if self.policy.include_confidence else ""
        alt_s = "\nAlso provide 1-2 alternative interpretations briefly." if include_alts else ""
        return f"{header}\n\nContext:\n{context}\n\nUser: {text}{conf_s}\n\n{style}{alt_s}\n\nAnalysis:"

    def _extract_alts(self, txt: str) -> Tuple[str, List[str]]:
        lines = txt.splitlines()
        main, alts, cur = [], [], "main"
        for line in lines:
            if any(k in line.lower() for k in ("alternative", "another perspective", "different interpretation")):
                cur = "alts"; continue
            (alts if cur == "alts" else main).append(line)
        primary = "\n".join(main).strip()
        alt = [s.strip(" -•\t") for s in "\n".join(alts).split("•") if s.strip()]
        return primary, alt

    def _synthesize(self, text: str, context: str, mode: SynthesisMode, conf: float, max_tokens: int) -> Tuple[str, List[str], int]:
        # Budget
        if not self._check_budget():
            if METRICS: M_FB.labels(type="budget").inc()
            return "Response limited due to resource constraints. Please try again later.", [], 0

        # If a subengine is present (LangGraph/DSPy…), let it try first
        if self.subengine:
            try:
                out = self.subengine.run(text=text, context=context, mode=mode.value, max_tokens=max_tokens)
                if isinstance(out, str) and out.strip():
                    prim, alts = self._extract_alts(out.strip())
                    tokens = max(1, len(out.split()))
                    self._record_tokens(tokens, mode.value)
                    return prim, alts, tokens
            except Exception:
                if METRICS: M_FB.labels(type="subengine").inc()
                # fall back to LLM prompt below

        # Prompt-first LLM fallback
        prompt = self._prompt(text, context, mode, conf, self.policy.include_alternatives)
        try:
            resp = self.llm.generate_text(prompt, max_tokens=max_tokens).strip()
        except Exception:
            if METRICS: M_FB.labels(type="llm_exception").inc()
            resp = "Unable to synthesize a response at this time."
        prim, alts = self._extract_alts(resp)
        tokens = max(1, len(resp.split()))
        self._record_tokens(tokens, mode.value)
        return prim, alts, tokens

    # ---------- Decisions ----------

    def _entropy(self, matches: List[Dict[str, Any]]) -> Tuple[float, float]:
        top = float(matches[0]["score"]) if matches else 0.0
        return 1.0 - top, top

    def _z_entropy(self, entropy: float) -> float:
        std = max(1e-6, self.baseline.entropy_std)
        return (entropy - self.baseline.avg_entropy) / std

    def _threshold(self) -> float:
        base = self.policy.base_entropy_threshold
        if not self.policy.dynamic_threshold:
            return base
        pen = self.policy.latency_sensitivity * 0.1 if self.baseline.p95_latency > 1000 else 0.0
        bonus = -0.05 if self.baseline.success_rate > 0.95 else 0.0
        thr = base + pen + bonus
        return max(self.policy.min_entropy_threshold, min(self.policy.max_entropy_threshold, thr))

    def _confidence(self, top: float, z_ent: float, count: int) -> float:
        return max(0.0, min(1.0, top - max(0.0, z_ent * 0.1) + min(0.2, count * 0.05)))

    def _importance(self, text: str, synthesis: str) -> float:
        imp = 0.2
        tl = (text + " " + synthesis).lower()
        for b in self.policy.importance_boosters:
            if b in tl: imp += 0.3; break
        if "?" in text: imp += 0.2
        if len(synthesis.split()) > 25: imp += 0.2
        return min(1.0, imp)

    def _writeback(self, text: str, entropy: float, thr: float, synthesis: str, metadata: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[int]]:
        if not self.policy.enable:
            return False, None
        imp = self._importance(text, synthesis)
        if self.policy.force_writeback or (entropy + (0.2 if imp > 0.7 else 0.0)) > thr:
            meta = dict(metadata or {}); meta.update({"source": "PremiumICE", "importance": imp, "timestamp": time.time(), "version": "3.1"})
            try:
                rid = self.sr.ingest(text, meta, ttl_seconds=self.policy.ttl_seconds_hint, force=self.policy.force_writeback)
                tier = "long" if (self.policy.ttl_seconds_hint and self.policy.ttl_seconds_hint >= 86400) or imp >= 0.7 else "default"
                if METRICS: M_WB.labels(tier=tier).inc()
                return True, int(rid) if rid is not None else None
            except Exception:
                return False, None
        return False, None

    # ---------- Budget / Tokens ----------

    def _check_budget(self) -> bool:
        if not self.policy.budget_per_hour: return True
        now = time.time()
        if now - self._budget_reset_time > 3600:
            self._token_budget_used = 0; self._budget_reset_time = now
        return self._token_budget_used < int(self.policy.budget_per_hour)

    def _record_tokens(self, tokens: int, mode: str) -> None:
        self._token_budget_used += max(0, int(tokens))
        if METRICS: M_TOK.labels(mode=mode).inc(tokens)

    # ---------- Circuit breaker ----------

    @contextmanager
    def _cb_guard(self):
        if not self.cb.can_execute():
            raise RuntimeError("Circuit breaker is open")
        try:
            yield
            self.cb.record_success()
        except Exception:
            self.cb.record_failure()
            raise

    # ---------- Audit ----------

    def _audit(self, trace: ReasoningTrace) -> None:
        if callable(self.policy.audit_callback):
            try:
                self.policy.audit_callback({"actor_role": self.policy.actor_role, "trace": trace.to_dict(), "ts": time.time(), "component": "PremiumICEWrapper"})
            except Exception:
                pass


class _SoftEngineAdapter(SRRetriever):
    """Internal adapter to expose SoftReasoningEngine as SRRetriever."""
    def __init__(self, engine: SoftReasoningEngine) -> None:
        self._e = engine

    def query(self, text: str, *, top_k: int = 5, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._e.query(text, top_k=top_k, metadata_filter=metadata_filter)

    def ingest(self, text: str, metadata: Optional[Dict[str, Any]] = None, *, ttl_seconds: Optional[float] = None, force: bool = False) -> Optional[int]:
        return self._e.ingest(text, metadata, ttl_seconds=ttl_seconds)
