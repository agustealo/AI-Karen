"""Governed compatibility shims for cognitive contract convergence.

A shim may exist only with a canonical replacement and a removal date. New code
must import the canonical contract, never the legacy symbol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CompatibilityShim:
    legacy_symbol: str
    canonical_symbol: str
    owner: str
    reason: str
    remove_after: date


COGNITIVE_COMPATIBILITY_SHIMS: tuple[CompatibilityShim, ...] = (
    CompatibilityShim(
        legacy_symbol="ai_karen_engine.core.personalization.contracts.UserGoalStatus",
        canonical_symbol="ai_karen_engine.core.personalization.goals.contracts.GoalState",
        owner="personalization/goals",
        reason=(
            "active stored UserGoal/UserModel contracts and GoalStore lifecycle still "
            "consume UserGoalStatus; migrate persistence readers before removal"
        ),
        remove_after=date(2026, 10, 15),
    ),
)


def expired_shims(today: date | None = None) -> tuple[CompatibilityShim, ...]:
    current = today or date.today()
    return tuple(shim for shim in COGNITIVE_COMPATIBILITY_SHIMS if shim.remove_after < current)


__all__ = ["COGNITIVE_COMPATIBILITY_SHIMS", "CompatibilityShim", "expired_shims"]
