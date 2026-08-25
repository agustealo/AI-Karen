"""
Relationship Model for AI-Karen

Karen↔User relationship model.
Tracks shared history and relationship-specific context.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.memory.contracts import RelationshipModel


class RelationshipModelStore:
    """
    Stores and manages Karen↔User relationship model.
    """

    def __init__(self):
        self._model = RelationshipModel()

    def get(self) -> RelationshipModel:
        """Get the current relationship model."""
        return self._model

    def add_shared_project(self, project: str) -> None:
        """Add a shared project."""
        if project not in self._model.shared_projects:
            self._model.shared_projects.append(project)

    def record_decision(self, decision: dict[str, Any]) -> None:
        """Record a past decision."""
        self._model.past_decisions.append({
            **decision,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })

    def set_interaction_style(self, key: str, value: Any) -> None:
        """Set an interaction style attribute."""
        self._model.interaction_style[key] = value

    def add_trust_fact(self, fact: str) -> None:
        """Add a trust-relevant fact."""
        if fact not in self._model.trust_relevant_facts:
            self._model.trust_relevant_facts.append(fact)

    def add_unresolved_thread(self, thread: str) -> None:
        """Add an unresolved thread."""
        if thread not in self._model.unresolved_threads:
            self._model.unresolved_threads.append(thread)

    def record_interaction(self, interaction: dict[str, Any]) -> None:
        """Record an interaction."""
        self._model.interaction_history.append({
            **interaction,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
