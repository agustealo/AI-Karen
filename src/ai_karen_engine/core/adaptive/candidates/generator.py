"""Action candidate generator.

Produces feasible action candidates from task signature and available capabilities.
Candidate generation is not authorization.
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)

logger = logging.getLogger(__name__)


class ActionCandidateGenerator:
    """Generates feasible action candidates for a given context."""

    def __init__(
        self,
        system_capabilities: SystemCapabilitySnapshot | None = None,
    ) -> None:
        self._system_capabilities = system_capabilities or SystemCapabilitySnapshot()

    def generate(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        available_capabilities: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate feasible action candidates.

        Returns a list of candidate dicts with at least:
        - action_type: AdaptiveActionType
        - target_id: Optional[str]
        - source: str
        """
        candidates: list[dict[str, Any]] = []

        complexity = getattr(task_signature, "complexity", "simple")
        ambiguity = getattr(task_signature, "ambiguity", "clear")
        risk = getattr(task_signature, "risk", "low")
        tool_requirements = getattr(task_signature, "tool_requirements", []) or []
        reasoning_requirements = getattr(task_signature, "reasoning_requirements", []) or []
        collaboration_value = getattr(task_signature, "collaboration_value", 0.0)
        verification_value = getattr(task_signature, "verification_value", 0.0)

        candidates.append({
            "action_type": AdaptiveActionType.RESPOND_DIRECTLY,
            "target_id": None,
            "source": "generator.default",
        })

        if ambiguity in ("moderate", "ambiguous", "unknown"):
            candidates.append({
                "action_type": AdaptiveActionType.ASK_CLARIFICATION,
                "target_id": None,
                "source": "generator.ambiguity",
            })

        candidates.append({
            "action_type": AdaptiveActionType.RETRIEVE_MEMORY,
            "target_id": None,
            "source": "generator.default",
        })

        if tool_requirements and self._system_capabilities.available_tools:
            for tool_id in tool_requirements:
                if tool_id in self._system_capabilities.available_tools:
                    candidates.append({
                        "action_type": AdaptiveActionType.USE_TOOL,
                        "target_id": tool_id,
                        "source": "generator.tool_requirement",
                    })

        if complexity in ("complex", "expert") or reasoning_requirements:
            candidates.append({
                "action_type": AdaptiveActionType.USE_WORKFLOW,
                "target_id": None,
                "source": "generator.complexity",
            })

        if collaboration_value > 0.3 and self._system_capabilities.available_agents:
            candidates.append({
                "action_type": AdaptiveActionType.USE_AGENT,
                "target_id": None,
                "source": "generator.collaboration",
            })

        if collaboration_value > 0.6 and verification_value > 0.3 and len(self._system_capabilities.available_agents) >= 2:
                candidates.append({
                    "action_type": AdaptiveActionType.USE_MULTI_AGENT,
                    "target_id": None,
                    "source": "generator.multi_agent",
                })

        if risk in ("high", "critical"):
            candidates.append({
                "action_type": AdaptiveActionType.SUGGEST_ACTION,
                "target_id": None,
                "source": "generator.risk",
            })

        seen = set()
        unique = []
        for c in candidates:
            key = (c["action_type"], c.get("target_id"))
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique

    def update_system_capabilities(
        self, capabilities: SystemCapabilitySnapshot
    ) -> None:
        self._system_capabilities = capabilities
