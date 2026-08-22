from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ai_karen_engine.core.runtime.outcome.contracts import OutcomeRecord


class OutcomeStore(ABC):
    """Abstract storage for outcome records."""

    @abstractmethod
    def save_outcome(self, payload: dict[str, Any]) -> None:
        """Persist an outcome payload."""

    @abstractmethod
    def get_for_trajectory(self, trajectory_id: str) -> list[dict[str, Any]]:
        """Return all outcomes linked to a trajectory."""

    @abstractmethod
    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List recent outcomes for a tenant."""


class InMemoryOutcomeStore(OutcomeStore):
    """Non-durable in-memory store for testing and fallback."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._trajectory_index: dict[str, list[int]] = {}
        self._tenant_index: dict[str, list[int]] = {}

    def save_outcome(self, payload: dict[str, Any]) -> None:
        idx = len(self._records)
        self._records.append(payload)
        trajectory_id = payload.get("trajectory_id")
        tenant_id = payload.get("tenant_id") or "_unknown"
        if trajectory_id:
            self._trajectory_index.setdefault(trajectory_id, []).append(idx)
        self._tenant_index.setdefault(tenant_id, []).append(idx)

    def get_for_trajectory(self, trajectory_id: str) -> list[dict[str, Any]]:
        indices = self._trajectory_index.get(trajectory_id, [])
        return [self._records[i] for i in indices if i < len(self._records)]

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        indices = self._tenant_index.get(tenant_id or "_unknown", [])
        return [self._records[i] for i in indices[-limit:] if i < len(self._records)]


class PostgresOutcomeStore(OutcomeStore):
    """PostgreSQL-backed outcome store.

    Canonical durable store. Outcomes are append-only; edits are audited
    by retaining original recorded_at and source metadata.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def save_outcome(self, payload: dict[str, Any]) -> None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            db.execute(
                """
                INSERT INTO outcome_records (
                    outcome_id, trajectory_id, message_id, conversation_id,
                    tenant_id, user_id, recorded_at, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, now(), %s)
                """,
                (
                    payload.get("outcome_id"),
                    payload.get("trajectory_id"),
                    payload.get("message_id"),
                    payload.get("conversation_id"),
                    payload.get("tenant_id"),
                    payload.get("user_id"),
                    json.dumps(payload, default=str),
                ),
            )
        except Exception:
            pass

    def get_for_trajectory(self, trajectory_id: str) -> list[dict[str, Any]]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                "SELECT payload FROM outcome_records WHERE trajectory_id = %s ORDER BY recorded_at ASC",
                (trajectory_id,),
            )
            return [json.loads(row["payload"]) for row in rows]
        except Exception:
            return []

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                "SELECT payload FROM outcome_records WHERE tenant_id = %s ORDER BY recorded_at DESC LIMIT %s",
                (tenant_id, limit),
            )
            return [json.loads(row["payload"]) for row in rows]
        except Exception:
            return []
