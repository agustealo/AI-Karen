from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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

    async def save_unique_outcome_async(self, payload: dict[str, Any]) -> None:
        """Strict append required for governed action receipts."""
        raise OutcomeStoreError("Strict append-only outcome persistence unavailable")

    async def save_unique_outcomes_async(
        self, payloads: list[dict[str, Any]]
    ) -> None:
        """Atomic, tenant-scoped strict batch for verified evaluation evidence.

        Reject adapters without native atomicity. Never implement as a loop
        of separately committed single-outcome writes.
        """
        if payloads:
            raise OutcomeStoreError(
                "Atomic governed outcome batch persistence unavailable"
            )

    async def list_task_reviews_async(
        self, task_id: str, *, tenant_id: str, user_id: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Owner-scoped task review history, never a tenant-wide fallback."""
        raise OutcomeStoreError("Task review history is not available")

    async def list_governed_tool_receipts_async(
        self,
        *,
        trajectory_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tool-runtime receipts only for the exact principal and run."""
        raise OutcomeStoreError("Governed tool receipts are unavailable")

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
        source: str | None = None,
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

    async def save_unique_outcome_async(self, payload: dict[str, Any]) -> None:
        identifier = str(payload.get("outcome_id") or "").strip()
        if not identifier or any(
            item.get("outcome_id") == identifier for item in self._records
        ):
            raise OutcomeStoreError("Duplicate or missing governed outcome identifier")
        self.save_outcome(payload)

    async def save_unique_outcomes_async(
        self, payloads: list[dict[str, Any]]
    ) -> None:
        if not payloads:
            return
        identities = [str(p.get("outcome_id") or "").strip() for p in payloads]
        tenants = {p.get("tenant_id") for p in payloads}
        if (
            any(not key for key in identities)
            or len(set(identities)) != len(identities)
            or len(tenants) != 1
            or not next(iter(tenants))
            or any(item.get("outcome_id") in identities for item in self._records)
        ):
            raise OutcomeStoreError(
                "Atomic in-memory evaluation batch contains duplicate or cross-tenant identity"
            )
        # Validate the entire set before allowing any mutation.
        for payload in payloads:
            if payload.get("source") != "intelligence.ml":
                raise OutcomeStoreError(
                    "Atomic evaluation batches must contain governed ML evidence"
                )
            PostgresOutcomeStore._validated_identity(payload)
        for payload in payloads:
            self.save_outcome(payload)

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

    async def list_governed_tool_receipts_async(
        self,
        *,
        trajectory_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not trajectory_id or not tenant_id or not user_id:
            raise OutcomeStoreError("Tool receipt scope is required")
        events = [
            record
            for record in self.get_for_trajectory(
                trajectory_id, tenant_id=tenant_id,
            )
            if record.get("user_id") == user_id
            and record.get("source") == "runtime.execution"
            and (record.get("metadata") or {}).get("event_type")
            == "agent.tool.execution"
            and (record.get("metadata") or {}).get("receipt_version")
            == "governed-tool.v1"
        ]
        return sorted(
            events,
            key=lambda value: (
                str(value.get("recorded_at") or ""),
                str(value.get("outcome_id") or ""),
            ),
            reverse=True,
        )[:max(1, min(int(limit), 100))]

    async def list_task_reviews_async(
        self, task_id: str, *, tenant_id: str, user_id: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not tenant_id or not user_id:
            raise OutcomeStoreError("Tenant and user required")
        events = [
            dict(item)
            for item in self.get_for_trajectory(
                f"task:{task_id}", tenant_id=tenant_id,
            )
            if item.get("user_id") == user_id
            and item.get("source") == "user.feedback"
            and item.get("feedback_type") == "task_completion_confirmation"
            and item.get("task_id") == task_id
        ]
        return sorted(
            events, key=lambda item: (
                str(item.get("recorded_at") or ""),
                str(item.get("outcome_id") or ""),
            ), reverse=True,
        )[:max(1, min(int(limit), 100))]

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        user_id: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        indices = self._tenant_index.get(tenant_id or "_unknown", [])
        records = [self._records[i] for i in indices if i < len(self._records)]
        if user_id is not None:
            records = [record for record in records if str(record.get("user_id") or "") == user_id]
        if source is not None:
            if source not in {"runtime.execution", "user.feedback", "intelligence.ml"}:
                raise ValueError("Unsupported governed outcome evidence source")
            records = [record for record in records if record.get("source") == source]
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
    def _normalize_recorded_at(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise OutcomeStoreError("recorded_at must be an ISO-8601 timestamp") from exc
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        raise OutcomeStoreError(
            "recorded_at must be a datetime, ISO-8601 string, or null"
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
            "recorded_at": PostgresOutcomeStore._normalize_recorded_at(
                payload.get("recorded_at")
            ),
            "payload": json.dumps(payload, default=str),
        }

    @staticmethod
    def _validated_identity(payload: dict[str, Any]) -> tuple[str, str]:
        tenant_id = PostgresOutcomeStore._require_tenant(payload.get("tenant_id"))
        source = str(payload.get("source") or "").strip()
        if source not in {
            "runtime.execution", "user.feedback", "intelligence.ml",
        }:
            raise OutcomeStoreError(f"Unsupported outcome source: {source or 'missing'}")
        if source == "intelligence.ml":
            metadata = payload.get("metadata")
            if (
                not payload.get("user_id")
                or not payload.get("outcome_id")
                or not isinstance(metadata, dict)
                or metadata.get("schema_version") != "ml_predictor_evidence_v1"
                or metadata.get("label_source") not in {
                    "human_review", "heldout_evaluation",
                }
                or not isinstance(metadata.get("label_evidence_ref"), str)
                or not metadata["label_evidence_ref"]
                or not isinstance(metadata.get("correct"), bool)
                or not isinstance(metadata.get("task"), str)
                or not isinstance(metadata.get("model_id"), str)
                or not isinstance(metadata.get("model_version"), str)
                or not isinstance(metadata.get("feature_version"), str)
                or not all(metadata.get(k) for k in (
                    "task", "model_id", "model_version", "feature_version",
                ))
                or set(metadata) != {
                    "schema_version", "label_source", "label_evidence_ref",
                    "task", "model_id", "model_version", "feature_version",
                    "correct", "raw_probability", "calibrated_probability",
                    "confidence", "calibration_error", "latency_ms",
                    "fallback_used",
                }
                or any(
                    isinstance(metadata.get(k), bool)
                    or not isinstance(metadata.get(k), (int, float))
                    or not math.isfinite(metadata[k])
                    or not 0 <= metadata[k] <= 1
                    for k in (
                        "raw_probability", "calibrated_probability",
                        "confidence", "calibration_error",
                    )
                )
                or isinstance(metadata.get("latency_ms"), bool)
                or not isinstance(metadata.get("latency_ms"), (int, float))
                or not math.isfinite(metadata["latency_ms"])
                or not 0 <= metadata["latency_ms"] <= 600000
                or not isinstance(metadata.get("fallback_used"), bool)
                or len(metadata["label_evidence_ref"]) > 256
                or not metadata["label_evidence_ref"].isascii()
                or not all(
                    ch.isalnum() or ch in "-._:/"
                    for ch in metadata["label_evidence_ref"]
                )
            ):
                raise OutcomeStoreError(
                    "ML evidence requires trusted scoped evaluation provenance without raw labels"
                )
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

    async def save_unique_outcome_async(self, payload: dict[str, Any]) -> None:
        """Commit exactly one new row or fail; never accept silent conflict."""
        tenant, _ = self._validated_identity(payload)
        try:
            async with async_transaction_scope(tenant) as session:
                await self.append_in_transaction(session, payload)
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.strict_append_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": tenant,
                    "error_type": type(exc).__name__,
                },
            )
            raise OutcomeStoreError("Governed outcome was not durably appended") from exc

    async def save_unique_outcomes_async(
        self, payloads: list[dict[str, Any]]
    ) -> None:
        """One transaction or no evidence: batch is never partially learned."""
        if not payloads:
            return
        if len(payloads) > 5000:
            raise OutcomeStoreError("Governed evaluation batch exceeds safety limit")
        identities = [str(p.get("outcome_id") or "").strip() for p in payloads]
        if any(not v for v in identities) or len(set(identities)) != len(identities):
            raise OutcomeStoreError("Evaluation batch IDs must be unique")
        tenants = set()
        for payload in payloads:
            tenant, source = self._validated_identity(payload)
            if source != "intelligence.ml":
                raise OutcomeStoreError("Only evaluated ML evidence may be batch appended")
            tenants.add(tenant)
        if len(tenants) != 1:
            raise OutcomeStoreError("Cross-tenant evidence batch is forbidden")
        tenant = next(iter(tenants))
        try:
            async with async_transaction_scope(tenant) as session:
                for payload in payloads:
                    await self.append_in_transaction(session, payload)
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.atomic_evaluation_batch_failed",
                extra={"tenant_id": tenant, "evidence_count": len(payloads),
                       "error_type": type(exc).__name__},
            )
            raise OutcomeStoreError(
                "Governed evaluation batch did not commit atomically"
            ) from exc

    @staticmethod
    async def append_in_transaction(session: Any, payload: dict[str, Any]) -> None:
        """Append through the canonical outcome schema in a caller-owned transaction.

        Used only when another authoritative state change must commit or roll
        back alongside its outcome event. This method never starts a second
        transaction, and duplicate deterministic receipt IDs fail closed.
        """
        tenant, source = PostgresOutcomeStore._validated_identity(payload)
        result = await session.execute(
            PostgresOutcomeStore._insert_statement(),
            PostgresOutcomeStore._insert_params(
                payload, tenant_id=tenant, source=source,
            ),
        )
        if result.rowcount != 1:
            raise OutcomeStoreError("Outcome event was not appended")

    async def list_governed_tool_receipts_async(
        self,
        *,
        trajectory_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Tenant/user/run-filtered receipt read, never an unscoped audit listing."""
        tenant = self._require_tenant(tenant_id)
        if not trajectory_id or not user_id:
            raise OutcomeStoreError("Tool receipt scope is required")
        bounded = max(1, min(int(limit), 100))
        try:
            async with async_transaction_scope(tenant) as session:
                result = await session.execute(
                    text(
                        """
                        SELECT payload FROM public.outcome_records
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND user_id = CAST(:user_id AS uuid)
                          AND trajectory_id = :trajectory_id
                          AND source = 'runtime.execution'
                          AND payload->'metadata'->>'event_type' = 'agent.tool.execution'
                          AND payload->'metadata'->>'receipt_version' = 'governed-tool.v1'
                        ORDER BY recorded_at DESC, outcome_id DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user_id,
                        "trajectory_id": trajectory_id,
                        "limit": bounded,
                    },
                )
                return [
                    self._payload_from_row(row["payload"])
                    for row in result.mappings().all()
                ]
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.governed_tool_receipts_read_failed",
                extra={
                    "tenant_id": tenant,
                    "user_id": user_id,
                    "trajectory_id": trajectory_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise OutcomeStoreError("Tool receipts unavailable") from exc

    async def list_task_reviews_async(
        self,
        task_id: str,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return only authenticated-owner reviews for a task trajectory."""
        tenant = self._require_tenant(tenant_id)
        if not user_id:
            raise OutcomeStoreError("User identity required for task review history")
        bounded = max(1, min(int(limit), 100))
        try:
            async with async_transaction_scope(tenant) as session:
                result = await session.execute(
                    text(
                        """
                        SELECT payload FROM public.outcome_records
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND user_id = CAST(:user_id AS uuid)
                          AND trajectory_id = :trajectory_id
                          AND source = 'user.feedback'
                          AND payload->>'feedback_type' = 'task_completion_confirmation'
                          AND payload->>'task_id' = :task_id
                        ORDER BY recorded_at DESC, outcome_id DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user_id,
                        "trajectory_id": f"task:{task_id}",
                        "task_id": task_id,
                        "limit": bounded,
                    },
                )
                return [
                    self._payload_from_row(row["payload"])
                    for row in result.mappings().all()
                ]
        except OutcomeStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "outcome.store.task_review_read_failed",
                extra={"tenant_id": tenant, "user_id": user_id, "task_id": task_id},
            )
            raise OutcomeStoreError("Task review history unavailable") from exc

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
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant = self._require_tenant(tenant_id)
        bounded_limit = max(1, min(int(limit), 1000))
        user = str(user_id or "").strip()
        if source is not None and source not in {
            "runtime.execution", "user.feedback", "intelligence.ml",
        }:
            raise ValueError("Unsupported governed outcome evidence source")
        scoped_source = source or ""
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.outcome_records
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND (:user_id = '' OR user_id = CAST(:user_id AS uuid))
                          AND (:source = '' OR source = :source)
                        ORDER BY recorded_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "user_id": user,
                     "source": scoped_source, "limit": bounded_limit},
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
