"""Suggestion engine.

Generates user-facing advice separate from execution recommendations.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ai_karen_engine.core.adaptive.contracts import (
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.suggestions.contracts import SuggestionCandidate
from ai_karen_engine.core.adaptive.suggestions.policy import SuggestionPolicy

logger = logging.getLogger(__name__)


class SuggestionEngine:
    """Generates user-facing suggestions."""

    def __init__(
        self,
        policy: SuggestionPolicy | None = None,
    ) -> None:
        self._policy = policy or SuggestionPolicy()

    def generate(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        behavior_patterns: Any,
        system_capabilities: SystemCapabilitySnapshot,
    ) -> list[SuggestionCandidate]:
        """Generate suggestions for the current context."""
        candidates = self._generate_candidates(
            task_signature=task_signature,
            user_state=user_state,
            behavior_patterns=behavior_patterns,
            system_capabilities=system_capabilities,
        )

        surfaced = []
        for candidate in candidates:
            if self._policy.should_surface(candidate):
                self._policy.record_surface(candidate)
                surfaced.append(candidate)
            if len(surfaced) >= self._policy._max_per_request:
                break

        return surfaced

    def _generate_candidates(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        behavior_patterns: Any,
        system_capabilities: SystemCapabilitySnapshot,
    ) -> list[SuggestionCandidate]:
        candidates: list[SuggestionCandidate] = []

        workflow_count = getattr(behavior_patterns, "workflow_usage_rate", 0.0)
        if workflow_count > 0.3:
            candidates.append(SuggestionCandidate(
                suggestion_id=f"sug-{uuid.uuid4().hex}",
                suggestion_type="workflow_automation",
                subject="You have repeated similar workflows. Consider saving as automation.",
                utility=0.7,
                confidence=0.6,
                interruption_cost=0.2,
                urgency="low",
                evidence={"workflow_usage_rate": workflow_count},
                dedupe_key="workflow_automation",
            ))

        memory_available = system_capabilities.memory_available
        if memory_available:
            candidates.append(SuggestionCandidate(
                suggestion_id=f"sug-{uuid.uuid4().hex}",
                suggestion_type="memory_continuation",
                subject="There may be related context from previous conversations.",
                utility=0.5,
                confidence=0.4,
                interruption_cost=0.1,
                urgency="low",
                dedupe_key="memory_continuation",
            ))

        if len(system_capabilities.available_agents) > 1:
            candidates.append(SuggestionCandidate(
                suggestion_id=f"sug-{uuid.uuid4().hex}",
                suggestion_type="capability_available",
                subject="Multiple agents are available for this type of task.",
                utility=0.4,
                confidence=0.5,
                interruption_cost=0.3,
                urgency="low",
                dedupe_key="capability_available",
            ))

        return candidates

    def record_feedback(self, candidate: SuggestionCandidate, feedback: str) -> None:
        from ai_karen_engine.core.adaptive.suggestions.contracts import (
            SuggestionFeedbackType,
        )
        try:
            fb = SuggestionFeedbackType(feedback)
        except ValueError:
            fb = SuggestionFeedbackType.IGNORED
        if fb in (SuggestionFeedbackType.DISMISSED, SuggestionFeedbackType.CORRECTED):
            self._policy.record_dismissal(candidate)
