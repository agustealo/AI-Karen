"""
Self Model for AI-Karen

Karen's governed model of itself.
Provides continuity without pretending consciousness.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import SelfModel


class SelfModelStore:
    """
    Stores and manages Karen's self model.
    """

    def __init__(self):
        self._model = SelfModel()

    def get(self) -> SelfModel:
        """Get the current self model."""
        return self._model

    def update_identity(self, **kwargs: Any) -> None:
        """Update identity fields."""
        self._model.identity.update(kwargs)

    def add_capability(self, capability: str) -> None:
        """Add a capability."""
        if capability not in self._model.capabilities:
            self._model.capabilities.append(capability)

    def set_capability_limit(self, capability: str, limit: str) -> None:
        """Set a limit for a capability."""
        self._model.capability_limits[capability] = limit

    def add_commitment(self, commitment: str) -> None:
        """Add a current commitment."""
        if commitment not in self._model.current_commitments:
            self._model.current_commitments.append(commitment)

    def remove_commitment(self, commitment: str) -> None:
        """Remove a completed commitment."""
        if commitment in self._model.current_commitments:
            self._model.current_commitments.remove(commitment)

    def add_active_goal(self, goal: str) -> None:
        """Add an active goal."""
        if goal not in self._model.active_goals:
            self._model.active_goals.append(goal)

    def record_significant_decision(self, decision: Dict[str, Any]) -> None:
        """Record a significant decision."""
        self._model.significant_decisions.append({
            **decision,
            "timestamp": datetime.utcnow().isoformat(),
        })
