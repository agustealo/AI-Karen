from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class MemoryRuntimeSettings:
    """Canonical configuration for bounded memory runtime state.

    Redis is the current physical STM/session backing, but these settings describe
    memory semantics rather than a vendor-specific cache contract.
    """

    stm_session_ttl_seconds: int = 24 * 60 * 60
    stm_max_slot_bytes: int = 64 * 1024

    def apply_env_overrides(self) -> None:
        raw_ttl = os.getenv("MEMORY_STM_SESSION_TTL_SECONDS")
        if raw_ttl and raw_ttl.strip():
            try:
                self.stm_session_ttl_seconds = max(60, int(raw_ttl.strip()))
            except ValueError:
                pass

        raw_max = os.getenv("MEMORY_STM_MAX_SLOT_BYTES")
        if raw_max and raw_max.strip():
            try:
                self.stm_max_slot_bytes = max(1024, int(raw_max.strip()))
            except ValueError:
                pass


_settings: MemoryRuntimeSettings | None = None


def get_memory_runtime_settings() -> MemoryRuntimeSettings:
    """Return the canonical memory runtime settings singleton."""
    global _settings
    if _settings is None:
        _settings = MemoryRuntimeSettings()
        _settings.apply_env_overrides()
    return _settings


def reload_memory_runtime_settings() -> MemoryRuntimeSettings:
    """Reload memory runtime settings from environment overrides."""
    global _settings
    _settings = MemoryRuntimeSettings()
    _settings.apply_env_overrides()
    return _settings


__all__ = [
    "MemoryRuntimeSettings",
    "get_memory_runtime_settings",
    "reload_memory_runtime_settings",
]
