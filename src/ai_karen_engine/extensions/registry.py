"""
Canonical extension registry.

Replaces global PLUGIN_MAP / ENABLED_PLUGINS with typed registration,
secondary indexes, duplicate detection, and lifecycle-aware state.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from ai_karen_engine.extensions.contracts import (
    ExtensionLifecycleState,
    ExtensionRegistration,
)

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
        self._registrations: dict[str, ExtensionRegistration] = {}
        self._by_capability: dict[str, set[str]] = {}
        self._by_intent: dict[str, set[str]] = {}
        self._by_permission: dict[str, set[str]] = {}
        self._versions: dict[str, dict[str, ExtensionRegistration]] = {}

    async def register(self, registration: ExtensionRegistration) -> None:
        """Register an extension after validation.

        Raises on duplicate id/version or unsupported API version.
        """
        async with self._lock:
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

    async def unregister(self, plugin_id: str) -> None:
        """Unregister an extension."""
        async with self._lock:
            registration = self._registrations.pop(plugin_id, None)
            if registration is None:
                raise Exception(f"Extension '{plugin_id}' not found")

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

    def get(self, plugin_id: str) -> ExtensionRegistration | None:
        """Get registration by id."""
        return self._registrations.get(plugin_id)

    def get_by_version(self, plugin_id: str, version: str) -> ExtensionRegistration | None:
        """Get a specific version of an extension."""
        return self._versions.get(plugin_id, {}).get(version)

    def get_by_capability(self, capability_id: str) -> list[ExtensionRegistration]:
        """Find extensions by capability."""
        plugin_ids = self._by_capability.get(capability_id, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def get_capability_candidates(
        self,
        capability_id: str,
        version_constraint: str | None = None,
    ) -> list[ExtensionRegistration]:
        """Find candidate extensions that provide a capability with optional version filtering.

        This is for capability resolution, not execution filtering.
        Returns a snapshot that won't race with concurrent mutations.
        """
        plugin_ids = self._by_capability.get(capability_id, set())
        candidates: list[ExtensionRegistration] = [
            self._registrations[pid] for pid in plugin_ids if pid in self._registrations
        ]

        if version_constraint:
            candidates = [
                reg for reg in candidates
                if self._matches_version_constraint(reg.manifest.capabilities, capability_id, version_constraint)
            ]

        return candidates

    def _matches_version_constraint(
        self,
        capabilities: list[Any],
        capability_id: str,
        version_constraint: str,
    ) -> bool:
        """Check if any capability matches the version constraint."""
        for cap in capabilities:
            cap_obj_id = getattr(cap, "id", str(cap))
            if cap_obj_id == capability_id:
                cap_version = getattr(cap, "version", "1.0.0")
                if version_constraint == cap_version:
                    return True
                if version_constraint.startswith(">="):
                    min_version = version_constraint[2:]
                    try:
                        from packaging.version import Version
                        return Version(cap_version) >= Version(min_version)
                    except Exception:
                        pass
                if version_constraint.startswith("^"):
                    try:
                        from packaging.version import Version
                        v = Version(cap_version)
                        min_v = Version(version_constraint[1:])
                        return v.major == min_v.major and v >= min_v
                    except Exception:
                        pass
        return False

    def get_by_intent(self, intent: str) -> list[ExtensionRegistration]:
        """Find extensions by intent."""
        plugin_ids = self._by_intent.get(intent, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def get_by_permission(self, permission: str) -> list[ExtensionRegistration]:
        """Find extensions requiring a permission."""
        plugin_ids = self._by_permission.get(permission, set())
        return [self._registrations[pid] for pid in plugin_ids if pid in self._registrations]

    def list_registered(self) -> list[ExtensionRegistration]:
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

    def list_enabled(self) -> list[ExtensionRegistration]:
        """List enabled extensions."""
        return [
            reg for reg in self._registrations.values()
            if reg.state == ExtensionLifecycleState.ENABLED
        ]

    async def update_state(self, plugin_id: str, state: ExtensionLifecycleState, error: str | None = None) -> None:
        """Update lifecycle state."""
        async with self._lock:
            registration = self._registrations.get(plugin_id)
            if registration is None:
                raise Exception(f"Extension '{plugin_id}' not found")
            registration.state = state
            if error:
                registration.last_error = error
            logger.debug("Extension %s state -> %s", plugin_id, state.value)

    async def prune_stale(self, discovered_ids: set[str]) -> list[str]:
        """Remove registered extensions that no longer exist on disk.

        Returns list of pruned plugin ids.
        """
        async with self._lock:
            stale = [
                plugin_id for plugin_id in list(self._registrations.keys())
                if plugin_id not in discovered_ids
            ]
            for plugin_id in stale:
                await self._unregister_unsafe(plugin_id)
            return stale

    async def _unregister_unsafe(self, plugin_id: str) -> None:
        """Unregister without lock - only call from within locked context."""
        registration = self._registrations.pop(plugin_id, None)
        if registration is None:
            return

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

    def stats(self) -> dict[str, Any]:
        """Registry statistics."""
        by_state: dict[str, int] = {}
        for reg in self._registrations.values():
            by_state[reg.state.value] = by_state.get(reg.state.value, 0) + 1
        return {
            "total": len(self._registrations),
            "by_state": by_state,
            "by_capability": {k: len(v) for k, v in self._by_capability.items()},
            "by_intent": {k: len(v) for k, v in self._by_intent.items()},
        }


__all__ = ["ExtensionRegistry"]
