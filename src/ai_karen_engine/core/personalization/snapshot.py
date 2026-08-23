"""
User state snapshot for AI-Karen personalization.

Provides read-only snapshot generation for consumer APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import (
    BehaviorPattern,
    CurrentUserState,
    PreferenceRecord,
    UserGoal,
    UserStateSnapshot,
)


class SnapshotBuilder:
    """Builds UserStateSnapshot from personalization state."""

    def __init__(self, user_id: str, tenant_id: str):
        self.user_id = user_id
        self.tenant_id = tenant_id

    def build(
        self,
        current_state: CurrentUserState,
        all_preferences: List[PreferenceRecord],
        behavior_patterns: List[BehaviorPattern],
        active_goals: List[UserGoal],
    ) -> UserStateSnapshot:
        stable = [p for p in all_preferences if p.state in ("stable", "established")]
        tentative = [p for p in all_preferences if p.state in ("observed", "tentative", "decaying")]

        confidence_summary: Dict[str, float] = {}
        if stable:
            confidence_summary["stable_preferences_avg"] = sum(p.confidence for p in stable) / len(stable)
        if tentative:
            confidence_summary["tentative_preferences_avg"] = sum(p.confidence for p in tentative) / len(tentative)
        if behavior_patterns:
            confidence_summary["behavior_patterns_avg"] = sum(p.confidence for p in behavior_patterns) / len(behavior_patterns)

        return UserStateSnapshot(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            current_state=current_state,
            stable_preferences=stable,
            tentative_preferences=tentative,
            behavior_patterns=behavior_patterns,
            active_goals=active_goals,
            confidence_summary=confidence_summary,
            generated_at=datetime.utcnow(),
            version="1.0.0",
        )


__all__ = ["SnapshotBuilder"]
