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

_RENEW_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""

_RELEASE_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_CANCEL_RUN_SCRIPT = """
local owner = redis.call('GET', KEYS[1])
if not owner then
  return -1
end
if redis.call('HGET', KEYS[2], 'owner_worker_id') ~= owner then
  return -1
end
if redis.call('HGET', KEYS[2], 'tenant_id') ~= ARGV[1] then
  return -2
end
if redis.call('HGET', KEYS[2], 'status') ~= 'running' then
  return -3
end
redis.call('HSET', KEYS[2],
  'status', 'cancelling',
  'cancel_requested_at', ARGV[2],
  'updated_at', ARGV[2])
return 1
"""

_MARK_TERMINAL_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return 0
end
if redis.call('HGET', KEYS[2], 'owner_worker_id') ~= ARGV[1] then
  return 0
end
redis.call('HSET', KEYS[2],
  'status', ARGV[2],
  'updated_at', ARGV[3],
  'completed_at', ARGV[3],
  'error_type', ARGV[4],
  'lease_expires_at', '')
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
redis.call('DEL', KEYS[1])
return 1
"""


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
        run_key = self._run_key(run_id)
        index_key = self._tenant_index(tenant_id)
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
            pipeline.hset(run_key, mapping=mapping)
            pipeline.expire(run_key, self._settings.run_terminal_retention_seconds)
            pipeline.sadd(index_key, run_id)
            pipeline.expire(index_key, self._settings.run_terminal_retention_seconds)
            await pipeline.execute()
        except Exception:
            await client.eval(_RELEASE_CLAIM_SCRIPT, 1, claim_key, worker_id)
            raise

    async def heartbeat(self, *, run_id: str, worker_id: str) -> bool:
        client = await self._client()
        claim_key = self._claim_key(run_id)
        renewed = await client.eval(
            _RENEW_CLAIM_SCRIPT,
            1,
            claim_key,
            worker_id,
            str(self._settings.run_lease_ttl_seconds),
        )
        if not renewed:
            raise RuntimeError(f"Medusa run ownership changed or expired: {run_id}")

        run_key = self._run_key(run_id)
        record = await client.hgetall(run_key)
        if not record:
            await client.eval(_RELEASE_CLAIM_SCRIPT, 1, claim_key, worker_id)
            raise DistributedRunNotFound(run_id)
        if record.get("owner_worker_id") != worker_id:
            await client.eval(_RELEASE_CLAIM_SCRIPT, 1, claim_key, worker_id)
            raise RuntimeError(f"Medusa run ownership metadata changed: {run_id}")
        if record.get("status") not in self._ACTIVE:
            return False

        now = self._now()
        lease_expires = now + timedelta(seconds=self._settings.run_lease_ttl_seconds)
        index_key = self._tenant_index(str(record.get("tenant_id", "")))
        pipeline = client.pipeline(transaction=True)
        pipeline.hset(
            run_key,
            mapping={
                "updated_at": self._iso(now),
                "heartbeat_at": self._iso(now),
                "lease_expires_at": self._iso(lease_expires),
            },
        )
        pipeline.expire(run_key, self._settings.run_terminal_retention_seconds)
        if record.get("tenant_id"):
            pipeline.expire(index_key, self._settings.run_terminal_retention_seconds)
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
        run_key = self._run_key(run_id)
        record = await client.hgetall(run_key)
        if not record:
            return
        index_key = self._tenant_index(str(record.get("tenant_id", "")))
        result = await client.eval(
            _MARK_TERMINAL_SCRIPT,
            2,
            self._claim_key(run_id),
            run_key,
            worker_id,
            status,
            self._iso(completed_at),
            error_type or "",
            str(self._settings.run_terminal_retention_seconds),
        )
        if not result:
            return
        if record.get("tenant_id"):
            await client.expire(
                index_key,
                self._settings.run_terminal_retention_seconds,
            )

    async def request_cancel(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        client = await self._client()
        run_key = self._run_key(run_id)
        record = await client.hgetall(run_key)
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("tenant_id") != tenant_id:
            raise DistributedRunTenantMismatch(run_id)

        now = self._now()
        result = int(
            await client.eval(
                _CANCEL_RUN_SCRIPT,
                2,
                self._claim_key(run_id),
                run_key,
                tenant_id,
                self._iso(now),
            )
        )
        if result == -2:
            raise DistributedRunTenantMismatch(run_id)
        if result in {-1, -3, 0}:
            refreshed = await client.hgetall(run_key)
            if not refreshed:
                raise DistributedRunNotFound(run_id)
            owner = await client.get(self._claim_key(run_id))
            snapshot = self._snapshot(
                refreshed,
                claim_alive=bool(owner and owner == refreshed.get("owner_worker_id")),
            )
            raise DistributedRunNotCancellable(
                f"Run {run_id} is {snapshot['status']}, not cancellable"
            )

        refreshed = await client.hgetall(run_key)
        owner = await client.get(self._claim_key(run_id))
        return self._snapshot(
            refreshed,
            claim_alive=bool(owner and owner == refreshed.get("owner_worker_id")),
        )

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        client = await self._client()
        record = await client.hgetall(self._run_key(run_id))
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("tenant_id") != tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        owner = await client.get(self._claim_key(run_id))
        return self._snapshot(
            record,
            claim_alive=bool(owner and owner == record.get("owner_worker_id")),
        )

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
            owner = await client.get(self._claim_key(normalized_run_id))
            snapshot = self._snapshot(
                record,
                claim_alive=bool(owner and owner == record.get("owner_worker_id")),
            )
            if include_terminal or snapshot["status"] in {
                "running",
                "cancelling",
                "orphaned",
            }:
                snapshots.append(snapshot)
        if stale:
            await client.srem(index_key, *stale)
        return sorted(
            snapshots,
            key=lambda item: item["started_at"] or "",
            reverse=True,
        )

    def _snapshot(
        self,
        record: dict[str, str],
        *,
        claim_alive: bool,
    ) -> dict[str, Any]:
        now = self._now()
        status = record.get("status", "failed")
        lease_expires = self._parse_time(record.get("lease_expires_at"))
        metadata_lease_alive = bool(lease_expires and lease_expires > now)
        lease_alive = claim_alive and metadata_lease_alive
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
