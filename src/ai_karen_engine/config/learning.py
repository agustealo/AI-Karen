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
