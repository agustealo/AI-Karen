"""Active Redis readiness checks against the canonical platform manager."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
    RedisConnectionManager,
    RedisDurabilityObservation,
)


@pytest.mark.asyncio
async def test_uninitialized_canonical_redis_manager_cannot_report_healthy() -> None:
    manager = RedisConnectionManager(redis_url="redis://red-private:6379")
    assert manager.is_degraded() is False
    assert manager.health() is False
    assert await manager.is_healthy() is False

    client = type("HealthyClient", (), {"ping": AsyncMock(return_value=True)})()
    manager._client = client
    assert await manager.is_healthy() is True
    client.ping.assert_awaited_once()

    manager._degraded_mode = True
    assert await manager.is_healthy() is False

    manager._degraded_mode = False
    client.ping = AsyncMock(side_effect=ConnectionError("offline"))
    assert await manager.is_healthy() is False


@pytest.mark.asyncio
async def test_redis_health_and_connection_metadata_redact_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "dont-expose-redis-secret-98765"
    url = f"redis://:{secret}@red-private:6379/0"
    manager = RedisConnectionManager(redis_url=url)
    manager._client = type(
        "BrokenClient", (),
        {"ping": AsyncMock(side_effect=ConnectionError(f"{url} unavailable"))},
    )()

    assert await manager.is_healthy() is False
    report = await manager.health_check()
    assert report["healthy"] is False
    assert report["error_type"] == "ConnectionError"
    assert report["connection_info"]["redis_url"] == "[REDACTED]"
    assert secret not in repr(report)
    assert secret not in repr(manager.get_connection_info())

    assert await manager._test_connection() is False
    assert secret not in caplog.text


def _durability_client():
    from types import SimpleNamespace

    return SimpleNamespace(
        info=AsyncMock(
            side_effect=[
                {
                    "maxmemory_policy": "volatile-lru",
                    "maxmemory": 1024,
                    "used_memory": 512,
                    "mem_not_counted_for_evict": 0,
                    "secret_unrelated": "private-value",
                },
                {"aof_enabled": 1, "aof_last_write_status": "ok"},
                {"evicted_keys": 0},
            ]
        ),
        config_get=AsyncMock(return_value={"appendfsync": "always"}),
    )


@pytest.mark.asyncio
async def test_durability_observation_reports_only_allowlisted_live_facts() -> None:
    manager = RedisConnectionManager()
    client = _durability_client()
    manager._client = client
    result = await manager.observe_durability()
    assert asdict(result) == {
        "status": "observed",
        "maxmemory_policy": "volatile-lru",
        "maxmemory_bytes": 1024,
        "used_memory_bytes": 512,
        "mem_not_counted_for_evict_bytes": 0,
        "aof_enabled": True,
        "appendfsync": "always",
        "aof_write_ok": True,
        "evicted_keys": 0,
    }
    assert [call.args for call in client.info.await_args_list] == [
        ("memory",), ("persistence",), ("stats",)
    ]
    client.config_get.assert_awaited_once_with("appendfsync")
    assert "private-value" not in repr(result)


@pytest.mark.asyncio
async def test_durability_observation_preserves_denied_configuration_as_unknown() -> None:
    from redis.exceptions import ResponseError

    manager = RedisConnectionManager()
    client = _durability_client()
    client.config_get.side_effect = ResponseError("private ACL diagnostic")
    manager._client = client
    result = await manager.observe_durability()
    assert result.status == "partial"
    assert result.aof_enabled is True
    assert result.appendfsync is None
    assert result.maxmemory_policy == "volatile-lru"
    assert "private ACL diagnostic" not in repr(result)


def test_durability_observation_rejects_malformed_values_and_does_not_infer() -> None:
    result = RedisDurabilityObservation.from_observations(
        {
            "maxmemory_policy": "private arbitrary string",
            "maxmemory": True,
            "used_memory": -1,
            "mem_not_counted_for_evict": "0",
        },
        {"aof_enabled": "1", "aof_last_write_status": "private value"},
        {"evicted_keys": False},
        {"appendfsync": "private arbitrary string"},
    )
    assert result == RedisDurabilityObservation(status="partial")


@pytest.mark.asyncio
async def test_durability_observation_preserves_real_zero_and_false_values() -> None:
    manager = RedisConnectionManager()
    client = _durability_client()
    client.info.side_effect = [
        {"maxmemory_policy": "allkeys-lru", "maxmemory": 0,
         "used_memory": 0, "mem_not_counted_for_evict": 0},
        {"aof_enabled": 0, "aof_last_write_status": "err"},
        {"evicted_keys": 0},
    ]
    client.config_get.return_value = {"appendfsync": "everysec"}
    manager._client = client
    result = await manager.observe_durability()
    assert result.status == "observed"
    assert result.maxmemory_bytes == 0
    assert result.aof_enabled is False
    assert result.aof_write_ok is False


@pytest.mark.asyncio
async def test_durability_observation_fails_without_a_live_connection() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    manager = RedisConnectionManager()
    assert await manager.observe_durability() == RedisDurabilityObservation(
        status="unavailable"
    )
    client = _durability_client()
    manager._client = client
    manager._degraded_mode = True
    assert (await manager.observe_durability()).status == "unavailable"
    client.info.assert_not_awaited()
    manager._degraded_mode = False
    client.info.side_effect = RedisConnectionError("private connection URL")
    assert await manager.observe_durability() == RedisDurabilityObservation(
        status="unavailable"
    )


@pytest.mark.asyncio
async def test_durability_observation_does_not_swallow_cancellation() -> None:
    manager = RedisConnectionManager()
    client = _durability_client()
    client.info.side_effect = asyncio.CancelledError()
    manager._client = client
    with pytest.raises(asyncio.CancelledError):
        await manager.observe_durability()


@pytest.mark.asyncio
async def test_durability_observation_config_disconnect_is_unavailable() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    manager = RedisConnectionManager()
    client = _durability_client()
    manager._client = client
    client.config_get.side_effect = RedisConnectionError("private URL")
    assert await manager.observe_durability() == RedisDurabilityObservation(
        status="unavailable"
    )


@pytest.mark.asyncio
async def test_durability_observation_uses_bounded_timeout(monkeypatch) -> None:
    from ai_karen_engine.platform.memory.redis import redis_connection_manager

    manager = RedisConnectionManager()
    manager._client = _durability_client()

    async def expire(awaitable, *, timeout):
        assert timeout == 3.0
        awaitable.close()
        raise TimeoutError()

    monkeypatch.setattr(redis_connection_manager.asyncio, "wait_for", expire)
    assert await manager.observe_durability() == RedisDurabilityObservation(
        status="unavailable"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["replace", "close", "degrade"])
async def test_durability_observation_discards_superseded_client_evidence(change) -> None:
    manager = RedisConnectionManager()
    client = _durability_client()
    manager._client = client

    async def change_connection(*args, **kwargs):
        if change == "replace":
            manager._client = _durability_client()
        elif change == "close":
            manager._client = None
        else:
            manager._degraded_mode = True
        return {"appendfsync": "always"}

    client.config_get.side_effect = change_connection
    assert await manager.observe_durability() == RedisDurabilityObservation(
        status="unavailable"
    )
