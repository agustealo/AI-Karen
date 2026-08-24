"""
Canonical extension permission resolver.

Permissions are granted by policy, never inferred from plugin code.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.contracts import ExtensionManifest

logger = logging.getLogger("kari.extensions.permissions")


class ExtensionPermissionResolver:
    """Resolves plugin permissions from manifest, policy, and RBAC."""

    def resolve(
        self,
        manifest: ExtensionManifest,
        *,
        user_roles: Optional[List[str]] = None,
        policy_grants: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        granted: List[str] = []
        user_roles = set(user_roles or [])
        policy_grants = policy_grants or {}

        allowed_roles = set(manifest.required_roles)
        if allowed_roles and not (allowed_roles & user_roles):
            return granted

        granted_permissions = set(policy_grants.get("permissions", []))
        for perm in manifest.required_permissions:
            if perm in granted_permissions:
                granted.append(perm)

        return granted

    def missing(
        self,
        manifest: ExtensionManifest,
        *,
        user_roles: Optional[List[str]] = None,
        policy_grants: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        granted = set(self.resolve(manifest, user_roles=user_roles, policy_grants=policy_grants))
        return [p for p in manifest.required_permissions if p not in granted]


__all__ = ["ExtensionPermissionResolver"]
