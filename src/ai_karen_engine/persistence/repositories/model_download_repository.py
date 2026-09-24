"""PostgreSQL lifecycle authority for model-download jobs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

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


class ModelDownloadRepository:
    """Own durable job state, runtime cap, and lease fencing for model downloads."""

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
            result = await session.execute(statement, params)
            return dict(result.mappings().one())

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
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET cancel_requested = true,
                        status = 'cancelled',
                        message = 'Cancelled by user',
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        completed_at = now()
                    WHERE job_id = :job_id
                      AND status NOT IN ('promoting', 'completed', 'failed', 'cancelled')
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def pause_job(self, job_id: str) -> Optional[dict[str, Any]]:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET pause_requested = true,
                        status = CASE WHEN status = 'running' THEN 'pause_requested' ELSE 'paused' END,
                        message = CASE WHEN status = 'running'
                            THEN 'Pause requested; active staging will not be promoted'
                            ELSE 'Paused before execution' END,
                        lease_owner = CASE WHEN status = 'running' THEN NULL ELSE lease_owner END,
                        lease_token = CASE WHEN status = 'running' THEN NULL ELSE lease_token END,
                        lease_expires_at = CASE WHEN status = 'running' THEN NULL ELSE lease_expires_at END,
                        heartbeat_at = CASE WHEN status = 'running' THEN NULL ELSE heartbeat_at END
                    WHERE job_id = :job_id
                      AND status NOT IN ('promoting', 'completed', 'failed', 'cancelled', 'paused', 'pause_requested')
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
            )
            return _mapping(result.mappings().first())

    async def resume_job(self, job_id: str) -> Optional[dict[str, Any]]:
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
                      AND status IN ('paused', 'pause_requested')
                    RETURNING *
                    """
                ),
                {"job_id": job_id},
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
            await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'queued' END,
                        message = CASE WHEN attempt_count >= max_attempts
                            THEN 'Download failed after maximum retry attempts'
                            ELSE 'Lease expired; queued for retry' END,
                        error = COALESCE(error, 'Worker lease expired'),
                        available_at = CASE WHEN attempt_count >= max_attempts
                            THEN available_at
                            ELSE now() + (:retry_base_seconds * GREATEST(attempt_count, 1)) * interval '1 second' END,
                        dead_lettered_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE dead_lettered_at END,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL
                    WHERE status IN ('running', 'promoting')
                      AND lease_token IS NOT NULL
                      AND lease_expires_at <= now()
                    """
                ),
                {"retry_base_seconds": retry_base_seconds},
            )
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
                    WHERE status IN ('running', 'promoting')
                      AND lease_token IS NOT NULL
                      AND lease_expires_at > now()
                    """
                )
            )
            if int(active_result.scalar_one()) >= int(global_concurrency):
                return None

            result = await session.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT job_id
                        FROM public.model_download_jobs
                        WHERE status = 'queued'
                          AND cancel_requested = false
                          AND pause_requested = false
                          AND available_at <= now()
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
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
                      AND status IN ('running', 'promoting')
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    RETURNING job_id
                    """
                ),
                {"job_id": job_id, "lease_token": lease_token, "lease_seconds": lease_seconds},
            )
            return result.first() is not None

    async def lease_is_valid(self, *, job_id: str, lease_token: str) -> bool:
        """Atomically reserve promotion for the current valid lease.

        The state transition closes the check-then-promote race: once a lease
        holder moves from ``running`` to ``promoting``, cancel/pause mutations
        are fenced out until completion, failure, or expiry.
        """
        async with async_transaction_scope() as session:
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

    async def complete_job(
        self,
        *,
        job_id: str,
        lease_token: str,
        result_payload: Mapping[str, Any],
        install_path: str,
    ) -> Optional[dict[str, Any]]:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = 'completed', progress = 1.0,
                        message = 'Download completed', error = NULL,
                        result = CAST(:result_payload AS jsonb), install_path = :install_path,
                        completed_at = now(), lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status = 'promoting'
                      AND cancel_requested = false
                      AND pause_requested = false
                      AND lease_token = CAST(:lease_token AS uuid)
                      AND lease_expires_at > now()
                    RETURNING *
                    """
                ),
                {
                    "job_id": job_id,
                    "lease_token": lease_token,
                    "result_payload": _json(dict(result_payload)),
                    "install_path": install_path,
                },
            )
            return _mapping(result.mappings().first())

    async def fail_or_retry(
        self,
        *,
        job_id: str,
        lease_token: str,
        error: str,
        retry_base_seconds: int,
    ) -> Optional[dict[str, Any]]:
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.model_download_jobs
                    SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'queued' END,
                        message = CASE WHEN attempt_count >= max_attempts
                            THEN 'Download failed after maximum retry attempts'
                            ELSE 'Download failed; queued for retry' END,
                        error = :error,
                        available_at = CASE WHEN attempt_count >= max_attempts
                            THEN available_at
                            ELSE now() + (:retry_base_seconds * GREATEST(attempt_count, 1)) * interval '1 second' END,
                        dead_lettered_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE NULL END,
                        completed_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE NULL END,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status IN ('running', 'promoting')
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
                    SET status = 'queued', message = 'Worker stopped; queued for retry',
                        available_at = now() + :retry_delay_seconds * interval '1 second',
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = :job_id
                      AND status = 'running'
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
