"""Evidence handling for adaptive ranking.

Provides historical evidence lookup and transformation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EvidenceProvider:
    """Provides historical evidence for adaptive ranking."""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    async def get_evidence(
        self,
        action_type: str,
        target_id: str | None = None,
        user_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Retrieve historical evidence for an action."""
        user_scope = user_scope or {}
        evidence: dict[str, Any] = {}

        if self._store is not None:
            try:
                raw = await self._store.get_evidence(action_type, target_id, user_scope)
                if raw:
                    evidence = raw
            except Exception as exc:  # noqa: BLE001
                logger.debug("Evidence store lookup failed: %s", exc)

        if not evidence:
            evidence = self._default_evidence(action_type, target_id)

        return evidence

    def _default_evidence(
        self, action_type: str, target_id: str | None
    ) -> dict[str, Any]:
        return {
            "action_type": action_type,
            "target_id": target_id,
            "success_rate": 0.5,
            "sample_count": 0,
            "confidence_interval": 0.5,
            "median_latency_ms": 0.0,
            "retry_rate": 0.0,
            "correction_rate": 0.0,
        }

    async def aggregate_user_evidence(
        self, user_id: str, tenant_id: str
    ) -> dict[str, Any]:
        """Aggregate evidence specific to a user."""
        if self._store is not None:
            try:
                return await self._store.aggregate_for_user(user_id, tenant_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("User evidence aggregation failed: %s", exc)
        return {}

    async def aggregate_global_evidence(self) -> dict[str, Any]:
        """Aggregate global evidence across users."""
        if self._store is not None:
            try:
                return await self._store.aggregate_global()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Global evidence aggregation failed: %s", exc)
        return {}
