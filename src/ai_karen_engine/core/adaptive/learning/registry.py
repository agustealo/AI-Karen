"""Adaptive policy registry.

Separate from ML model registry. Manages policy lifecycle with atomic promotion/rollback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    PolicyStatus,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PolicyRecord:
    policy_id: str
    policy_version: str
    status: PolicyStatus
    policy: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, PolicyRecord] = {}
        self._active_aliases: dict[str, str] = {}
        self._aliases: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []

    def register(self, record: PolicyRecord) -> None:
        key = self._key(record.policy_id, record.policy_version)
        self._policies[key] = record
        self._history.append({
            "action": "register",
            "policy_id": record.policy_id,
            "policy_version": record.policy_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get(self, policy_id: str, policy_version: str) -> PolicyRecord | None:
        return self._policies.get(self._key(policy_id, policy_version))

    def list_policies(self, policy_id: str | None = None) -> list[PolicyRecord]:
        if policy_id:
            return [r for r in self._policies.values() if r.policy_id == policy_id]
        return list(self._policies.values())

    def set_alias(self, alias: str, policy_id: str, policy_version: str) -> None:
        self._aliases[f"{alias}:{policy_id}"] = f"{policy_id}:{policy_version}"

    def resolve_alias(self, alias: str) -> tuple[str, str] | None:
        target = self._aliases.get(alias)
        if target is None:
            return None
        parts = target.split(":")
        if len(parts) != 2:
            return None
        return parts[0], parts[1]

    def get_active_policy(self, policy_id: str) -> PolicyRecord | None:
        alias_key = f"active:{policy_id}"
        target = self._aliases.get(alias_key)
        if not target:
            return None
        parts = target.split(":")
        if len(parts) != 2:
            return None
        return self.get(parts[0], parts[1])

    def promote(
        self,
        policy_id: str,
        policy_version: str,
        alias: str = "active",
        previous_version: str | None = None,
    ) -> dict[str, Any]:
        record = self.get(policy_id, policy_version)
        if record is None:
            raise ValueError(f"policy not found: {policy_id}:{policy_version}")
        if record.status not in (PolicyStatus.CANDIDATE, PolicyStatus.SHADOW):
            raise ValueError(f"policy not promotable: {record.status}")

        previous = self.get_active_policy(policy_id)
        prev_id = ""
        prev_version = ""
        if previous:
            prev_id = previous.policy_id
            prev_version = previous.policy_version
            previous.status = PolicyStatus.RETIRED
            previous.updated_at = datetime.now(timezone.utc).isoformat()

        record.status = PolicyStatus.ACTIVE
        record.updated_at = datetime.now(timezone.utc).isoformat()
        self.set_alias(alias, policy_id, policy_version)

        promotion_event = {
            "action": "promote",
            "policy_id": policy_id,
            "policy_version": policy_version,
            "previous_policy_id": prev_id,
            "previous_policy_version": prev_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(promotion_event)
        return promotion_event

    def rollback(
        self,
        policy_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        current = self.get_active_policy(policy_id)
        if current is None:
            raise ValueError("no active policy to rollback")
        current.status = PolicyStatus.RETIRED
        current.updated_at = datetime.now(timezone.utc).isoformat()

        candidates = [
            r for r in self._policies.values()
            if r.policy_id == policy_id and r.status == PolicyStatus.SHADOW
        ]
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        target = candidates[0] if candidates else None

        if target is None:
            raise ValueError("no shadow policy available for rollback")

        target.status = PolicyStatus.ACTIVE
        target.updated_at = datetime.now(timezone.utc).isoformat()
        self.set_alias("active", target.policy_id, target.policy_version)

        rollback_event = {
            "action": "rollback",
            "policy_id": policy_id,
            "from_policy_version": current.policy_version,
            "to_policy_version": target.policy_version,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(rollback_event)
        return rollback_event

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    @staticmethod
    def _key(policy_id: str, policy_version: str) -> str:
        return f"{policy_id}:{policy_version}"
