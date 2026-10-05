"""Behavior observation contracts for personalization learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


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


__all__ = ["BehaviorObservation"]
