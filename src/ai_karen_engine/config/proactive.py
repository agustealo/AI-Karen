"""Canonical configuration for proactive continuity intelligence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProactiveContinuitySettings:
    enabled: bool = True
    max_candidates: int = 5
    min_candidate_utility: float = 0.5
    behavior_min_observations: int = 3
    behavior_min_confidence: float = 0.6
    open_loop_weight: float = 0.68
    prospective_weight: float = 0.72
    goal_weight: float = 0.58
    behavior_weight: float = 0.48
    behavior_observation_boost: float = 0.03
    behavior_max_boost: float = 0.18
    at_risk_boost: float = 0.18
    blocked_boost: float = 0.10
    overdue_boost: float = 0.12
    due_six_hours_boost: float = 0.22
    due_one_day_boost: float = 0.16
    due_three_days_boost: float = 0.10
    due_seven_days_boost: float = 0.05
    default_interruption_cost: float = 0.25
    behavior_interruption_cost: float = 0.35
    due_soon_hours: int = 6
    due_day_hours: int = 24
    due_three_days_hours: int = 72
    due_week_hours: int = 168
    restricted_domains: tuple[str, ...] = ("finance", "medical", "health", "legal")

    def validate(self) -> None:
        if self.max_candidates < 1 or self.max_candidates > 20:
            raise ValueError("proactive max_candidates must be between 1 and 20")
        if self.behavior_min_observations < 2:
            raise ValueError("proactive behavior_min_observations must be at least 2")
        for name, value in (
            ("min_candidate_utility", self.min_candidate_utility),
            ("behavior_min_confidence", self.behavior_min_confidence),
            ("open_loop_weight", self.open_loop_weight),
            ("prospective_weight", self.prospective_weight),
            ("goal_weight", self.goal_weight),
            ("behavior_weight", self.behavior_weight),
            ("behavior_observation_boost", self.behavior_observation_boost),
            ("behavior_max_boost", self.behavior_max_boost),
            ("at_risk_boost", self.at_risk_boost),
            ("blocked_boost", self.blocked_boost),
            ("overdue_boost", self.overdue_boost),
            ("due_six_hours_boost", self.due_six_hours_boost),
            ("due_one_day_boost", self.due_one_day_boost),
            ("due_three_days_boost", self.due_three_days_boost),
            ("due_seven_days_boost", self.due_seven_days_boost),
            ("default_interruption_cost", self.default_interruption_cost),
            ("behavior_interruption_cost", self.behavior_interruption_cost),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"proactive {name} must be between 0 and 1")
        windows = (
            self.due_soon_hours,
            self.due_day_hours,
            self.due_three_days_hours,
            self.due_week_hours,
        )
        if any(value < 1 for value in windows):
            raise ValueError("proactive time windows must be positive")
        if list(windows) != sorted(windows):
            raise ValueError("proactive time windows must be monotonic")


_settings: Optional[ProactiveContinuitySettings] = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(
        dict.fromkeys(
            value.strip().casefold()
            for value in raw.split(",")
            if value.strip()
        )
    )
    return values


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def get_proactive_continuity_settings() -> ProactiveContinuitySettings:
    global _settings
    if _settings is not None:
        return _settings

    settings = ProactiveContinuitySettings(
        enabled=_env_bool("KARI_PROACTIVE_CONTINUITY_ENABLED", True),
        max_candidates=_env_int("KARI_PROACTIVE_CONTINUITY_MAX_CANDIDATES", 5),
        min_candidate_utility=_env_float(
            "KARI_PROACTIVE_CONTINUITY_MIN_UTILITY",
            0.5,
        ),
        behavior_min_observations=_env_int(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_MIN_OBSERVATIONS",
            3,
        ),
        behavior_min_confidence=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_MIN_CONFIDENCE",
            0.6,
        ),
        open_loop_weight=_env_float(
            "KARI_PROACTIVE_CONTINUITY_OPEN_LOOP_WEIGHT",
            0.68,
        ),
        prospective_weight=_env_float(
            "KARI_PROACTIVE_CONTINUITY_PROSPECTIVE_WEIGHT",
            0.72,
        ),
        goal_weight=_env_float(
            "KARI_PROACTIVE_CONTINUITY_GOAL_WEIGHT",
            0.58,
        ),
        behavior_weight=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_WEIGHT",
            0.48,
        ),
        behavior_observation_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_OBSERVATION_BOOST",
            0.03,
        ),
        behavior_max_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_MAX_BOOST",
            0.18,
        ),
        at_risk_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_AT_RISK_BOOST",
            0.18,
        ),
        blocked_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BLOCKED_BOOST",
            0.10,
        ),
        overdue_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_OVERDUE_BOOST",
            0.12,
        ),
        due_six_hours_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_DUE_SIX_HOURS_BOOST",
            0.22,
        ),
        due_one_day_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_DUE_ONE_DAY_BOOST",
            0.16,
        ),
        due_three_days_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_DUE_THREE_DAYS_BOOST",
            0.10,
        ),
        due_seven_days_boost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_DUE_SEVEN_DAYS_BOOST",
            0.05,
        ),
        default_interruption_cost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_DEFAULT_INTERRUPTION_COST",
            0.25,
        ),
        behavior_interruption_cost=_env_float(
            "KARI_PROACTIVE_CONTINUITY_BEHAVIOR_INTERRUPTION_COST",
            0.35,
        ),
        due_soon_hours=_env_int(
            "KARI_PROACTIVE_CONTINUITY_DUE_SOON_HOURS",
            6,
        ),
        due_day_hours=_env_int(
            "KARI_PROACTIVE_CONTINUITY_DUE_DAY_HOURS",
            24,
        ),
        due_three_days_hours=_env_int(
            "KARI_PROACTIVE_CONTINUITY_DUE_THREE_DAYS_HOURS",
            72,
        ),
        due_week_hours=_env_int(
            "KARI_PROACTIVE_CONTINUITY_DUE_WEEK_HOURS",
            168,
        ),
        restricted_domains=_env_csv(
            "KARI_PROACTIVE_CONTINUITY_RESTRICTED_DOMAINS",
            ("finance", "medical", "health", "legal"),
        ),
    )
    try:
        settings.validate()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    _settings = settings
    return settings


def reset_proactive_continuity_settings() -> None:
    global _settings
    _settings = None


__all__ = [
    "ProactiveContinuitySettings",
    "get_proactive_continuity_settings",
    "reset_proactive_continuity_settings",
]
