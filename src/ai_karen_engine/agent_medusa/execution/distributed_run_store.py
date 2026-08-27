"""Shared coordination metadata for Agent Medusa execution runs.

This module deliberately reuses KAREN's canonical Redis connection manager. It
never uses the manager's process-local degraded cache because local fallback
cannot provide truthful cluster leases or remote cancellation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings
from ai_karen_engine.platform.memory.redis import (
    RedisConnectionManager,
    get_redis_manager,
)


class DistributedRunStoreUnavailable(RuntimeError):
    """Raised when shared coordination is not currently authoritative."""


class DistributedRunNotFound(LookupError):
    """Raised when a shared run record does not exist."""


class DistributedRunTenantMismatch(PermissionError):
    """Raised when a shared run is accessed from another tenant."""


class DistributedRunNotCancellable(RuntimeError):
    """Raised when a shared run cannot accept a cancellation request."""


class DistributedRunStore(Protocol):
    """Storage contract used by the Medusa run manager."""

    async def available(self) -> bool: ...

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> None: ...

    async def heartbeat(self, *, run_id: str, worker_id: str) -> bool: ...

    async def mark_terminal(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None: ...

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]: ...

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]: ...

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
    ) -> list[dict[str, Any]]: ...


class RedisDistributedRunStore:
    """Strict Redis-backed lease and cancellation metadata store."""

    _ACTIVE = {"running", "cancelling"}

    def __init__(
        self,
        *,
        settings: AgentMedusaRuntimeSettings,
        redis_manager: RedisConnectionManager | None = None,
    ) -> None:
        self._settings = settings
        self._redis = redis_manager or get_redis_manager()

    async def available(self) -> bool:
        if not self._settings.distributed_run_control_enabled:
            return False
        if self._redis.is_degraded() or self._redis.client is None:
            return False
        try:
            return bool(await self._redis.client.ping())
        except Exception:
            return False

    def _run_key(self, run_id: str) -> str:
        return f"{self._settings.run_key_prefix}:run:{run_id}"

    def _claim_key(self, run_id: str) -> str:
        return f"{self._settings.run_key_prefix}:claim:{run_id}"

    def _tenant_index(self, tenant_id: str) -> str:
        return f"{self._settings.run_key_prefix}:tenant:{tenant_id}"

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _iso(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    def _parse_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    async def _client(self):
        if not await self.available():
            raise DistributedRunStoreUnavailable("shared_redis_unavailable")
        client = self._redis.client
        if client is None:
            raise DistributedRunStoreUnavailable("shared_redis_unavailable")
        return client

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> None:
        client = await self._client()
        claim_key = self._claim_key(run_id)
        claimed = await client.set(
            claim_key,
            worker_id,
            nx=True,
            ex=self._settings.run_lease_ttl_seconds,
        )
        if not claimed:
            raise RuntimeError(f"Medusa distributed run already active: {run_id}")

        now = self._now()
        lease_expires = now + timedelta(seconds=self._settings.run_lease_ttl_seconds)
        key = self._run_key(run_id)
        mapping = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "owner_worker_id": worker_id,
            "status": "running",
            "started_at": self._iso(started_at),
            "updated_at": self._iso(now),
            "heartbeat_at": self._iso(now),
            "lease_expires_at": self._iso(lease_expires),
            "cancel_requested_at": "",
            "completed_at": "",
            "error_type": "",
        }
        try:
            pipeline = client.pipeline(transaction=True)
            pipeline.hset(key, mapping=mapping)
            pipeline.expire(key, self._settings.run_terminal_retention_seconds)
            pipeline.sadd(self._tenant_index(tenant_id), run_id)
            pipeline.expire(
                self._tenant_index(tenant_id),
                self._settings.run_terminal_retention_seconds,
            )
            await pipeline.execute()
        except Exception:
            owner = await client.get(claim_key)
            if owner == worker_id:
                await client.delete(claim_key)
            raise

    async def heartbeat(self, *, run_id: str, worker_id: str) -> bool:
        client = await self._client()
        claim_key = self._claim_key(run_id)
        owner = await client.get(claim_key)
        if owner != worker_id:
            raise RuntimeError(f"Medusa run ownership changed or expired: {run_id}")

        key = self._run_key(run_id)
        record = await client.hgetall(key)
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("owner_worker_id") != worker_id:
            raise RuntimeError(f"Medusa run ownership changed: {run_id}")
        if record.get("status") not in self._ACTIVE:
            return False

        now = self._now()
        lease_expires = now + timedelta(seconds=self._settings.run_lease_ttl_seconds)
        pipeline = client.pipeline(transaction=True)
        pipeline.expire(claim_key, self._settings.run_lease_ttl_seconds)
        pipeline.hset(
            key,
            mapping={
                "updated_at": self._iso(now),
                "heartbeat_at": self._iso(now),
                "lease_expires_at": self._iso(lease_expires),
            },
        )
        pipeline.expire(key, self._settings.run_terminal_retention_seconds)
        await pipeline.execute()
        return bool(record.get("cancel_requested_at"))

    async def mark_terminal(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None:
        client = await self._client()
        key = self._run_key(run_id)
        record = await client.hgetall(key)
        if not record:
            return
        if record.get("owner_worker_id") != worker_id:
            raise RuntimeError(f"Medusa run ownership changed: {run_id}")

        pipeline = client.pipeline(transaction=True)
        pipeline.hset(
            key,
            mapping={
                "status": status,
                "updated_at": self._iso(completed_at),
                "completed_at": self._iso(completed_at),
                "error_type": error_type or "",
                "lease_expires_at": "",
            },
        )
        pipeline.expire(key, self._settings.run_terminal_retention_seconds)
        await pipeline.execute()

        claim_key = self._claim_key(run_id)
        owner = await client.get(claim_key)
        if owner == worker_id:
            await client.delete(claim_key)

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        client = await self._client()
        key = self._run_key(run_id)
        record = await client.hgetall(key)
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("tenant_id") != tenant_id:
            raise DistributedRunTenantMismatch(run_id)

        snapshot = self._snapshot(record)
        if not snapshot["cancellable"]:
            raise DistributedRunNotCancellable(
                f"Run {run_id} is {snapshot['status']}, not cancellable"
            )
        now = self._now()
        await client.hset(
            key,
            mapping={
                "status": "cancelling",
                "cancel_requested_at": self._iso(now),
                "updated_at": self._iso(now),
            },
        )
        record.update(
            {
                "status": "cancelling",
                "cancel_requested_at": self._iso(now),
                "updated_at": self._iso(now),
            }
        )
        return self._snapshot(record)

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        client = await self._client()
        record = await client.hgetall(self._run_key(run_id))
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("tenant_id") != tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        return self._snapshot(record)

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
    ) -> list[dict[str, Any]]:
        client = await self._client()
        index_key = self._tenant_index(tenant_id)
        run_ids = await client.smembers(index_key)
        snapshots: list[dict[str, Any]] = []
        stale: list[str] = []
        for run_id in run_ids:
            normalized_run_id = str(run_id)
            record = await client.hgetall(self._run_key(normalized_run_id))
            if not record:
                stale.append(normalized_run_id)
                continue
            snapshot = self._snapshot(record)
            if include_terminal or snapshot["status"] in {
                "running",
                "cancelling",
                "orphaned",
            }:
                snapshots.append(snapshot)
        if stale:
            await client.srem(index_key, *stale)
        return sorted(snapshots, key=lambda item: item["started_at"] or "", reverse=True)

    def _snapshot(self, record: dict[str, str]) -> dict[str, Any]:
        now = self._now()
        status = record.get("status", "failed")
        lease_expires = self._parse_time(record.get("lease_expires_at"))
        lease_alive = bool(lease_expires and lease_expires > now)
        if status in self._ACTIVE and not lease_alive:
            status = "orphaned"
        return {
            "run_id": record.get("run_id", ""),
            "correlation_id": record.get("correlation_id", ""),
            "tenant_id": record.get("tenant_id", ""),
            "user_id": record.get("user_id", ""),
            "status": status,
            "started_at": record.get("started_at") or None,
            "completed_at": record.get("completed_at") or None,
            "error_type": record.get("error_type") or None,
            "cancellable": status == "running" and lease_alive,
            "distributed_control": {
                "supported": True,
                "lease_alive": lease_alive,
            },
        }


__all__ = [
    "DistributedRunNotCancellable",
    "DistributedRunNotFound",
    "DistributedRunStore",
    "DistributedRunStoreUnavailable",
    "DistributedRunTenantMismatch",
    "RedisDistributedRunStore",
]
