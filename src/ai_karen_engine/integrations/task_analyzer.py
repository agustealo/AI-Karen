"""
Lightweight TaskAnalyzer for query classification and capability mapping.

Classifies a user query into task types and required capabilities to
inform KIRE routing decisions and KHRP step selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TaskAnalysis:
    task_type: str
    required_capabilities: List[str] = field(default_factory=list)
    khrp_step_hint: Optional[str] = None
    hints: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    tool_intents: List[str] = field(default_factory=list)
    user_need_state: Dict[str, Any] = field(default_factory=dict)


class TaskAnalyzer:
    """Pattern-based query classifier with provider capability mapping."""

    # Task keyword patterns (weighted heuristic)
    _TASK_PATTERNS: Dict[str, List[Tuple[str, float]]] = {
        "code": [("code", 1.0), ("bug", 1.0), ("fix", 0.9), ("function", 0.6), ("class", 0.6), ("python", 1.1), ("typescript", 1.1), ("compile", 0.8), ("refactor", 1.0)],
        "reasoning": [("reason", 0.8), ("explain", 0.7), ("analyze", 0.9), ("logic", 0.9), ("why", 0.6), ("prove", 1.0), ("derive", 1.0), ("theorem", 1.2)],
        "summarization": [("summarize", 1.0), ("tl;dr", 1.2), ("brief", 0.7), ("condense", 0.8), ("summary", 0.7)],
        "embedding": [("embed", 1.0), ("embedding", 1.0), ("semantic", 0.7), ("vector", 0.7), ("similarity", 0.6)],
        "lookup": [("search", 0.8), ("lookup", 0.8), ("find", 0.6), ("retrieve", 0.9), ("fetch", 0.6), ("documentation", 0.7)],
        "calc": [("calculate", 0.9), ("compute", 0.9), ("sum", 0.6), ("average", 0.6), ("mean", 0.6), ("median", 0.6), ("arithmetic", 0.8), ("equation", 1.1)],
        "chat": [("chat", 0.4), ("talk", 0.4), ("discuss", 0.5), ("conversation", 0.4), ("help", 0.2)],
    }

    # Capability mapping per task
    _TASK_CAPABILITIES: Dict[str, List[str]] = {
        "code": ["text", "code", "reasoning"],
        "reasoning": ["text", "reasoning"],
        "summarization": ["text"],
        "embedding": ["embeddings"],
        "lookup": ["text"],
        "calc": ["text", "reasoning"],
        "chat": ["text"],
    }

    # Provider capability hints
    _PROVIDER_CAPABILITIES: Dict[str, List[str]] = {
        "openai": ["text", "reasoning", "function_calling", "streaming"],
        "deepseek": ["text", "code", "reasoning"],
        "local_gguf": ["text"],
        "huggingface": ["text", "embeddings"],
        "gemini": ["text", "vision", "code", "reasoning", "streaming"],
    }

    _ROLE_TASK_HINTS: Dict[str, Tuple[str, float]] = {
        "developer": ("code", 0.8),
        "engineer": ("code", 0.5),
        "analyst": ("reasoning", 0.5),
        "support": ("chat", 0.4),
    }

    _TOOL_PATTERNS: Dict[str, List[Tuple[str, float]]] = {
        "web_browse": [("browser", 1.1), ("web", 0.8), ("search", 0.9), ("lookup", 0.8), ("internet", 1.0)],
        "code_execution": [("run", 1.0), ("execute", 1.0), ("script", 0.8), ("test", 0.6), ("stack trace", 0.9)],
        "data_viz": [("chart", 0.8), ("plot", 0.8), ("visualize", 0.9)],
        "retrieval": [("document", 0.7), ("knowledge base", 1.0), ("wiki", 0.8), ("reference", 0.7)],
        "function_calling": [("tool", 0.6), ("call", 0.6), ("api", 0.8), ("function", 0.7), ("automation", 0.8)],
    }

    _EXPLICIT_TOOL_MAP: Dict[str, str] = {
        "browser": "web_browse",
        "web_browser": "web_browse",
        "web_search": "web_browse",
        "code_runner": "code_execution",
        "executor": "code_execution",
        "sandbox": "code_execution",
        "retriever": "retrieval",
        "vector_search": "retrieval",
        "function_call": "function_calling",
    }

    _AFFECTIVE_CUES: Dict[str, Tuple[str, float]] = {
        "urgent": ("high", 0.45),
        "asap": ("high", 0.5),
        "right now": ("high", 0.4),
        "stuck": ("elevated", 0.35),
        "blocked": ("elevated", 0.35),
        "confused": ("elevated", 0.25),
        "frustrated": ("elevated", 0.25),
        "important": ("elevated", 0.2),
        "curious": ("curious", 0.2),
    }

    def analyze(self, query: str, user_ctx: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> TaskAnalysis:
        q = (query or "").lower()
        context = context or {}
        history_fragments: List[str] = []
        history = context.get("conversation_history")
        if isinstance(history, list):
            for entry in history[-3:]:
                if isinstance(entry, dict):
                    content = (entry.get("content") or "").lower()
                    if content:
                        history_fragments.append(content)
        augmented_query = " ".join([q] + history_fragments)

        tokens = set(re.findall(r"\w+", augmented_query))
        scores: Dict[str, float] = {task: 0.0 for task in self._TASK_PATTERNS}
        hints: Dict[str, Any] = {}

        for task, patterns in self._TASK_PATTERNS.items():
            for keyword, weight in patterns:
                if keyword in augmented_query:
                    scores[task] += weight
                elif keyword in tokens:
                    scores[task] += weight * 0.9

        requirements = context.get("requirements", {})

        task_hint = (context.get("task_hint") or context.get("task_type") or "").lower()
        if task_hint in scores:
            scores[task_hint] += 2.5
            hints["task_hint"] = task_hint

        capability_hints = requirements.get("capabilities") or context.get("capability_hints")
        if capability_hints:
            caps = {c.lower() for c in capability_hints}
            for task, task_caps in self._TASK_CAPABILITIES.items():
                overlap = caps.intersection({c.lower() for c in task_caps})
                if overlap:
                    scores[task] += 0.6 + 0.2 * len(overlap)
            hints["capabilities"] = list(caps)

        roles = {r.lower() for r in (user_ctx or {}).get("roles", [])}
        for role in roles:
            task_hint_role = self._ROLE_TASK_HINTS.get(role)
            if task_hint_role:
                hinted_task, boost = task_hint_role
                scores[hinted_task] += boost
                hints.setdefault("role_hints", set()).add(role)

        if "role_hints" in hints and isinstance(hints["role_hints"], set):
            hints["role_hints"] = sorted(hints["role_hints"])

        tool_scores: Dict[str, float] = {tool: 0.0 for tool in self._TOOL_PATTERNS}
        for tool, patterns in self._TOOL_PATTERNS.items():
            for keyword, weight in patterns:
                if keyword in augmented_query:
                    tool_scores[tool] += weight
                elif keyword in tokens:
                    tool_scores[tool] += weight * 0.85

        explicit_tools = context.get("tool_suggestions") or context.get("tools")
        if isinstance(explicit_tools, (list, tuple)):
            for tool in explicit_tools:
                if isinstance(tool, str):
                    key = tool.lower()
                    canonical = self._EXPLICIT_TOOL_MAP.get(key, key)
                    tool_scores.setdefault(canonical, 0.0)
                    tool_scores[canonical] += 1.2

        tool_intents = sorted(tool for tool, score in tool_scores.items() if score >= 1.2)
        if tool_intents:
            hints["tools"] = tool_intents
            if "code_execution" in tool_intents:
                scores["code"] += 1.1
            if "web_browse" in tool_intents:
                scores["lookup"] += 0.8
            if "function_calling" in tool_intents:
                scores["reasoning"] += 0.5

        affect_signals: List[str] = []
        urgency_level = "normal"
        affect_state = "neutral"
        for cue, (level, boost) in self._AFFECTIVE_CUES.items():
            if cue in augmented_query:
                affect_signals.append(cue)
                if level == "high":
                    urgency_level = "high"
                elif level == "elevated" and urgency_level != "high":
                    urgency_level = "elevated"
                if level in {"high", "elevated"}:
                    scores["reasoning"] += boost * 0.6
                    scores["chat"] += boost * 0.4
                    affect_state = "stressed"
                elif level == "curious" and affect_state == "neutral":
                    affect_state = "curious"

        # Detect multilingual queries (non-ascii) -> reasoning/chat bias
        if any(ord(ch) > 127 for ch in q):
            scores["chat"] += 0.3
            scores["reasoning"] += 0.3
            hints["multilingual"] = True

        best_task = max(scores, key=scores.get)
        best_score = scores[best_task]
        if best_score <= 0.3:
            best_task = "chat"
            best_score = scores.get("chat", 0.0)

        ordered_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        secondary_candidates = [task for task, score in ordered_scores[1:3] if score and (best_score - score) <= 0.8]
        if secondary_candidates:
            hints["secondary_tasks"] = secondary_candidates

        caps = self._TASK_CAPABILITIES.get(best_task, ["text"])
        step = None
        if best_task in ("reasoning", "calc"):
            step = "reasoning_core"
        elif best_task == "summarization":
            step = "output_rendering"
        elif best_task == "lookup":
            step = "evidence_gathering"

        confidence = 0.55 + min(best_score / 5.0, 0.35)
        if urgency_level == "high":
            confidence += 0.05
        confidence = min(confidence, 0.95)

        need_mode = "informational"
        if best_task == "code":
            need_mode = "problem_solving"
        elif best_task == "reasoning":
            need_mode = "analysis"
        elif best_task == "summarization":
            need_mode = "synthesis"
        elif best_task == "embedding":
            need_mode = "retrieval"

        if "code_execution" in tool_intents and need_mode == "informational":
            need_mode = "problem_solving"

        user_need_state = {
            "mode": need_mode,
            "urgency": urgency_level,
            "affect": affect_state,
            "signals": affect_signals,
        }
        if secondary_candidates:
            user_need_state["adjacent_tasks"] = secondary_candidates

        if tool_intents:
            user_need_state["tool_bias"] = tool_intents

        return TaskAnalysis(
            task_type=best_task,
            required_capabilities=caps,
            khrp_step_hint=step,
            hints=hints,
            confidence=confidence,
            tool_intents=tool_intents,
            user_need_state=user_need_state,
        )

    def provider_supports(self, provider: str, required_caps: List[str]) -> bool:
        caps = self._PROVIDER_CAPABILITIES.get(provider.lower(), ["text"])  # assume at least text
        return all(c in caps for c in required_caps)
