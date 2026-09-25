"""PostgreSQL lifecycle authority for model-download jobs."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

# One transaction-scoped advisory lock serializes reclaim/count/claim so every
# worker process observes one installation-wide concurrency ceiling.
_MODEL_DOWNLOAD_CLAIM_LOCK = 0x4B4152454E4D444C
_MODEL_DOWNLOAD_IMPORT_LOCK = 0x4B4152454E4D494D


def _json(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, separators=(",", ":"), default=str)


def _mapping(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


async def _lock_install_target(session: Any, install_path: Optional[str]) -> None:
    """Serialize durable mutations for one canonical installation target."""
    if not install_path:
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:install_path, 0))"),
        {"install_path": install_path},
    )


async def _global_capacity_available(session: Any) -> bool:
    limit_result = await session.execute(
        text(
            """
            SELECT max_concurrent_downloads
            FROM public.model_download_runtime_settings
            WHERE singleton = true
            FOR UPDATE
            """
        )
    )
    global_concurrency = limit_result.scalar_one_or_none()
    if global_concurrency is None:
        raise RuntimeError("model download runtime settings are not initialized")

    active_result = await session.execute(
        text(
            """
            SELECT count(*)
            FROM public.model_download_jobs
            WHERE status IN ('running', 'promoting', 'pause_requested')
              AND lease_token IS NOT NULL
              AND lease_expires_at > clock_timestamp()
            """
        )
    )
    return int(active_result.scalar_one()) < int(global_concurrency)


async def _fail_or_retry_in_session(
    session: Any,
    *,
    job_id: str,
    lease_token: str,
    error: str,
    retry_base_seconds: int,
) -> Optional[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            UPDATE public.model_download_jobs
            SET status = CASE
                    WHEN cancel_requested THEN 'cancelled'
                    WHEN pause_requested THEN 'paused'
                    WHEN attempt_count >= max_attempts THEN 'failed'
                    ELSE 'queued'
                END,
                message = CASE
                    WHEN cancel_requested THEN 'Cancelled after active download stopped'
                    WHEN pause_requested THEN 'Paused after active download stopped'
                    WHEN attempt_count >= max_attempts
                        THEN 'Download failed after maximum retry attempts'
                    ELSE 'Download failed; queued for retry'
                END,
                error = CASE
                    WHEN cancel_requested OR pause_requested THEN error
                    ELSE :error
                END,
                available_at = CASE
                    WHEN cancel_requested OR pause_requested OR attempt_count >= max_attempts
                        THEN available_at
                    ELSE now() + (:retry_base_seconds * GREATEST(attempt_count, 1)) * interval '1 second'
                END,
                dead_lettered_at = CASE
                    WHEN cancel_requested OR pause_requested THEN NULL
                    WHEN attempt_count >= max_attempts THEN now()
                    ELSE NULL
                END,
                completed_at = CASE
                    WHEN cancel_requested THEN now()
                    WHEN pause_requested THEN NULL
                    WHEN attempt_count >= max_attempts THEN now()
                    ELSE NULL
                END,
                publication_source_lease_token = NULL,
                lease_owner = NULL,
                lease_token = NULL,
                lease_expires_at = NULL,
                heartbeat_at = NULL
            WHERE job_id = :job_id
              AND status IN ('running', 'promoting', 'pause_requested')
              AND lease_token = CAST(:lease_token AS uuid)
            RETURNING *
            """
        ),
        {
            "job_id": job_id,
            "lease_token": lease_token,
            "error": error,
            "retry_base_seconds": retry_base_seconds,
        },
    )
    return _mapping(result.mappings().first())


class _ModelDownloadPublication:
    """Finalize one promotion while its durable row and target locks stay held."""

    def __init__(
        self,
        *,
        session: Any,
        job_id: str,
        lease_token: str,
        install_path: str,
    ) -> None:
        self._session = session
        self._job_id = job_id
        self._lease_token = lease_token
        self._install_path = install_path
        self._finished = False

    async def complete(self, result_payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._finished:
            raise RuntimeError(f"Model download publication already finalized: {self._job_id}")

        result = await self._session.execute(
            text(
                """
                UPDATE public.model_download_jobs
                SET status = 'completed', progress = 1.0,
                    message = 'Download completed', error = NULL,
                    result = CAST(:result_payload AS jsonb), install_path = :install_path,
                    completed_at = now(), publication_source_lease_token = NULL,
                    lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL
                WHERE job_id = :job_id
                  AND status = 'promoting'
                  AND cancel_requested = false
                  AND pause_requested = false
                  AND lease_token = CAST(:lease_token AS uuid)
                RETURNING *
                """
            ),
            {
                "job_id": self._job_id,
                "lease_token": self._lease_token,
                "result_payload": _json(dict(result_payload)),
                "install_path": self._install_path,
            },
        )
        completed = _mapping(result.mappings().first())
        if completed is None:
            raise RuntimeError(
                f"Model download publication ownership changed while locked: {self._job_id}"
            )

        await self._session.execute(
            text(
                """
                UPDATE public.model_download_jobs
                SET status = 'cancelled',
                    cancel_requested = true,
                    pause_requested = false,
                    message = 'Superseded by completed canonical job for the same install target',
                    completed_at = now(),
                    lease_owner = NULL,
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL
                WHERE job_id <> :job_id
                  AND install_path = :install_path
                  AND status IN ('queued', 'paused')
                  AND lease_token IS NULL
                """
            ),
            {"job_id": self._job_id, "install_path": self._install_path},
        )
        await self._session.execute(
            text(
                """
                UPDATE public.model_download_jobs
                SET cancel_requested = true,
                    message = 'Cancellation requested because the install target completed elsewhere'
                WHERE job_id <> :job_id
                  AND install_path = :install_path
                  AND status IN ('running', 'pause_requested')
                  AND lease_token IS NOT NULL
                  AND lease_expires_at > now()
                """
            ),
            {"job_id": self._job_id, "install_path": self._install_path},
        )
        self._finished = True
        return completed

    async def abort_for_retry(
        self,
        *,
        error: str,
        retry_base_seconds: int,
    ) -> dict[str, Any]:
        if self._finished:
            raise RuntimeError(f"Model download publication already finalized: {self._job_id}")
        row = await _fail_or_retry_in_session(
            self._session,
            job_id=self._job_id,
            lease_token=self._lease_token,
            error=error,
            retry_base_seconds=retry_base_seconds,
        )
        if row is None:
            raise RuntimeError(
                f"Model download publication ownership changed while aborting: {self._job_id}"
            )
        self._finished = True
        return row


class ModelDownloadRepository:
    """Own durable job state, runtime cap, target exclusivity, and lease fencing."""

    async def initialize_global_concurrency_limit(self, default_limit: int) -> int:
        async with async_transaction_scope() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.model_download_runtime_settings (
                        singleton, max_concurrent_downloads
                    ) VALUES (true, :default_limit)
                    ON CONFLICT (singleton) DO NOTHING
                    """
                ),
                {"default_limit": default_limit},
            )
            result = await session.execute(
                text(
                    """
                    SELECT max_concurrent_downloads
                    FROM public.model_download_runtime_settings
                    WHERE singleton = true
                    """
                )
            )
            return int(result.scalar_one())

    async def get_global_concurrency_limit(self) -> int:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    SELECT max_concurrent_downloads
                    FROM public.model_download_runtime_settings
                    WHERE singleton = true
                    """
                )
            )
            value = result.scalar_one_or_none()
            if value is None:
                raise RuntimeError("model download runtime settings are not initialized")
            return int(value)

    async def set_global_concurrency_limit(self, value: int) -> int:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_runtime_settings
                    SET max_concurrent_downloads = :value
                    WHERE singleton = true
                    RETURNING max_concurrent_downloads
                    """
                ),
                {"value": value},
            )
            updated = result.scalar_one_or_none()
            if updated is None:
                raise RuntimeError("model download runtime settings are not initialized")
            return int(updated)

    async def create_job(self, payload: Mapping[str, Any], *, max_attempts: int) -> dict[str, Any]:
        """Create one durable job per canonical install target.

        Concurrent requests for a target already owned by nonterminal durable
        work reuse that job instead of creating a second filesystem mutator.
        The target-scoped advisory lock makes the check/insert atomic across
        API processes without introducing process-local authority.
        """
        statement = text(
            """
            INSERT INTO public.model_download_jobs (
                job_id, model_id, revision, channel_id, storage_key, status,
                progress, message, error, result, requested_by, trust_remote_code,
                license_accepted, include_patterns, exclude_patterns, pin,
                force_redownload, pause_requested, cancel_requested, warnings,
                detected_runtime, detected_modality, install_path, max_attempts
            ) VALUES (
                :job_id, :model_id, :revision, :channel_id, :storage_key, 'queued',
                :progress, :message, :error, CAST(:result AS jsonb), :requested_by,
                :trust_remote_code, :license_accepted,
                CAST(:include_patterns AS jsonb), CAST(:exclude_patterns AS jsonb),
                :pin, :force_redownload, false, false, CAST(:warnings AS jsonb),
                :detected_runtime, :detected_modality, :install_path, :max_attempts
            )
            RETURNING *
            """
        )
        params = {
            "job_id": payload["job_id"],
            "model_id": payload["model_id"],
            "revision": payload.get("revision"),
            "channel_id": payload["channel_id"],
            "storage_key": payload.get("storage_key"),
            "progress": float(payload.get("progress") or 0.0),
            "message": str(payload.get("message") or "Queued for download"),
            "error": payload.get("error"),
            "result": _json(payload.get("result")),
            "requested_by": payload.get("requested_by"),
            "trust_remote_code": bool(payload.get("trust_remote_code", False)),
            "license_accepted": bool(payload.get("license_accepted", False)),
            "include_patterns": _json(payload.get("include_patterns")),
            "exclude_patterns": _json(payload.get("exclude_patterns")),
            "pin": bool(payload.get("pin", False)),
            "force_redownload": bool(payload.get("force_redownload", False)),
            "warnings": _json(list(payload.get("warnings") or [])),
            "detected_runtime": payload.get("detected_runtime"),
            "detected_modality": payload.get("detected_modality"),
            "install_path": payload.get("install_path"),
            "max_attempts": max_attempts,
        }
        async with async_transaction_scope() as session:
            install_path = str(params["install_path"] or "").strip() or None
            await _lock_install_target(session, install_path)
            if install_path is not None:
                existing_result = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM public.model_download_jobs
                        WHERE install_path = :install_path
                          AND status IN (
                              'queued', 'running', 'promoting', 'paused', 'pause_requested'
                          )
                        ORDER BY
                            CASE
                                WHEN lease_token IS NOT NULL
                                 AND lease_expires_at > now() THEN 0
                                WHEN status = 'queued' THEN 1
                                WHEN status = 'paused' THEN 2
                                ELSE 3
                            END,
                            created_at ASC,
                            job_id ASC
                        FOR UPDATE
                        LIMIT 1
                        """
                    ),
                    {"install_path": install_path},
                )
                existing = _mapping(existing_result.mappings().first())
                if existing is not None:
                    existing["_target_reused"] = True
                    existing["_requested_job_id"] = str(payload["job_id"])
                    return existing

            result = await session.execute(statement, params)
            created = dict(result.mappings().one())
            created["_target_reused"] = False
            return created

    async def list_jobs(self, *, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM public.model_download_jobs"
        params: dict[str, Any] = {"limit": limit}
        if status:
            sql += " WHERE status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        async with async_transaction_scope() as session:
            result = await session.execute(text(sql), params)
            return [dict(row) for row in result.mappings().all()]

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text("SELECT * FROM public.model_download_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def cancel_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Request cancellation without releasing a live execution lease.

        Blocking downloads run in ``asyncio.to_thread`` and cannot be stopped by
        cancelling the asyncio task. A leased job therefore keeps its lease and
        remains counted as active until the real I/O returns, fails, or its
        lease expires. Unclaimed work can be cancelled immediately.
        """
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET cancel_requested = true,
                        status = CASE
                            WHEN lease_token IS NOT NULL THEN status
                            ELSE 'cancelled'
                        END,
                        message = CASE
                            WHEN lease_token IS NOT NULL
                                THEN 'Cancellation requested; active staging will not be promoted'
                            ELSE 'Cancelled by user'
                        END,
                        lease_owner = CASE WHEN lease_token IS NOT NULL THEN lease_owner ELSE NULL END,
                        lease_token = CASE WHEN lease_token IS NOT NULL THEN lease_token ELSE NULL END,
                        lease_expires_at = CASE WHEN lease_token IS NOT NULL THEN lease_expires_at ELSE NULL END,
                        heartbeat_at = CASE WHEN lease_token IS NOT NULL THEN heartbeat_at ELSE NULL END,
                        completed_at = CASE WHEN lease_token IS NOT NULL THEN completed_at ELSE now() END
                    WHERE job_id = :job_id
                      AND status NOT IN ('promoting', 'completed', 'failed', 'cancelled')
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def pause_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Pause queued work immediately or fence active work after its I/O ends."""
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET pause_requested = true,
                        status = CASE WHEN lease_token IS NOT NULL THEN 'pause_requested' ELSE 'paused' END,
                        message = CASE WHEN lease_token IS NOT NULL
                            THEN 'Pause requested; active staging will not be promoted'
                            ELSE 'Paused before execution' END
                    WHERE job_id = :job_id
                      AND status IN ('queued', 'running')
                      AND cancel_requested = false
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def resume_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Resume only fully paused work, never a still-leased pause request."""
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET pause_requested = false,
                        status = 'queued',
                        message = 'Resumed and waiting for execution slot',
                        available_at = now(),
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status = 'paused'
                      AND lease_token IS NULL
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def claim_expired_promotion_for_recovery(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> Optional[dict[str, Any]]:
        """Claim one interrupted promotion without losing receipt identity.

        ``publication_source_lease_token`` is evidence identity only. Recovery
        execution authority rotates through ``lease_token`` and can be released
        independently without changing which staging receipt must be reconciled.
        """
        recovery_token = str(uuid.uuid4())
        async with async_transaction_scope() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _MODEL_DOWNLOAD_CLAIM_LOCK},
            )
            if not await _global_capacity_available(session):
                return None
            result = await session.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT
                            job_id,
                            COALESCE(publication_source_lease_token, lease_token) AS source_lease_token
                        FROM public.model_download_jobs
                        WHERE status = 'promoting'
                          AND (
                              (
                                  publication_source_lease_token IS NULL
                                  AND lease_token IS NOT NULL
                                  AND lease_expires_at <= clock_timestamp()
                              )
                              OR (
                                  publication_source_lease_token IS NOT NULL
                                  AND available_at <= clock_timestamp()
                                  AND (
                                      lease_token IS NULL
                                      OR lease_expires_at <= clock_timestamp()
                                  )
                              )
                          )
                        ORDER BY updated_at ASC, job_id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE public.model_download_jobs AS jobs
                    SET publication_source_lease_token = candidate.source_lease_token,
                        lease_owner = :worker_id,
                        lease_token = CAST(:recovery_token AS uuid),
                        lease_expires_at = clock_timestamp() + :lease_seconds * interval '1 second',
                        heartbeat_at = clock_timestamp(),
                        message = 'Recovering interrupted publication'
                    FROM candidate
                    WHERE jobs.job_id = candidate.job_id
                    RETURNING jobs.*, jobs.publication_source_lease_token::text AS interrupted_lease_token
                    """
                ),
                {
                    "worker_id": worker_id,
                    "recovery_token": recovery_token,
                    "lease_seconds": lease_seconds,
                },
            )
            return _mapping(result.mappings().first())

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        retry_base_seconds: int,
    ) -> Optional[dict[str, Any]]:
        lease_token = str(uuid.uuid4())
        async with async_transaction_scope() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _MODEL_DOWNLOAD_CLAIM_LOCK},
            )
            # ``promoting`` is intentionally excluded. An expired promotion may
            # already have filesystem/registry side effects and must be claimed
            # by the recovery lane before durable state can return to the queue.
            await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = CASE
                            WHEN cancel_requested THEN 'cancelled'
                            WHEN pause_requested THEN 'paused'
                            WHEN attempt_count >= max_attempts THEN 'failed'
                            ELSE 'queued'
                        END,
                        message = CASE
                            WHEN cancel_requested THEN 'Cancelled after worker lease expired'
                            WHEN pause_requested THEN 'Paused after worker lease expired'
                            WHEN attempt_count >= max_attempts
                                THEN 'Download failed after maximum retry attempts'
                            ELSE 'Lease expired; queued for retry'
                        END,
                        error = CASE
                            WHEN cancel_requested OR pause_requested THEN error
                            ELSE COALESCE(error, 'Worker lease expired')
                        END,
                        available_at = CASE
                            WHEN cancel_requested OR pause_requested OR attempt_count >= max_attempts
                                THEN available_at
                            ELSE now() + (:retry_base_seconds * GREATEST(attempt_count, 1)) * interval '1 second'
                        END,
                        dead_lettered_at = CASE
                            WHEN cancel_requested OR pause_requested THEN NULL
                            WHEN attempt_count >= max_attempts THEN now()
                            ELSE dead_lettered_at
                        END,
                        completed_at = CASE
                            WHEN cancel_requested THEN now()
                            WHEN pause_requested THEN NULL
                            WHEN attempt_count >= max_attempts THEN now()
                            ELSE NULL
                        END,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL
                    WHERE status IN ('running', 'pause_requested')
                      AND lease_token IS NOT NULL
                      AND lease_expires_at <= clock_timestamp()
                    """
                ),
                {"retry_base_seconds": retry_base_seconds},
            )
            if not await _global_capacity_available(session):
                return None

            result = await session.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT jobs.job_id, jobs.install_path
                        FROM public.model_download_jobs AS jobs
                        WHERE jobs.status = 'queued'
                          AND jobs.cancel_requested = false
                          AND jobs.pause_requested = false
                          AND jobs.available_at <= now()
                          AND (
                              jobs.install_path IS NULL
                              OR NOT EXISTS (
                                  SELECT 1
                                  FROM public.model_download_jobs AS blocker
                                  WHERE blocker.job_id <> jobs.job_id
                                    AND blocker.install_path = jobs.install_path
                                    AND (
                                        blocker.status = 'promoting'
                                        OR (
                                            blocker.status IN ('running', 'pause_requested')
                                            AND blocker.lease_token IS NOT NULL
                                            AND blocker.lease_expires_at > clock_timestamp()
                                        )
                                        OR (
                                            blocker.status IN ('queued', 'paused')
                                            AND blocker.lease_token IS NULL
                                            AND (
                                                blocker.created_at < jobs.created_at
                                                OR (
                                                    blocker.created_at = jobs.created_at
                                                    AND blocker.job_id < jobs.job_id
                                                )
                                            )
                                        )
                                    )
                              )
                          )
                        ORDER BY jobs.created_at ASC, jobs.job_id ASC
                        FOR UPDATE OF jobs SKIP LOCKED
                        LIMIT 1
                    ),
                    superseded AS (
                        UPDATE public.model_download_jobs AS duplicate
                        SET status = 'cancelled',
                            cancel_requested = true,
                            pause_requested = false,
                            message = 'Superseded by canonical job for the same install target',
                            completed_at = now(),
                            lease_owner = NULL,
                            lease_token = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = NULL
                        FROM candidate
                        WHERE candidate.install_path IS NOT NULL
                          AND duplicate.install_path = candidate.install_path
                          AND duplicate.job_id <> candidate.job_id
                          AND duplicate.status IN ('queued', 'paused')
                          AND duplicate.lease_token IS NULL
                        RETURNING duplicate.job_id
                    )
                    UPDATE public.model_download_jobs AS jobs
                    SET status = 'running',
                        message = 'Downloading',
                        attempt_count = jobs.attempt_count + 1,
                        lease_owner = :worker_id,
                        lease_token = CAST(:lease_token AS uuid),
                        lease_expires_at = now() + :lease_seconds * interval '1 second',
                        heartbeat_at = now(),
                        started_at = now(),
                        error = NULL
                    FROM candidate
                    WHERE jobs.job_id = candidate.job_id
                    RETURNING jobs.*
                    """
                ),
                {
                    "worker_id": worker_id,
                    "lease_token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
            return _mapping(result.mappings().first())

    async def heartbeat(self, *, job_id: str, lease_token: str, lease_seconds: int) -> bool:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET heartbeat_at = now(),
                        lease_expires_at = now() + :lease_seconds * interval '1 second'
                    WHERE job_id = :job_id
                      AND status IN ('running', 'promoting', 'pause_requested')
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    RETURNING job_id
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token, "lease_seconds": lease_seconds},
            )
            return result.first() is not None

    async def lease_is_valid(self, *, job_id: str, lease_token: str) -> bool:
        """Finalize requested states or atomically reserve one target for promotion.

        The target-scoped advisory lock is the final filesystem-mutation fence.
        Even if legacy data already contains two valid leases for one target,
        exactly one holder can transition to ``promoting``. A later holder is
        durably cancelled before shared artifacts or registry state are touched.
        """
        async with async_transaction_scope() as session:
            requested = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = CASE WHEN cancel_requested THEN 'cancelled' ELSE 'paused' END,
                        message = CASE WHEN cancel_requested
                            THEN 'Cancelled after active staging stopped'
                            ELSE 'Paused after active staging stopped' END,
                        completed_at = CASE WHEN cancel_requested THEN now() ELSE NULL END,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status IN ('running', 'pause_requested')
                      AND (cancel_requested = true OR pause_requested = true)
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    RETURNING status
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token},
            )
            if requested.first() is not None:
                return False

            current_result = await session.execute(
                text(
                    """
                    SELECT install_path, created_at
                    FROM public.model_download_jobs
                    WHERE job_id = :job_id
                      AND status = 'running'
                      AND cancel_requested = false
                      AND pause_requested = false
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token},
            )
            current = current_result.mappings().first()
            if current is None:
                return False

            install_path = str(current.get("install_path") or "").strip() or None
            await _lock_install_target(session, install_path)
            if install_path is not None:
                fenced = await session.execute(
                    text(
                        """
                        UPDATE public.model_download_jobs AS jobs
                        SET status = 'cancelled',
                            cancel_requested = true,
                            message = 'Superseded before promotion by canonical install-target owner',
                            completed_at = now(),
                            lease_owner = NULL,
                            lease_token = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = NULL
                        WHERE jobs.job_id = :job_id
                          AND jobs.status = 'running'
                          AND jobs.cancel_requested = false
                          AND jobs.pause_requested = false
                          AND jobs.lease_token = CAST(:lease_token AS uuid)
                          AND jobs.lease_expires_at > now()
                          AND EXISTS (
                              SELECT 1
                              FROM public.model_download_jobs AS sibling
                              WHERE sibling.job_id <> jobs.job_id
                                AND sibling.install_path = jobs.install_path
                                AND (
                                    (
                                        sibling.status = 'promoting'
                                        AND sibling.lease_token IS NOT NULL
                                        AND sibling.lease_expires_at > now()
                                    )
                                    OR (
                                        sibling.status = 'completed'
                                        AND sibling.completed_at IS NOT NULL
                                        AND sibling.completed_at >= jobs.created_at
                                    )
                                )
                          )
                        RETURNING jobs.job_id
                        """
                    ),
                    {"job_id": job_id, "lease_token": lease_token},
                )
                if fenced.first() is not None:
                    return False

            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = 'promoting',
                        message = 'Promoting staged artifacts',
                        heartbeat_at = now()
                    WHERE job_id = :job_id
                      AND status = 'running'
                      AND cancel_requested = false
                      AND pause_requested = false
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    RETURNING job_id
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token},
            )
            return result.first() is not None

    @asynccontextmanager
    async def publication_guard(
        self,
        *,
        job_id: str,
        lease_token: str,
        install_path: str,
    ) -> AsyncIterator[Optional[_ModelDownloadPublication]]:
        """Hold durable ownership across final filesystem and registry publication.

        Publication authority must still have a live lease after this transaction
        wins the target and job-row locks. That wall-clock check happens only after
        the row is held so time spent waiting for either lock cannot resurrect an
        expired worker. Once validated, the short irreversible publication window
        remains owned by this transaction even if the lease later reaches its
        deadline; reclaim stays blocked until terminal durable state commits.
        """
        async with async_transaction_scope() as session:
            await _lock_install_target(session, install_path)
            result = await session.execute(
                text(
                    """
                    SELECT job_id
                    FROM public.model_download_jobs
                    WHERE job_id = :job_id
                      AND install_path = :install_path
                      AND status = 'promoting'
                      AND cancel_requested = false
                      AND pause_requested = false
                      AND lease_token = CAST(:lease_token AS uuid)
                    FOR UPDATE
                    """
                ),
                {
                    "job_id": job_id,
                    "lease_token": lease_token,
                    "install_path": install_path,
                },
            )
            if result.first() is None:
                yield None
                return

            lease_live_result = await session.execute(
                text(
                    """
                    SELECT lease_expires_at > clock_timestamp()
                    FROM public.model_download_jobs
                    WHERE job_id = :job_id
                      AND lease_token = CAST(:lease_token AS uuid)
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token},
            )
            if lease_live_result.scalar_one_or_none() is not True:
                yield None
                return

            yield _ModelDownloadPublication(
                session=session,
                job_id=job_id,
                lease_token=lease_token,
                install_path=install_path,
            )

    async def complete_job(
        self,
        *,
        job_id: str,
        lease_token: str,
        result_payload: Mapping[str, Any],
        install_path: str,
    ) -> Optional[dict[str, Any]]:
        """Compatibility completion path using the same publication transaction."""
        async with self.publication_guard(
            job_id=job_id,
            lease_token=lease_token,
            install_path=install_path,
        ) as publication:
            if publication is None:
                return None
            return await publication.complete(result_payload)

    async def release_publication_for_recovery(
        self,
        *,
        job_id: str,
        lease_token: str,
        error: str,
    ) -> bool:
        """Separate receipt identity from execution authority after uncertainty."""
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET publication_source_lease_token = COALESCE(
                            publication_source_lease_token,
                            lease_token
                        ),
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        available_at = clock_timestamp(),
                        message = 'Publication interrupted; awaiting recovery',
                        error = :error
                    WHERE job_id = :job_id
                      AND status = 'promoting'
                      AND lease_token = CAST(:lease_token AS uuid)
                    RETURNING job_id
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token, "error": error},
            )
            return result.first() is not None

    async def defer_publication_recovery_retry(
        self,
        *,
        job_id: str,
        lease_token: str,
        error: str,
        retry_base_seconds: int,
    ) -> bool:
        """Release one failed recovery lease while preserving receipt identity."""
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        available_at = clock_timestamp()
                            + GREATEST(:retry_base_seconds, 1) * interval '1 second',
                        message = 'Publication recovery deferred; retry scheduled',
                        error = :error
                    WHERE job_id = :job_id
                      AND status = 'promoting'
                      AND publication_source_lease_token IS NOT NULL
                      AND lease_token = CAST(:lease_token AS uuid)
                    RETURNING job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "lease_token": lease_token,
                    "error": error,
                    "retry_base_seconds": retry_base_seconds,
                },
            )
            return result.first() is not None

    async def fail_or_retry(
        self,
        *,
        job_id: str,
        lease_token: str,
        error: str,
        retry_base_seconds: int,
    ) -> Optional[dict[str, Any]]:
        async with async_transaction_scope() as session:
            return await _fail_or_retry_in_session(
                session,
                job_id=job_id,
                lease_token=lease_token,
                error=error,
                retry_base_seconds=retry_base_seconds,
            )

    async def release_for_shutdown(
        self,
        *,
        job_id: str,
        lease_token: str,
        retry_delay_seconds: int = 0,
    ) -> bool:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = CASE
                            WHEN cancel_requested THEN 'cancelled'
                            WHEN pause_requested THEN 'paused'
                            ELSE 'queued'
                        END,
                        message = CASE
                            WHEN cancel_requested THEN 'Cancelled while worker stopped'
                            WHEN pause_requested THEN 'Paused while worker stopped'
                            ELSE 'Worker stopped; queued for retry'
                        END,
                        available_at = CASE
                            WHEN cancel_requested OR pause_requested THEN available_at
                            ELSE now() + :retry_delay_seconds * interval '1 second'
                        END,
                        completed_at = CASE WHEN cancel_requested THEN now() ELSE completed_at END,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status IN ('running', 'pause_requested')
                      AND lease_token = CAST(:lease_token AS uuid)
                    RETURNING job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "lease_token": lease_token,
                    "retry_delay_seconds": retry_delay_seconds,
                },
            )
            return result.first() is not None

    async def cleanup_finished_jobs(self, *, max_age_seconds: int) -> int:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM public.model_download_jobs
                    WHERE status IN ('completed', 'failed', 'cancelled')
                      AND updated_at < now() - :max_age_seconds * interval '1 second'
                    RETURNING job_id
                    """
                ),
                {"max_age_seconds": max_age_seconds},
            )
            return len(result.all())

    async def import_legacy_jobs(
        self,
        jobs: Sequence[Mapping[str, Any]],
        *,
        max_attempts: int,
    ) -> int:
        if not jobs:
            return 0
        inserted = 0
        async with async_transaction_scope() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _MODEL_DOWNLOAD_IMPORT_LOCK},
            )
            for source in jobs:
                old_status = str(source.get("status") or "queued")
                if old_status == "running":
                    status = "queued"
                    message = "Recovered from legacy running job; queued after restart"
                elif old_status == "pause_requested":
                    status = "paused"
                    message = "Recovered from legacy pause request"
                elif old_status in {"queued", "paused", "completed", "failed", "cancelled"}:
                    status = old_status
                    message = str(source.get("message") or "Imported from legacy state")
                else:
                    status = "queued"
                    message = "Recovered from unknown legacy state; queued"
                result = await session.execute(
                    text(
                        """
                        INSERT INTO public.model_download_jobs (
                            job_id, model_id, revision, channel_id, storage_key, status,
                            progress, message, error, result, created_at, updated_at,
                            requested_by, trust_remote_code, license_accepted,
                            include_patterns, exclude_patterns, pin, force_redownload,
                            pause_requested, cancel_requested, warnings, detected_runtime,
                            detected_modality, install_path, max_attempts, legacy_imported_at,
                            completed_at
                        ) VALUES (
                            :job_id, :model_id, :revision, :channel_id, :storage_key, :status,
                            :progress, :message, :error, CAST(:result_payload AS jsonb),
                            CAST(:created_at AS timestamptz), CAST(:updated_at AS timestamptz),
                            :requested_by, :trust_remote_code, :license_accepted,
                            CAST(:include_patterns AS jsonb), CAST(:exclude_patterns AS jsonb),
                            :pin, :force_redownload, :pause_requested, :cancel_requested,
                            CAST(:warnings AS jsonb), :detected_runtime, :detected_modality,
                            :install_path, :max_attempts, now(),
                            CASE WHEN :status IN ('completed', 'failed', 'cancelled')
                                THEN CAST(:updated_at AS timestamptz) ELSE NULL END
                        )
                        ON CONFLICT (job_id) DO NOTHING
                        RETURNING job_id
                        """
                    ),
                    {
                        "job_id": source["job_id"],
                        "model_id": source["model_id"],
                        "revision": source.get("revision"),
                        "channel_id": source.get("channel_id") or "core_runtime_transformers",
                        "storage_key": source.get("storage_key") or source.get("library_override"),
                        "status": status,
                        "progress": float(source.get("progress") or 0.0),
                        "message": message,
                        "error": source.get("error"),
                        "result_payload": _json(source.get("result")),
                        "created_at": source.get("created_at") or datetime.now(timezone.utc).isoformat(),
                        "updated_at": source.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                        "requested_by": source.get("requested_by"),
                        "trust_remote_code": bool(source.get("trust_remote_code", False)),
                        "license_accepted": bool(source.get("license_accepted", False)),
                        "include_patterns": _json(source.get("include_patterns")),
                        "exclude_patterns": _json(source.get("exclude_patterns")),
                        "pin": bool(source.get("pin", False)),
                        "force_redownload": bool(source.get("force_redownload", False)),
                        "pause_requested": status == "paused" or bool(source.get("pause_requested", False)),
                        "cancel_requested": bool(source.get("cancel_requested", False)),
                        "warnings": _json(list(source.get("warnings") or [])),
                        "detected_runtime": source.get("detected_runtime"),
                        "detected_modality": source.get("detected_modality"),
                        "install_path": source.get("install_path"),
                        "max_attempts": max_attempts,
                    },
                )
                if result.first() is not None:
                    inserted += 1
        return inserted


__all__ = ["ModelDownloadRepository"]