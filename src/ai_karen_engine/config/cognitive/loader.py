from __future__ import annotations

import copy
import os
from typing import Any

from ai_karen_engine.config.cognitive.defaults import DEFAULT_COGNITIVE_POLICY
from ai_karen_engine.config.cognitive.models import (
    CognitivePolicyConfig,
)
from ai_karen_engine.config.cognitive.validation import (
    CognitiveConfigValidationError,
    validate_cognitive_policy,
)

_COGNITIVE_PREFIX = "KAREN_COG"

# Map env keys to nested config paths
_ENV_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    "KAREN_COG_META_WEAK_MEMORY_THRESHOLD": ("meta", "weak_memory_threshold"),
    "KAREN_COG_META_LOW_REASONING_THRESHOLD": ("meta", "low_reasoning_threshold"),
    "KAREN_COG_META_VERIFICATION_THRESHOLD": ("meta", "verification_threshold"),
    "KAREN_COG_META_DEEP_REASONING_THRESHOLD": ("meta", "deep_reasoning_threshold"),
    "KAREN_COG_META_LOOP_REPEAT_THRESHOLD": ("meta", "loop_repeat_threshold"),
    "KAREN_COG_META_MAX_RECONSIDERATION_STEPS": ("meta", "max_reconsideration_steps"),
    "KAREN_COG_META_CONFIDENCE_THRESHOLD_LOW": ("meta", "confidence_threshold_low"),
    "KAREN_COG_META_CONFIDENCE_THRESHOLD_HIGH": ("meta", "confidence_threshold_high"),
    "KAREN_COG_META_ENABLE_ADAPTIVE_THRESHOLDS": ("meta", "enable_adaptive_thresholds"),
    "KAREN_COG_CONTEXT_MAX_ITEMS": ("context", "max_items"),
    "KAREN_COG_CONTEXT_MAX_TOKENS": ("context", "max_tokens"),
    "KAREN_COG_CONTEXT_RESERVED_FOR_CRITICAL": ("context", "reserved_for_critical"),
    "KAREN_COG_BEHAVIOR_RISK_WEIGHT": ("behavior", "risk_penalty_weight"),
    "KAREN_COG_BEHAVIOR_INTERRUPTION_PENALTY_WEIGHT": ("behavior", "interruption_penalty_weight"),
    "KAREN_COG_BEHAVIOR_VERIFICATION_VALUE_WEIGHT": ("behavior", "verification_value_weight"),
    "KAREN_COG_SALIENCE_DECAY_RATE": ("salience", "default_decay_rate"),
    "KAREN_COG_LEARNING_MIN_SAMPLES": ("learning", "min_samples"),
    "KAREN_COG_LEARNING_MIN_CONFIDENCE": ("learning", "min_confidence"),
    "KAREN_COG_MEMORY_DEFAULT_DECAY_LAMBDA": ("memory", "default_decay_lambda"),
    "KAREN_COG_BELIEF_STALENESS_THRESHOLD_HOURS": ("belief", "staleness_threshold_hours"),
}

_cached_config: CognitivePolicyConfig | None = None


def _get_section(config: CognitivePolicyConfig, section_name: str) -> Any:
    return getattr(config, section_name)


def _set_section_field(config: CognitivePolicyConfig, section_name: str, field_name: str, value: Any) -> None:
    section = _get_section(config, section_name)
    object.__setattr__(section, field_name, value)


def _coerce_value(raw: str, current: Any, key: str) -> Any:
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        try:
            return int(raw.strip())
        except ValueError:
            raise CognitiveConfigValidationError(
                f"Environment variable {key} expects int, got {raw!r}"
            )
    if isinstance(current, float):
        try:
            return float(raw.strip())
        except ValueError:
            raise CognitiveConfigValidationError(
                f"Environment variable {key} expects float, got {raw!r}"
            )
    return raw.strip()


def _coerce_env_value(raw: str, current: Any, key: str) -> Any:
    return _coerce_value(raw, current, key)


def _apply_env_overrides(config: CognitivePolicyConfig) -> CognitivePolicyConfig:
    config = copy.deepcopy(config)
    for env_key, (section, field_name) in _ENV_OVERRIDE_MAP.items():
        raw = os.getenv(env_key)
        if raw is not None:
            section_obj = _get_section(config, section)
            current = getattr(section_obj, field_name)
            value = _coerce_value(raw, current, env_key)
            _set_section_field(config, section, field_name, value)
    return config


def load_cognitive_config(validate: bool = True) -> CognitivePolicyConfig:
    global _cached_config
    if _cached_config is None:
        _cached_config = _apply_env_overrides(DEFAULT_COGNITIVE_POLICY)
        if validate:
            validate_cognitive_policy(_cached_config)
    return _cached_config


def get_cognitive_config() -> CognitivePolicyConfig:
    return load_cognitive_config(validate=True)


def reload_cognitive_config() -> CognitivePolicyConfig:
    global _cached_config
    _cached_config = None
    return load_cognitive_config(validate=True)


def reset_cognitive_config() -> None:
    global _cached_config
    _cached_config = None
