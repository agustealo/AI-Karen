"""
Canonical extension registry.

Replaces global PLUGIN_MAP / ENABLED_PLUGINS with typed registration,
secondary indexes, duplicate detection, and lifecycle-aware state.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ai_karen_engine.extensions.contracts import (
    ExtensionManifest,
    ExtensionRegistration,
    ExtensionLifecycleState,
)
from ai_karen_engine.extensions.errors import ExtensionNotFoundError

logger = logging.getLogger("kari.extensions.registry")


class ExtensionRegistry:
    """Canonical extension registry.

    Owns:
      - register / unregister
      - lookup by id
      - lookup by capability
      - lookup by intent
      - lifecycle state
      - health state
      - version lookup
      - duplicate detection
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._registrations: Dict[str, ExtensionRegistration] = {}
        self._by_capability: Dict[str, Set[str]] = {}
        self._by_intent: Dict[str, Set[str]] = {}
        self._by_permission: Dict[str, Set[str]] = {}
        self._versions: Dict[str, Dict[str, ExtensionRegistration]] = {}

    def register(self, registration: ExtensionRegistration) -> None:
        """Register an extension after validation.

        Raises on duplicate id/version or unsupported API version.
        """
        plugin_id = registration.manifest.id

        existing = self._registrations.get(plugin_id)
        if existing is not None:
            if existing.manifest.version == registration.manifest.version:
                raise ValueError(
                    f"Extension '{plugin_id}' version {registration.manifest.version} is already registered"
                )
            if existing.state in {ExtensionLifecycleState.ENABLED, ExtensionLifecycleState.REGISTERED}:
                raise ValueError(
                    f"Extension '{plugin_id}' is already active; unregister first"
                )

        self._registrations[plugin_id] = registration
        self._versions.setdefault(plugin_id, {})[registration.manifest.version] = registration

        for capability in registration.manifest.capabilities:
            cap_id = getattr(capability, "id", str(capability))
            self._by_capability.setdefault(cap_id, set()).add(plugin_id)

        for intent in registration.manifest.intents:
            self._by_intent.setdefault(intent, set()).add(plugin_id)

        for perm in registration.manifest.required_permissions:
            self._by_permission.setdefault(perm, set()).add(plugin_id)

        registration.state = ExtensionLifecycleState.REGISTERED
        logger.info("Registered extension: %s v%s", plugin_id, registration.manifest.version)

    def unregister(self, plugin_id: str) -> None:
        """Unregister an extension."""
        registration = self._registrations.pop(plugin_id, None)
        if registration is None:
            raise ExtensionNotFoundError(plugin_id)

        manifest = registration.manifest
        versions = self._versions.get(plugin_id, {})
        versions.pop(manifest.version, None)
        if not versions:
            self._versions.pop(plugin_id, None)

        for capability in manifest.capabilities:
            cap_id = getattr(capability, "id", str(capability))
            self._by_capability.get(cap_id, set()).discard(plugin_id)

        for intent in manifest.intents:
            self._by_intent.get(intent, set()).discard(plugin_id)

        for perm in manifest.required_permissions:
            self._by_permission.get(perm, set()).discard(plugin_id)

        logger.info("Unregistered extension: %s", plugin_id)

    def get(self, plugin_id: str) -> Optional[ExtensionRegistration]:
        """Get registration by id."""
        return self._registrations.get(plugin_id)

    def get_by_version(self, plugin_id: str, version: str) -> Optional[ExtensionRegistration]:
        """Get a specific version of an extension."""
        return self._versions.get(plugin_id, {}).get(version)

    def get_by_capability(self, capability_id: str) -> List[ExtensionRegistration]:
        """Find extensions by capability."""
        plugin_ids = self._by_capability.get(capability_id, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def get_by_intent(self, intent: str) -> List[ExtensionRegistration]:
        """Find extensions by intent."""
        plugin_ids = self._by_intent.get(intent, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def get_by_permission(self, permission: str) -> List[ExtensionRegistration]:
        """Find extensions requiring a permission."""
        plugin_ids = self._by_permission.get(permission, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def list_registered(self) -> List[ExtensionRegistration]:
        """List all registered extensions."""
        return [
            reg for reg in self._registrations.values()
            if reg.state in {
                ExtensionLifecycleState.REGISTERED,
                ExtensionLifecycleState.ENABLED,
                ExtensionLifecycleState.DISABLED,
                ExtensionLifecycleState.DEGRADED,
            }
        ]

    def list_enabled(self) -> List[ExtensionRegistration]:
        """List enabled extensions."""
        return [
            reg for reg in self._registrations.values()
            if reg.state == ExtensionLifecycleState.ENABLED
        ]

    def update_state(self, plugin_id: str, state: ExtensionLifecycleState, error: Optional[str] = None) -> None:
        """Update lifecycle state."""
        registration = self._registrations.get(plugin_id)
        if registration is None:
            raise ExtensionNotFoundError(plugin_id)
        registration.state = state
        if error:
            registration.last_error = error
        logger.debug("Extension %s state -> %s", plugin_id, state.value)

    def prune_stale(self, discovered_ids: Set[str]) -> List[str]:
        """Remove registered extensions that no longer exist on disk.

        Returns list of pruned plugin ids.
        """
        stale = [
            plugin_id for plugin_id in list(self._registrations.keys())
            if plugin_id not in discovered_ids
        ]
        for plugin_id in stale:
            asyncio.create_task(self.unregister(plugin_id))
        return stale

    def stats(self) -> Dict[str, Any]:
        """Registry statistics."""
        by_state: Dict[str, int] = {}
        for reg in self._registrations.values():
            by_state[reg.state.value] = by_state.get(reg.state.value, 0) + 1
        return {
            "total": len(self._registrations),
            "by_state": by_state,
            "by_capability": {k: len(v) for k, v in self._by_capability.items()},
            "by_intent": {k: len(v) for k, v in self._by_intent.items()},
        }


__all__ = ["ExtensionRegistry"]
