"""
Behavior pattern contracts for AI-Karen personalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts import BehaviorPattern, PreferenceStability


@dataclass
class BehaviorObservation:
    """Single observation contributing to a behavior pattern."""
    observation_id: str
    pattern_id: str
    user_id: str
    tenant_id: str
    context_signature: str
    action: str
    outcome: str
    observed_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class BehaviorPatternStore:
    """Stores and manages behavior patterns."""

    def __init__(self):
        self._patterns: Dict[str, BehaviorPattern] = {}

    def upsert(self, pattern: BehaviorPattern) -> None:
        self._patterns[pattern.pattern_id] = pattern

    def get(self, pattern_id: str) -> Optional[BehaviorPattern]:
        return self._patterns.get(pattern_id)

    def list_for_user(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        return [
            p for p in self._patterns.values()
            if p.user_id == user_id and p.tenant_id == tenant_id
        ]

    def all(self) -> List[BehaviorPattern]:
        return list(self._patterns.values())


__all__ = ["BehaviorObservation", "BehaviorPatternStore"]
