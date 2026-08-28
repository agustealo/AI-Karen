"""Configuration for Agent Medusa execution coordination and durable history."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


class AgentMedusaConfigError(ValueError):
    """Raised when Medusa runtime coordination configuration is invalid."""


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AgentMedusaConfigError(f"{name} must be a boolean value")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise AgentMedusaConfigError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class AgentMedusaRuntimeSettings:
    """Validated Medusa coordination and durable-history settings."""

    distributed_run_control_enabled: bool = True
    durable_run_history_enabled: bool = True
    run_lease_ttl_seconds: int = 30
    run_heartbeat_interval_seconds: int = 10
    run_terminal_retention_seconds: int = 3600
    run_reconciliation_batch_size: int = 100
    run_history_list_limit: int = 500
    run_key_prefix: str = "kari:medusa:runs"
    worker_id: str = field(default_factory=_default_worker_id)

    def __post_init__(self) -> None:
        if self.run_lease_ttl_seconds < 3:
            raise AgentMedusaConfigError("run_lease_ttl_seconds must be at least 3")
        if self.run_heartbeat_interval_seconds < 1:
            raise AgentMedusaConfigError(
                "run_heartbeat_interval_seconds must be at least 1"
            )
        if self.run_heartbeat_interval_seconds >= self.run_lease_ttl_seconds:
            raise AgentMedusaConfigError(
                "run_heartbeat_interval_seconds must be less than run_lease_ttl_seconds"
            )
        if self.run_terminal_retention_seconds < self.run_lease_ttl_seconds:
            raise AgentMedusaConfigError(
                "run_terminal_retention_seconds must be at least run_lease_ttl_seconds"
            )
        if not 1 <= self.run_reconciliation_batch_size <= 1000:
            raise AgentMedusaConfigError(
                "run_reconciliation_batch_size must be between 1 and 1000"
            )
        if not 1 <= self.run_history_list_limit <= 1000:
            raise AgentMedusaConfigError(
                "run_history_list_limit must be between 1 and 1000"
            )
        if not self.run_key_prefix.strip():
            raise AgentMedusaConfigError("run_key_prefix must not be empty")
        if not self.worker_id.strip():
            raise AgentMedusaConfigError("worker_id must not be empty")


_SETTINGS: AgentMedusaRuntimeSettings | None = None


def get_agent_medusa_runtime_settings() -> AgentMedusaRuntimeSettings:
    """Return the process-wide validated Medusa runtime settings."""

    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=_env_bool(
                "KAREN_MEDUSA_DISTRIBUTED_RUN_CONTROL_ENABLED", True
            ),
            durable_run_history_enabled=_env_bool(
                "KAREN_MEDUSA_DURABLE_RUN_HISTORY_ENABLED", True
            ),
            run_lease_ttl_seconds=_env_int("KAREN_MEDUSA_RUN_LEASE_TTL_SECONDS", 30),
            run_heartbeat_interval_seconds=_env_int(
                "KAREN_MEDUSA_RUN_HEARTBEAT_INTERVAL_SECONDS", 10
            ),
            run_terminal_retention_seconds=_env_int(
                "KAREN_MEDUSA_RUN_TERMINAL_RETENTION_SECONDS", 3600
            ),
            run_reconciliation_batch_size=_env_int(
                "KAREN_MEDUSA_RUN_RECONCILIATION_BATCH_SIZE", 100
            ),
            run_history_list_limit=_env_int(
                "KAREN_MEDUSA_RUN_HISTORY_LIST_LIMIT", 500
            ),
            run_key_prefix=os.getenv("KAREN_MEDUSA_RUN_KEY_PREFIX", "kari:medusa:runs"),
            worker_id=os.getenv("KAREN_WORKER_ID", _default_worker_id()),
        )
    return _SETTINGS


__all__ = [
    "AgentMedusaConfigError",
    "AgentMedusaRuntimeSettings",
    "get_agent_medusa_runtime_settings",
]
