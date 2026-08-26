"""Deprecated LangGraph analysis compatibility adapter.

Canonical analysis lives in ``core.intelligence``. LangGraph must not own or
re-export a second NLP/intent authority. The adapter remains only for legacy
callers of ``DecisionEngine.analyze_intent`` while those callers migrate to
Runtime/CORTEX-propagated execution decisions.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime


class DecisionEngine:
    """Thin compatibility adapter over canonical IntelligenceRuntime."""

    def __init__(self, intelligence_runtime: Optional[IntelligenceRuntime] = None) -> None:
        self._intelligence = intelligence_runtime or IntelligenceRuntime()

    async def analyze_intent(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = await self._intelligence.analyze(prompt, context or {})
        return {
            "primary_intent": result.intent or "general_assist",
            "intent": result.intent or "general_assist",
            "confidence": float(result.intent_confidence or 0.0),
            "entities": list(result.entities or []),
            "topics": list(result.topics or []),
            "suggested_tools": [],
            "requires_clarification": False,
            "metadata": {
                "source": "core.intelligence",
                "task_complexity": result.task_complexity,
                "memory_relevance": result.memory_relevance,
                "capability_hints": dict(result.capability_hints or {}),
                "topology_signals": dict(result.topology_signals or {}),
                "risk_signals": dict(result.risk_signals or {}),
                "degraded": bool(result.degraded),
                "latency_ms": result.latency_ms,
            },
        }


__all__ = ["DecisionEngine"]
