"""PostgreSQL implementation of the canonical durable QueueClient contract."""

from __future__ import annotations

import json
import uuid
from typing import Optional

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.queue_client import QueueClient, QueueItem

_QUEUE_LEASE_SECONDS = 300
_RETRY_DELAY_SECONDS = 30


class PostgresQueueClient(QueueClient):
    """Durable queue backed by migration-owned PostgreSQL state."""

    @staticmethod
    async def _authorize_worker(session) -> None:
        await session.execute(
            text("SELECT set_config('app.automation_worker', '1', true)")
        )

    async def enqueue(self, item: QueueItem) -> RepositoryResult[str]:
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                await session.execute(
                    text(
                        """
                        INSERT INTO public.automation_queue_items (
                            item_id, queue_name, payload, tenant_id,
                            created_at, available_at, attempts, max_attempts,
                            last_error, status
                        ) VALUES (
                            :item_id, :queue_name, CAST(:payload AS jsonb),
                            CAST(NULLIF(:tenant_id, '') AS uuid),
                            :created_at, :available_at, :attempts, :max_attempts,
                            :last_error, 'pending'
                        )
                        """
                    ),
                    {
                        "item_id": item.id,
                        "queue_name": item.queue,
                        "payload": json.dumps(item.payload),
                        "tenant_id": item.tenant_id or "",
                        "created_at": item.created_at,
                        "available_at": item.available_at,
                        "attempts": item.attempts,
                        "max_attempts": item.max_attempts,
                        "last_error": item.last_error,
                    },
                )
            return RepositoryResult(success=True, data=item.id)
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))

    async def dequeue(
        self, queue: str, worker_id: str
    ) -> RepositoryResult[Optional[QueueItem]]:
        claim_token = str(uuid.uuid4())
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                await session.execute(
                    text(
                        """
                        UPDATE public.automation_queue_items
                        SET status = 'dead_letter',
                            last_error = COALESCE(last_error, 'claim lease expired after max attempts'),
                            claimed_by = NULL,
                            claim_token = NULL,
                            claimed_at = NULL,
                            claim_expires_at = NULL
                        WHERE queue_name = :queue_name
                          AND status = 'processing'
                          AND claim_expires_at <= now()
                          AND attempts >= max_attempts
                        """
                    ),
                    {"queue_name": queue},
                )
                result = await session.execute(
                    text(
                        """
                        WITH candidate AS (
                            SELECT item_id
                            FROM public.automation_queue_items
                            WHERE queue_name = :queue_name
                              AND (
                                  status = 'pending'
                                  OR (
                                      status = 'processing'
                                      AND claim_expires_at <= now()
                                  )
                              )
                              AND available_at <= now()
                              AND attempts < max_attempts
                            ORDER BY available_at ASC, created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE public.automation_queue_items AS items
                        SET status = 'processing',
                            attempts = attempts + 1,
                            claimed_by = :worker_id,
                            claim_token = CAST(:claim_token AS uuid),
                            claimed_at = now(),
                            claim_expires_at = now() + make_interval(secs => :lease_seconds)
                        FROM candidate
                        WHERE items.item_id = candidate.item_id
                        RETURNING items.*
                        """
                    ),
                    {
                        "queue_name": queue,
                        "worker_id": worker_id,
                        "claim_token": claim_token,
                        "lease_seconds": _QUEUE_LEASE_SECONDS,
                    },
                )
                row = result.mappings().one_or_none()
                if row is None:
                    return RepositoryResult(success=True, data=None)
                item = QueueItem(
                    id=row["item_id"],
                    queue=row["queue_name"],
                    payload=dict(row["payload"] or {}),
                    tenant_id=str(row["tenant_id"]) if row["tenant_id"] else None,
                    created_at=row["created_at"],
                    available_at=row["available_at"],
                    attempts=int(row["attempts"]),
                    max_attempts=int(row["max_attempts"]),
                    last_error=row["last_error"],
                    claim_token=claim_token,
                )
                return RepositoryResult(success=True, data=item)
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))

    async def renew_claim(
        self,
        queue: str,
        item_id: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        if not claim_token:
            return RepositoryResult(success=False, error="claim_token is required")
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                result = await session.execute(
                    text(
                        """
                        UPDATE public.automation_queue_items
                        SET claim_expires_at = now() + make_interval(secs => :lease_seconds)
                        WHERE item_id = :item_id
                          AND queue_name = :queue_name
                          AND status = 'processing'
                          AND claim_token = CAST(:claim_token AS uuid)
                          AND claim_expires_at > now()
                        RETURNING item_id
                        """
                    ),
                    {
                        "item_id": item_id,
                        "queue_name": queue,
                        "claim_token": claim_token,
                        "lease_seconds": _QUEUE_LEASE_SECONDS,
                    },
                )
                return RepositoryResult(
                    success=True, data=result.scalar_one_or_none() is not None
                )
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))

    async def ack(
        self,
        queue: str,
        item_id: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        if not claim_token:
            return RepositoryResult(success=False, error="claim_token is required")
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                result = await session.execute(
                    text(
                        """
                        UPDATE public.automation_queue_items
                        SET status = 'completed',
                            completed_at = now(),
                            claimed_by = NULL,
                            claim_token = NULL,
                            claimed_at = NULL,
                            claim_expires_at = NULL
                        WHERE item_id = :item_id
                          AND queue_name = :queue_name
                          AND status = 'processing'
                          AND claim_token = CAST(:claim_token AS uuid)
                        RETURNING item_id
                        """
                    ),
                    {
                        "item_id": item_id,
                        "queue_name": queue,
                        "claim_token": claim_token,
                    },
                )
                return RepositoryResult(
                    success=True, data=result.scalar_one_or_none() is not None
                )
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))

    async def nack(
        self,
        queue: str,
        item_id: str,
        error: str,
        claim_token: Optional[str] = None,
    ) -> RepositoryResult[bool]:
        if not claim_token:
            return RepositoryResult(success=False, error="claim_token is required")
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                result = await session.execute(
                    text(
                        """
                        UPDATE public.automation_queue_items
                        SET status = CASE
                                WHEN attempts >= max_attempts
                                THEN 'dead_letter'
                                ELSE 'pending'
                            END,
                            available_at = CASE
                                WHEN attempts >= max_attempts
                                THEN available_at
                                ELSE now() + make_interval(secs => :retry_delay)
                            END,
                            last_error = :error,
                            claimed_by = NULL,
                            claim_token = NULL,
                            claimed_at = NULL,
                            claim_expires_at = NULL
                        WHERE item_id = :item_id
                          AND queue_name = :queue_name
                          AND status = 'processing'
                          AND claim_token = CAST(:claim_token AS uuid)
                        RETURNING item_id
                        """
                    ),
                    {
                        "item_id": item_id,
                        "queue_name": queue,
                        "claim_token": claim_token,
                        "error": error[:4000],
                        "retry_delay": _RETRY_DELAY_SECONDS,
                    },
                )
                return RepositoryResult(
                    success=True, data=result.scalar_one_or_none() is not None
                )
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))

    async def health_check(self) -> RepositoryResult:
        try:
            async with async_transaction_scope() as session:
                await self._authorize_worker(session)
                result = await session.execute(
                    text(
                        """
                        SELECT to_regclass('public.automation_queue_items') IS NOT NULL
                        """
                    )
                )
                ready = bool(result.scalar_one())
            return RepositoryResult(
                success=ready,
                data={"status": "ready" if ready else "missing_schema"},
                error=None if ready else "automation_queue_items migration is not applied",
            )
        except Exception as exc:
            return RepositoryResult(success=False, error=str(exc))


__all__ = ["PostgresQueueClient"]
