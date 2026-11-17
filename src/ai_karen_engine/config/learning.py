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
    # Governed benchmark adapter writes independently verified predictor
    # labels to existing tenant-RLS OutcomeStore only when explicitly enabled
    # and its forward-only schema migration is applied.
    verified_evaluation_outcomes_enabled: bool = False
    # KCM is an independently governed, non-promoting admission capability.
    kcm_training_admission_enabled: bool = False
    kcm_training_min_quality: float = 0.82
    kcm_training_min_correctness: float = 0.90
    kcm_training_min_provenance: float = 0.80
    # Default task-benchmark evidence lifetime for read-only KCM inspection.
    # Expired evidence is unavailable; it cannot certify current capability.
    kcm_benchmark_max_evidence_age_seconds: int = 2_592_000
    # An optional, engine-specific worker observation. Never authorizes
    # training, KCM datasets, benchmark independence, or model execution.
    kcm_sklearn_fit_observation_enabled: bool = False
    model_routing_min_samples: int = 12
    model_routing_history_limit: int = 500
    model_routing_history_days: int = 90
    model_routing_read_timeout_seconds: float = 0.75
    model_routing_max_failure_rate: float = 0.4
    model_routing_min_reliability_gain: float = 0.2

    def __post_init__(self) -> None:
        for setting in (
            "kcm_training_min_quality",
            "kcm_training_min_correctness",
            "kcm_training_min_provenance",
        ):
            value = getattr(self, setting)
            if not isinstance(value, (int, float)) or not 0.0 < value <= 1.0:
                raise ValueError(f"{setting} must be in (0, 1]")
        if (
            type(self.kcm_benchmark_max_evidence_age_seconds) is not int
            or not 1 <= self.kcm_benchmark_max_evidence_age_seconds <= 31_536_000
        ):
            raise ValueError(
                "KCM benchmark evidence age must be 1-31536000 seconds"
            )
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


    def get_kcm_sklearn_fit_observation_key(self) -> tuple[str, bytes] | None:
        """Read a host-managed key without retaining it in settings or logs.

        A missing/invalid enabled key fails closed. Disabled means no receipt,
        not an implied identity, consent, or training authorization.
        """
        if not self.kcm_sklearn_fit_observation_enabled:
            return None
        key_id = os.environ.get("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", "")
        secret = os.environ.get("KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", "")
        if (
            not 1 <= len(key_id) <= 64
            or not all(ch.isascii() and (ch.isalnum() or ch in "._-")
                       for ch in key_id)
            or len(secret) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in secret)
        ):
            raise ValueError("Configured KCM sklearn observation key is unavailable")
        return key_id, bytes.fromhex(secret)

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
        raw_evaluation_enabled = env(
            "LEARNING_VERIFIED_EVALUATION_OUTCOMES_ENABLED"
        )
        if raw_evaluation_enabled is not None:
            normalized = raw_evaluation_enabled.strip().lower()
            if normalized not in {
                "1", "0", "true", "false", "yes", "no", "on", "off",
            }:
                raise ValueError(
                    "LEARNING_VERIFIED_EVALUATION_OUTCOMES_ENABLED must be boolean"
                )
            self.verified_evaluation_outcomes_enabled = normalized in {
                "1", "true", "yes", "on",
            }
        kcm_admission_enabled = env("KCM_TRAINING_ADMISSION_ENABLED")
        if kcm_admission_enabled is not None:
            normalized = kcm_admission_enabled.strip().lower()
            if normalized not in {
                "1", "0", "true", "false", "yes", "no", "on", "off",
            }:
                raise ValueError("KCM_TRAINING_ADMISSION_ENABLED must be boolean")
            self.kcm_training_admission_enabled = normalized in {
                "1", "true", "yes", "on",
            }

        fit_observation = env("KCM_SKLEARN_FIT_OBSERVATION_ENABLED")
        if fit_observation is not None:
            normalized = fit_observation.strip().lower()
            if normalized not in {
                "1", "0", "true", "false", "yes", "no", "on", "off",
            }:
                raise ValueError("KCM_SKLEARN_FIT_OBSERVATION_ENABLED must be boolean")
            self.kcm_sklearn_fit_observation_enabled = normalized in {
                "1", "true", "yes", "on",
            }

        numeric_settings = (
            ("KCM_TRAINING_MIN_QUALITY", "kcm_training_min_quality", float),
            ("KCM_TRAINING_MIN_CORRECTNESS", "kcm_training_min_correctness", float),
            ("KCM_TRAINING_MIN_PROVENANCE", "kcm_training_min_provenance", float),
            ("KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS",
             "kcm_benchmark_max_evidence_age_seconds", int),
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
