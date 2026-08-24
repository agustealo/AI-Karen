"""
Canonical extension lifecycle manager.

Manages explicit lifecycle state transitions:
  DISCOVERED -> VALIDATED -> REGISTERED -> ENABLED -> DISABLED -> DEGRADED -> FAILED -> UNAVAILABLE

No plugin is "enabled" merely because a manifest exists.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.contracts import (
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    ExtensionHealth,
    ExtensionHealthRecord,
)
from ai_karen_engine.extensions.errors import (
    ExtensionError,
    ExtensionNotFoundError,
)

logger = logging.getLogger("kari.extensions.lifecycle")


class ExtensionLifecycleManager:
    """Explicit lifecycle state machine for extensions."""

    VALID_TRANSITIONS = {
        (ExtensionLifecycleState.DISCOVERED, ExtensionLifecycleState.VALIDATED),
        (ExtensionLifecycleState.VALIDATED, ExtensionLifecycleState.REGISTERED),
        (ExtensionLifecycleState.VALIDATED, ExtensionLifecycleState.FAILED),
        (ExtensionLifecycleState.REGISTERED, ExtensionLifecycleState.ENABLED),
        (ExtensionLifecycleState.REGISTERED, ExtensionLifecycleState.DISABLED),
        (ExtensionLifecycleState.ENABLED, ExtensionLifecycleState.DISABLED),
        (ExtensionLifecycleState.ENABLED, ExtensionLifecycleState.DEGRADED),
        (ExtensionLifecycleState.ENABLED, ExtensionLifecycleState.FAILED),
        (ExtensionLifecycleState.DISABLED, ExtensionLifecycleState.ENABLED),
        (ExtensionLifecycleState.DISABLED, ExtensionLifecycleState.FAILED),
        (ExtensionLifecycleState.DEGRADED, ExtensionLifecycleState.ENABLED),
        (ExtensionLifecycleState.DEGRADED, ExtensionLifecycleState.FAILED),
        (ExtensionLifecycleState.DEGRADED, ExtensionLifecycleState.UNAVAILABLE),
        (ExtensionLifecycleState.FAILED, ExtensionLifecycleState.UNAVAILABLE),
        (ExtensionLifecycleState.FAILED, ExtensionLifecycleState.DISCOVERED),
        (ExtensionLifecycleState.UNAVAILABLE, ExtensionLifecycleState.DISCOVERED),
    }

    def __init__(self, registry: Any = None):
        self._registry = registry
        self._health: Dict[str, ExtensionHealthRecord] = {}
        self._listeners: List[Any] = []

    def transition(self, plugin_id: str, target_state: ExtensionLifecycleState, *, reason: Optional[str] = None) -> None:
        """Attempt a lifecycle state transition."""
        registration = self._get_registration(plugin_id)
        current = registration.state

        if (current, target_state) not in self.VALID_TRANSITIONS:
            raise ExtensionError(
                f"Invalid lifecycle transition for '{plugin_id}': {current.value} -> {target_state.value}",
                error_code="invalid_transition",
                plugin_id=plugin_id,
            )

        registration.state = target_state
        if reason:
            registration.last_error = reason

        self._update_health(plugin_id, target_state, reason)
        self._notify(plugin_id, current, target_state, reason)
        logger.debug("Lifecycle transition: %s %s -> %s", plugin_id, current.value, target_state.value, extra={"reason": reason})

    def get_health(self, plugin_id: str) -> Optional[ExtensionHealthRecord]:
        """Get health record for an extension."""
        return self._health.get(plugin_id)

    def record_health(self, plugin_id: str, health: ExtensionHealth, *, reason_code: Optional[str] = None, dependency_status: Optional[Dict[str, str]] = None) -> None:
        """Record a health check result."""
        self._update_health(plugin_id, ExtensionLifecycleState.ENABLED, reason_code)
        record = self._health.get(plugin_id)
        if record is not None:
            record.health = health
            if reason_code:
                record.reason_code = reason_code
            if dependency_status:
                record.dependency_status = dependency_status
            record.last_check = datetime.utcnow()

    def _get_registration(self, plugin_id: str) -> ExtensionRegistration:
        if self._registry is not None:
            registration = self._registry.get(plugin_id)
            if registration is not None:
                return registration
        raise ExtensionNotFoundError(plugin_id)

    def _update_health(self, plugin_id: str, state: ExtensionLifecycleState, reason: Optional[str]) -> None:
        health_map = {
            ExtensionLifecycleState.ENABLED: ExtensionHealth.HEALTHY,
            ExtensionLifecycleState.DISABLED: ExtensionHealth.UNKNOWN,
            ExtensionLifecycleState.DEGRADED: ExtensionHealth.DEGRADED,
            ExtensionLifecycleState.FAILED: ExtensionHealth.UNAVAILABLE,
            ExtensionLifecycleState.UNAVAILABLE: ExtensionHealth.UNAVAILABLE,
            ExtensionLifecycleState.VALIDATED: ExtensionHealth.UNKNOWN,
            ExtensionLifecycleState.REGISTERED: ExtensionHealth.UNKNOWN,
            ExtensionLifecycleState.DISCOVERED: ExtensionHealth.UNKNOWN,
        }
        record = self._health.get(plugin_id)
        if record is None:
            record = ExtensionHealthRecord(
                plugin_id=plugin_id,
                state=state,
                health=health_map.get(state, ExtensionHealth.UNKNOWN),
            )
            self._health[plugin_id] = record
        else:
            record.state = state
            record.health = health_map.get(state, ExtensionHealth.UNKNOWN)
            if reason:
                record.reason_code = reason

    def _notify(self, plugin_id: str, previous: ExtensionLifecycleState, next_state: ExtensionLifecycleState, reason: Optional[str]) -> None:
        for listener in self._listeners:
            try:
                listener(plugin_id, previous, next_state, reason)
            except Exception as exc:
                logger.warning("Lifecycle listener failed: %s", exc)

    def add_listener(self, listener: Any) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Any) -> None:
        self._listeners = [ln for ln in self._listeners if ln is not listener]


__all__ = ["ExtensionLifecycleManager"]
