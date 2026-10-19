from __future__ import annotations

import os
from dataclasses import dataclass

from ai_karen_engine.core.contracts.learning import LabelQuality

_DEFAULT_DATASET_DIR = "data/learning/datasets"


@dataclass
class LearningSettings:
    """Canonical configuration for Phase 2 durable learning records.

    All reads funnel through this single class; environment overrides are
    applied eagerly and defaults are safe (no tenant bypass, jsonl default).
    """

    recording_enabled: bool = True
    dataset_dir: str = _DEFAULT_DATASET_DIR
    dataset_format: str = "jsonl"  # jsonl | parquet
    min_label_quality: LabelQuality = LabelQuality.MEDIUM
    retention_days: int = 365
    # Learning is consulted by default, but NEVER overrides policy, an
    # explicit user model selection or unverified provider capabilities.
    model_routing_signals_enabled: bool = True
    # Learning is consulted normally, but operational evidence cannot
    # promote a routing policy by itself. Requires evaluated promotion.
    model_routing_adaptive_enabled: bool = False
    model_routing_min_samples: int = 12
    model_routing_history_limit: int = 500
    model_routing_history_days: int = 90
    model_routing_read_timeout_seconds: float = 0.75
    model_routing_max_failure_rate: float = 0.4
    model_routing_min_reliability_gain: float = 0.2

    def __post_init__(self) -> None:
        if not 5 <= self.model_routing_min_samples <= 1000:
            raise ValueError("Learning minimum model sample count must be 5-1000")
        if not 10 <= self.model_routing_history_limit <= 1000:
            raise ValueError("Learning outcome history limit must be 10-1000")
        if not 1 <= self.model_routing_history_days <= 365:
            raise ValueError("Learning outcome retention horizon must be 1-365 days")
        if not 0.1 <= self.model_routing_read_timeout_seconds <= 10.0:
            raise ValueError("Learning read timeout must be 0.1-10 seconds")
        for value in (
            self.model_routing_max_failure_rate, self.model_routing_min_reliability_gain
        ):
            if not 0.0 < value < 1.0:
                raise ValueError("Learning reliability thresholds must lie between 0 and 1")


    def apply_env_overrides(self) -> None:
        env = os.getenv
        raw_enabled = env("LEARNING_RECORDING_ENABLED")
        if raw_enabled is not None:
            self.recording_enabled = raw_enabled.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        raw_dir = env("LEARNING_DATASET_DIR")
        if raw_dir:
            self.dataset_dir = raw_dir
        raw_format = env("LEARNING_DATASET_FORMAT")
        if raw_format:
            self.dataset_format = raw_format.strip().lower()
        raw_quality = env("LEARNING_DATASET_MIN_LABEL_QUALITY")
        if raw_quality:
            try:
                self.min_label_quality = LabelQuality(raw_quality.strip().lower())
            except ValueError:
                pass
        raw_retention = env("LEARNING_RETENTION_DAYS")
        if raw_retention and raw_retention.strip():
            try:
                self.retention_days = int(raw_retention.strip())
            except ValueError:
                pass
        raw_model_enabled = env("LEARNING_MODEL_ROUTING_SIGNALS_ENABLED")
        if raw_model_enabled is not None:
            if raw_model_enabled.strip().lower() not in {
                "1", "0", "true", "false", "yes", "no", "on", "off",
            }:
                raise ValueError("LEARNING_MODEL_ROUTING_SIGNALS_ENABLED must be boolean")
            self.model_routing_signals_enabled = raw_model_enabled.strip().lower() in {
                "1", "true", "yes", "on",
            }
        raw_adaptive_enabled = env("LEARNING_MODEL_ROUTING_ADAPTIVE_ENABLED")
        if raw_adaptive_enabled is not None:
            normalized = raw_adaptive_enabled.strip().lower()
            if normalized not in {
                "1", "0", "true", "false", "yes", "no", "on", "off",
            }:
                raise ValueError(
                    "LEARNING_MODEL_ROUTING_ADAPTIVE_ENABLED must be boolean"
                )
            self.model_routing_adaptive_enabled = normalized in {
                "1", "true", "yes", "on",
            }
        numeric_settings = (
            ("LEARNING_MODEL_ROUTING_MIN_SAMPLES", "model_routing_min_samples", int),
            ("LEARNING_MODEL_ROUTING_HISTORY_LIMIT", "model_routing_history_limit", int),
            ("LEARNING_MODEL_ROUTING_HISTORY_DAYS", "model_routing_history_days", int),
            ("LEARNING_MODEL_ROUTING_READ_TIMEOUT_SECONDS", "model_routing_read_timeout_seconds", float),
            ("LEARNING_MODEL_ROUTING_MAX_FAILURE_RATE", "model_routing_max_failure_rate", float),
            ("LEARNING_MODEL_ROUTING_MIN_RELIABILITY_GAIN", "model_routing_min_reliability_gain", float),
        )
        for key, attr, parser in numeric_settings:
            raw = env(key)
            if raw is None:
                continue
            try:
                value = parser(raw)
            except ValueError as exc:
                raise ValueError(f"{key} must be numeric") from exc
            setattr(self, attr, value)
        self.__post_init__()


_settings: LearningSettings | None = None


def get_learning_settings() -> LearningSettings:
    """Return the current ``LearningSettings`` singleton."""
    global _settings
    if _settings is None:
        _settings = LearningSettings()
        _settings.apply_env_overrides()
    return _settings


def reload_learning_settings() -> LearningSettings:
    """Force reload of learning settings from environment."""
    global _settings
    _settings = LearningSettings()
    _settings.apply_env_overrides()
    return _settings
