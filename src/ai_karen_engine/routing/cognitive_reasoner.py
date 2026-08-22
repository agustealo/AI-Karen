"""Cognitive scaffolding for KIRE routing decisions.

The :class:`CognitiveReasoner` implements a lightweight cognitive
architecture inspired by global workspace theory and dual process models.
It synthesizes task analysis signals, user state, and profile metadata
to produce a deliberative vector that the router can use to steer model
selection in a more human-like manner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.routing.types import RouteRequest, UserProfile


@dataclass
class TaskAnalysis:
    """Minimal stub for legacy routing compatibility."""

    task_type: str = "chat"
    required_capabilities: List[str] = field(default_factory=list)
    tool_intents: List[str] = field(default_factory=list)
    hints: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    user_need_state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingCognition:
    """Structured cognition surface for routing.

    Attributes mirror components from contemporary cognitive science:

    * ``primary_goal`` represents the conscious spotlight (global workspace)
    * ``secondary_goals`` models peripheral intents competing for attention
    * ``recommended_tools`` suggests affordances for tool-augmented flows
    * ``need_urgency`` and ``persona_bias`` emulate affective modulation
    * ``decision_vector`` encodes normalized weights across cognitive axes
    * ``narrative`` is a natural language trace for observability
    """

    primary_goal: str
    secondary_goals: List[str] = field(default_factory=list)
    recommended_tools: List[str] = field(default_factory=list)
    need_urgency: str = "normal"
    persona_bias: Optional[str] = None
    decision_vector: Dict[str, float] = field(default_factory=dict)
    narrative: str = ""
    confidence: float = 0.6


class CognitiveReasoner:
    """Derive human-like decision scaffolding from routing signals."""

    def evaluate(
        self,
        request: RouteRequest,
        analysis: TaskAnalysis,
        profile: Optional[UserProfile],
    ) -> RoutingCognition:
        context = request.context or {}
        user_need = analysis.user_need_state or {}
        urgency = user_need.get("urgency", "normal")
        affect = user_need.get("affect", "neutral")

        persona = None
        if isinstance(context.get("persona"), str):
            persona = context["persona"]
        elif isinstance(context.get("user_persona"), str):
            persona = context["user_persona"]
        elif profile and profile.khrp_config:
            persona = profile.khrp_config.get("persona")

        secondary_goals = []
        secondary_hints = analysis.hints.get("secondary_tasks") if analysis.hints else []
        if isinstance(secondary_hints, list):
            secondary_goals = [str(goal) for goal in secondary_hints if goal and goal != analysis.task_type]

        tool_bias = analysis.tool_intents or []
        context_tools = []
        suggested = context.get("tool_suggestions") or context.get("tools")
        if isinstance(suggested, (list, tuple)):
            context_tools = [str(tool).lower() for tool in suggested if isinstance(tool, str)]

        recommended_tools = []
        for tool in tool_bias + context_tools:
            if tool not in recommended_tools:
                recommended_tools.append(tool)

        contributions: Dict[str, float] = {}
        # Conscious focus weight is tied to analysis confidence
        contributions["task_weight"] = max(0.2, min(0.6, analysis.confidence))

        # Urgency modulates executive focus (System 1 override)
        if urgency == "high":
            contributions["urgency_weight"] = 0.45
        elif urgency == "elevated":
            contributions["urgency_weight"] = 0.25
        else:
            contributions["urgency_weight"] = 0.12

        # Affect influences need for supportive reasoning providers
        if affect in {"stressed", "frustrated"}:
            contributions["affect_weight"] = 0.2
        elif affect == "curious":
            contributions["affect_weight"] = 0.15
        else:
            contributions["affect_weight"] = 0.08

        # Tool alignment fosters distributed cognition
        contributions["tool_alignment"] = 0.18 if recommended_tools else 0.05

        # Persona bias shifts style preference (e.g., creative vs. analytical)
        contributions["persona_alignment"] = 0.16 if persona else 0.07

        total = sum(contributions.values()) or 1.0
        decision_vector = {k: round(v / total, 3) for k, v in contributions.items()}

        narrative_fragments: List[str] = [
            f"goal={analysis.task_type}",
            f"urgency={urgency}",
            f"affect={affect}",
        ]
        if secondary_goals:
            narrative_fragments.append(f"secondary={','.join(secondary_goals)}")
        if recommended_tools:
            narrative_fragments.append(f"tools={','.join(recommended_tools)}")
        if persona:
            narrative_fragments.append(f"persona={persona}")

        narrative = "; ".join(narrative_fragments)

        confidence = min(0.98, max(0.5, analysis.confidence + decision_vector.get("urgency_weight", 0.0) * 0.3))

        return RoutingCognition(
            primary_goal=analysis.task_type,
            secondary_goals=secondary_goals,
            recommended_tools=recommended_tools,
            need_urgency=urgency,
            persona_bias=persona,
            decision_vector=decision_vector,
            narrative=narrative,
            confidence=confidence,
        )
