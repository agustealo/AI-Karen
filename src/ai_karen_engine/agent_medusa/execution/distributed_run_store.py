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

# Claim and publish the run identity in one Redis operation. A lost or
# retired lease does not make an existing run identity reusable.
_REGISTER_RUN_SCRIPT = """
if redis.call('EXISTS', KEYS[1], KEYS[2]) ~= 0 then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
redis.call('HSET', KEYS[2], unpack(ARGV, 5))
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
redis.call('SADD', KEYS[3], ARGV[4])
redis.call('EXPIRE', KEYS[3], tonumber(ARGV[3]))
return 1
"""

# Recheck the claim and immutable run identity in the same operation as
# renewal. A delayed heartbeat must never recreate or modify a retired run.
_HEARTBEAT_RUN_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return -1
end
if redis.call('EXISTS', KEYS[2]) == 0 then
  return -2
end
if redis.call('HGET', KEYS[2], 'owner_worker_id') ~= ARGV[1]
    or redis.call('HGET', KEYS[2], 'tenant_id') ~= ARGV[2]
    or redis.call('HGET', KEYS[2], 'run_id') ~= ARGV[3] then
  return -1
end
local status = redis.call('HGET', KEYS[2], 'status')
if status ~= 'running' and status ~= 'cancelling' then
  return -1
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
redis.call('HSET', KEYS[2],
  'updated_at', ARGV[6],
  'heartbeat_at', ARGV[6],
  'lease_expires_at', ARGV[7])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
redis.call('EXPIRE', KEYS[3], tonumber(ARGV[5]))
local cancel = redis.call('HGET', KEYS[2], 'cancel_requested_at')
if cancel and cancel ~= '' then
  return 1
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


class DistributedRunOwnershipLost(RuntimeError):
    """Raised when Redis definitively rejects the worker's live authority."""


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

    async def set_outcome_status(
        self,
        *,
        run_id: str,
        worker_id: str,
        outcome_status: str,
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
            "outcome_status": "",
        }
        claimed = await client.eval(
            _REGISTER_RUN_SCRIPT,
            3,
            claim_key,
            run_key,
            index_key,
            worker_id,
            str(self._settings.run_lease_ttl_seconds),
            str(self._settings.run_terminal_retention_seconds),
            run_id,
            *(value for pair in mapping.items() for value in pair),
        )
        if not claimed:
            raise RuntimeError(f"Medusa distributed run already exists: {run_id}")

    async def heartbeat(self, *, run_id: str, worker_id: str) -> bool:
        client = await self._client()
        run_key = self._run_key(run_id)
        # This read locates the tenant index only. The script repeats all
        # identity, status and claim checks before touching any key.
        record = await client.hgetall(run_key)
        if not record:
            raise DistributedRunNotFound(run_id)
        tenant_id = record.get("tenant_id")
        if not tenant_id:
            raise DistributedRunOwnershipLost(f"Missing Medusa tenant: {run_id}")

        now = self._now()
        lease_expires = now + timedelta(seconds=self._settings.run_lease_ttl_seconds)
        result = int(
            await client.eval(
                _HEARTBEAT_RUN_SCRIPT,
                3,
                self._claim_key(run_id),
                run_key,
                self._tenant_index(tenant_id),
                worker_id,
                tenant_id,
                run_id,
                str(self._settings.run_lease_ttl_seconds),
                str(self._settings.run_terminal_retention_seconds),
                self._iso(now),
                self._iso(lease_expires),
            )
        )
        if result == -2:
            raise DistributedRunNotFound(run_id)
        if result == -1:
            raise DistributedRunOwnershipLost(
                f"Medusa run ownership changed or expired: {run_id}"
            )
        if result not in {0, 1}:
            raise DistributedRunStoreUnavailable("invalid_heartbeat_result")
        return result == 1

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

    async def set_outcome_status(
        self,
        *,
        run_id: str,
        worker_id: str,
        outcome_status: str,
    ) -> None:
        """Attach task outcome to the retained shared run receipt."""

        normalized = str(outcome_status or "").strip().lower()
        if normalized not in {
            "success",
            "partial",
            "degraded",
            "error",
            "timeout",
            "cancelled",
        }:
            raise ValueError(f"Invalid Medusa outcome status: {outcome_status}")
        client = await self._client()
        run_key = self._run_key(run_id)
        record = await client.hgetall(run_key)
        if not record:
            raise DistributedRunNotFound(run_id)
        if record.get("owner_worker_id") != worker_id:
            raise RuntimeError(f"Medusa run ownership metadata changed: {run_id}")
        await client.hset(run_key, mapping={"outcome_status": normalized})

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
            "outcome_status": record.get("outcome_status") or None,
            "cancellable": status == "running" and lease_alive,
            "distributed_control": {
                "supported": True,
                "lease_alive": lease_alive,
            },
        }


__all__ = [
    "DistributedRunNotCancellable",
    "DistributedRunNotFound",
    "DistributedRunOwnershipLost",
    "DistributedRunStore",
    "DistributedRunStoreUnavailable",
    "DistributedRunTenantMismatch",
    "RedisDistributedRunStore",
]
