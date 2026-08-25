"""
User Model for AI-Karen

Karen's model of the user.
Evidence-backed: no one-event canon.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import MemoryClaim, UserModel


class UserModelStore:
    """
    Stores and manages Karen's user model.
    """

    def __init__(self):
        self._model = UserModel()

    def get(self) -> UserModel:
        """Get the current user model."""
        return self._model

    def record_preference(self, key: str, value: Any, confidence: float = 0.5, source: str = "inferred") -> None:
        """Record a user preference."""
        if source == "explicit":
            self._model.explicit_preferences[key] = value
        else:
            self._model.inferred_preferences[key] = confidence

    def update_preference_confidence(self, key: str, new_confidence: float) -> None:
        """Update confidence of an inferred preference."""
        if key in self._model.inferred_preferences:
            self._model.inferred_preferences[key] = new_confidence

    def add_project(self, project: str) -> None:
        """Add a user project."""
        if project not in self._model.projects:
            self._model.projects.append(project)

    def add_goal(self, goal: str) -> None:
        """Add a user goal."""
        if goal not in self._model.goals:
            self._model.goals.append(goal)

    def add_belief(self, claim: MemoryClaim) -> None:
        """Add a belief about the user."""
        self._model.evolving_beliefs.append(claim)

    def get_preference(self, key: str) -> Any | None:
        """Get a preference value."""
        if key in self._model.explicit_preferences:
            return self._model.explicit_preferences[key]
        return self._model.inferred_preferences.get(key)

    def get_preference_confidence(self, key: str) -> float:
        """Get confidence of a preference."""
        if key in self._model.explicit_preferences:
            return 1.0
        return self._model.inferred_preferences.get(key, 0.0)
