from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope, transaction_scope

logger = logging.getLogger(__name__)


class OutcomeStoreError(RuntimeError):
    """Durable outcome persistence or retrieval failed."""


class OutcomeStore(ABC):
    """Abstract storage for append-only outcome evidence."""

    @abstractmethod
    def save_outcome(self, payload: dict[str, Any]) -> None:
        """Persist an outcome payload."""

    async def save_outcome_async(self, payload: dict[str, Any]) -> None:
        """Persist without blocking an async runtime path.

        Stores with native async I/O should override this method. The default
        delegates synchronous adapters to a worker thread so they cannot block
        the event loop.
        """
        import asyncio

        await asyncio.to_thread(self.save_outcome, payload)

    @abstractmethod
    def get_for_trajectory(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return outcome evidence linked to a trajectory."""

    @abstractmethod
    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List recent tenant-scoped outcome evidence."""


class InMemoryOutcomeStore(OutcomeStore):
    """Non-durable test store. Production composition uses PostgreSQL."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._trajectory_index: dict[str, list[int]] = {}
        self._tenant_index: dict[str, list[int]] = {}

    def save_outcome(self, payload: dict[str, Any]) -> None:
        idx = len(self._records)
        record = dict(payload)
        self._records.append(record)
        trajectory_id = record.get("trajectory_id")
        tenant_id = record.get("tenant_id") or "_unknown"
        if trajectory_id:
            self._trajectory_index.setdefault(str(trajectory_id), []).append(idx)
        self._tenant_index.setdefault(str(tenant_id), []).append(idx)

    def get_for_trajectory(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        indices = self._trajectory_index.get(trajectory_id, [])
        records = [self._records[i] for i in indices if i < len(self._records)]
        if tenant_id is not None:
            records = [record for record in records if record.get("tenant_id") == tenant_id]
        return [dict(record) for record in records]

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        indices = self._tenant_index.get(tenant_id or "_unknown", [])
        records = [self._records[i] for i in indices if i < len(self._records)]
        if user_id is not None:
            records = [record for record in records if str(record.get("user_id") or "") == user_id]
        return [dict(record) for record in records[-limit:]]


class PostgresOutcomeStore(OutcomeStore):
    """Canonical PostgreSQL-backed append-only outcome evidence store."""

    @staticmethod
    def _require_tenant(tenant_id: str | None) -> str:
        tenant = str(tenant_id or "").strip()
        if not tenant or tenant == "default":
            raise OutcomeStoreError("Explicit tenant_id is required for outcome persistence")
        return tenant

    @staticmethod
    def _payload_from_row(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        raise OutcomeStoreError("Stored outcome payload is not a JSON object")

    @staticmethod
    def _insert_statement():
        return text(
            """
            INSERT INTO public.outcome_records (
                outcome_id,
                trajectory_id,
                decision_observation_id,
                request_id,
                correlation_id,
                message_id,
                conversation_id,
                session_id,
                tenant_id,
                user_id,
                source,
                recorded_at,
                payload
            ) VALUES (
                :outcome_id,
                :trajectory_id,
                :decision_observation_id,
                :request_id,
                :correlation_id,
                :message_id,
                :conversation_id,
                :session_id,
                CAST(:tenant_id AS uuid),
                NULLIF(:user_id, '')::uuid,
                :source,
                COALESCE(CAST(:recorded_at AS timestamptz), now()),
                CAST(:payload AS jsonb)
            )
            ON CONFLICT (outcome_id) DO NOTHING
            """
        )

    @staticmethod
    def _insert_params(
        payload: dict[str, Any],
        *,
        tenant_id: str,
        source: str,
    ) -> dict[str, Any]:
        return {
            "outcome_id": payload.get("outcome_id"),
            "trajectory_id": payload.get("trajectory_id"),
            "decision_observation_id": payload.get("decision_observation_id"),
            "request_id": payload.get("request_id"),
            "correlation_id": payload.get("correlation_id"),
            "message_id": payload.get("message_id"),
            "conversation_id": payload.get("conversation_id"),
            "session_id": payload.get("session_id"),
            "tenant_id": tenant_id,
            "user_id": str(payload.get("user_id") or ""),
            "source": source,
            "recorded_at": payload.get("recorded_at"),
            "payload": json.dumps(payload, default=str),
        }

    @staticmethod
    def _validated_identity(payload: dict[str, Any]) -> tuple[str, str]:
        tenant_id = PostgresOutcomeStore._require_tenant(payload.get("tenant_id"))
        source = str(payload.get("source") or "").strip()
        if source not in {"runtime.execution", "user.feedback"}:
            raise OutcomeStoreError(f"Unsupported outcome source: {source or 'missing'}")
        return tenant_id, source

    def save_outcome(self, payload: dict[str, Any]) -> None:
        tenant_id, source = self._validated_identity(payload)
        try:
            with transaction_scope(tenant_id) as session:
                session.execute(
                    self._insert_statement(),
                    self._insert_params(payload, tenant_id=tenant_id, source=source),
                )
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.save_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": tenant_id,
                    "user_id": payload.get("user_id"),
                    "source": source,
                },
            )
            raise OutcomeStoreError("Outcome persistence failed") from exc

    async def save_outcome_async(self, payload: dict[str, Any]) -> None:
        """Persist through SQLAlchemy's async engine on async runtime paths."""
        tenant_id, source = self._validated_identity(payload)
        try:
            async with async_transaction_scope(tenant_id) as session:
                await session.execute(
                    self._insert_statement(),
                    self._insert_params(payload, tenant_id=tenant_id, source=source),
                )
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.async_save_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": tenant_id,
                    "user_id": payload.get("user_id"),
                    "source": source,
                },
            )
            raise OutcomeStoreError("Outcome persistence failed") from exc

    def get_for_trajectory(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.outcome_records
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND trajectory_id = :trajectory_id
                        ORDER BY recorded_at ASC
                        """
                    ),
                    {"tenant_id": tenant, "trajectory_id": trajectory_id},
                ).mappings().all()
            return [self._payload_from_row(row["payload"]) for row in rows]
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.trajectory_read_failed",
                extra={"tenant_id": tenant, "trajectory_id": trajectory_id},
            )
            raise OutcomeStoreError("Outcome trajectory retrieval failed") from exc

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant = self._require_tenant(tenant_id)
        bounded_limit = max(1, min(int(limit), 1000))
        user = str(user_id or "").strip()
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.outcome_records
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND (:user_id = '' OR user_id = CAST(:user_id AS uuid))
                        ORDER BY recorded_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "user_id": user, "limit": bounded_limit},
                ).mappings().all()
            return [self._payload_from_row(row["payload"]) for row in rows]
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.tenant_read_failed",
                extra={"tenant_id": tenant, "user_id": user or None},
            )
            raise OutcomeStoreError("Outcome tenant retrieval failed") from exc


_outcome_store: OutcomeStore | None = None


def get_outcome_store() -> OutcomeStore:
    """Return the canonical durable runtime outcome evidence store."""
    global _outcome_store
    if _outcome_store is None:
        _outcome_store = PostgresOutcomeStore()
    return _outcome_store


def set_outcome_store(store: OutcomeStore | None) -> None:
    """Install an explicit store for tests/application composition."""
    global _outcome_store
    _outcome_store = store


__all__ = [
    "InMemoryOutcomeStore",
    "OutcomeStore",
    "OutcomeStoreError",
    "PostgresOutcomeStore",
    "get_outcome_store",
    "set_outcome_store",
]
