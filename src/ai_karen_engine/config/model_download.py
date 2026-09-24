"""Configuration for the durable model-download worker."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


@dataclass(frozen=True)
class ModelDownloadWorkerSettings:
    """Validated runtime settings for the durable worker.

    The control-plane policy remains the user-facing source for the global
    concurrency ceiling. ``global_concurrency_default`` is the safe fallback
    when no policy override is present.
    """

    enabled: bool = True
    global_concurrency_default: int = 2
    lease_seconds: int = 120
    heartbeat_seconds: int = 30
    poll_interval_seconds: float = 1.0
    max_attempts: int = 3
    retry_base_seconds: int = 5
    shutdown_grace_seconds: int = 30

    def validate(self) -> "ModelDownloadWorkerSettings":
        if self.global_concurrency_default < 1:
            raise ValueError("model download global concurrency must be at least 1")
        if self.lease_seconds < 2:
            raise ValueError("model download lease_seconds must be at least 2")
        if self.heartbeat_seconds < 1 or self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("model download heartbeat must be positive and shorter than the lease")
        if self.poll_interval_seconds <= 0:
            raise ValueError("model download poll interval must be positive")
        if self.max_attempts < 1:
            raise ValueError("model download max_attempts must be at least 1")
        if self.retry_base_seconds < 0:
            raise ValueError("model download retry_base_seconds cannot be negative")
        if self.shutdown_grace_seconds < 0:
            raise ValueError("model download shutdown_grace_seconds cannot be negative")
        return self


def load_model_download_worker_settings() -> ModelDownloadWorkerSettings:
    return ModelDownloadWorkerSettings(
        enabled=_env_bool("KAREN_MODEL_DOWNLOAD_WORKER_ENABLED", True),
        global_concurrency_default=_env_int("KAREN_MODEL_DOWNLOAD_GLOBAL_CONCURRENCY", 2),
        lease_seconds=_env_int("KAREN_MODEL_DOWNLOAD_LEASE_SECONDS", 120),
        heartbeat_seconds=_env_int("KAREN_MODEL_DOWNLOAD_HEARTBEAT_SECONDS", 30),
        poll_interval_seconds=_env_float("KAREN_MODEL_DOWNLOAD_POLL_INTERVAL_SECONDS", 1.0),
        max_attempts=_env_int("KAREN_MODEL_DOWNLOAD_MAX_ATTEMPTS", 3),
        retry_base_seconds=_env_int("KAREN_MODEL_DOWNLOAD_RETRY_BASE_SECONDS", 5),
        shutdown_grace_seconds=_env_int("KAREN_MODEL_DOWNLOAD_SHUTDOWN_GRACE_SECONDS", 30),
    ).validate()


__all__ = ["ModelDownloadWorkerSettings", "load_model_download_worker_settings"]
