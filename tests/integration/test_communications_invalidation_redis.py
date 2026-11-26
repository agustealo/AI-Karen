"""Live Redis proof of the canonical invalidation boundary, not browser delivery."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.realtime.inbox_invalidation import (
    inbox_invalidation_channel,
    publish_inbox_invalidation,
    wait_for_inbox_invalidation,
)
from ai_karen_engine.platform.memory.redis import initialize_redis_manager, shutdown_redis_manager


def _target() -> str:
    if os.environ.get("KAREN_TEST_DISPOSABLE_REDIS") != "1":
        raise RuntimeError("Disposable Redis opt-in required")
    url = os.environ.get("KAREN_TEST_COMMUNICATIONS_REDIS_URL", "")
    parsed = urlparse(url)
    if (
        parsed.scheme != "redis" or parsed.hostname != "127.0.0.1"
        or parsed.path != "/0" or parsed.port is None or parsed.port == 6379
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise RuntimeError("Dedicated loopback ephemeral Redis endpoint required")
    return url


async def _initialize(prefix: str):
    settings = get_runtime_settings()
    settings.features.enable_communications_invalidation = True
    settings.features.enable_communications_invalidation_wait = True
    settings.timeouts.communications_invalidation_timeout_ms = 1000
    settings.timeouts.communications_invalidation_wait_seconds = 10
    settings.timeouts.communications_invalidation_max_waiters = 2
    manager = await initialize_redis_manager(
        redis_url=_target(), max_connections=6, prefix=prefix,
        retry_on_timeout=False,
    )
    if not await manager.is_healthy():
        raise RuntimeError("Disposable Redis unavailable")
    return manager


async def _connected() -> bool:
    return False


async def _worker(prefix: str, tenant: str, owner: str) -> None:
    try:
        await _initialize(prefix)
        changed = await wait_for_inbox_invalidation(
            tenant_id=tenant, user_id=owner, disconnected=_connected,
        )
        sys.stdout.write("KCOMM_REDIS_RESULT=" + ("changed" if changed else "idle") + "\n")
        sys.stdout.flush()
    finally:
        await shutdown_redis_manager()


async def _wait_for_counts(client, channels: list[str], expected: int) -> None:
    async with asyncio.timeout(7):
        while True:
            counts = dict(await client.pubsub_numsub(*channels))
            if all(counts.get(channel) == expected for channel in channels):
                return
            await asyncio.sleep(0.025)


@pytest.mark.asyncio
async def test_real_redis_cross_process_owner_and_tenant_isolation():
    if os.environ.get("KAREN_TEST_DISPOSABLE_REDIS") != "1":
        pytest.skip("Explicit disposable Redis opt-in required")
    _target()
    prefix = "kcomm-proof-" + uuid.uuid4().hex
    tenant, owner, other_owner, other_tenant = (str(uuid.uuid4()) for _ in range(4))
    principals = [(tenant, owner), (tenant, other_owner), (other_tenant, owner)]
    channels = [
        inbox_invalidation_channel(prefix=prefix, tenant_id=t, user_id=u)
        for t, u in principals
    ]
    processes = []
    try:
        manager = await _initialize(prefix)
        client = manager.client
        assert client is not None
        # Independent Python processes, each with its own canonical Redis manager.
        for t, u in principals:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).resolve()), "--wait", prefix, t, u,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            processes.append(proc)
        await _wait_for_counts(client, channels, 1)
        await publish_inbox_invalidation(tenant_id=tenant, user_id=owner)
        # A single legitimate owner gets the change; foreign scopes must time out
        # with an acknowledged idle result, not receive the other owner's signal.
        results = await asyncio.wait_for(
            asyncio.gather(*(p.communicate() for p in processes)), timeout=15,
        )
        for i, (proc, (stdout, _stderr)) in enumerate(zip(processes, results)):
            assert proc.returncode == 0, f"Redis proof worker {i} failed"
            markers = [
                line for line in stdout.decode("utf-8").splitlines()
                if line.startswith("KCOMM_REDIS_RESULT=")
            ]
            assert markers == ["KCOMM_REDIS_RESULT=" + ("changed" if i == 0 else "idle")]
        await _wait_for_counts(client, channels, 0)

        # Cancellation must release the real subscription and allow the same
        # owner to subscribe again without consuming another permanent slot.
        task = asyncio.create_task(wait_for_inbox_invalidation(
            tenant_id=tenant, user_id=owner, disconnected=_connected,
        ))
        try:
            await _wait_for_counts(client, [channels[0]], 1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await _wait_for_counts(client, channels, 0)
        replacement = asyncio.create_task(wait_for_inbox_invalidation(
            tenant_id=tenant, user_id=owner, disconnected=_connected,
        ))
        try:
            await _wait_for_counts(client, [channels[0]], 1)
            await publish_inbox_invalidation(tenant_id=tenant, user_id=owner)
            assert await asyncio.wait_for(replacement, timeout=5) is True
        finally:
            if not replacement.done():
                replacement.cancel()
                await asyncio.gather(replacement, return_exceptions=True)
        await _wait_for_counts(client, channels, 0)
    finally:
        for proc in processes:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        await asyncio.gather(*(p.wait() for p in processes), return_exceptions=True)
        await shutdown_redis_manager()


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--wait":
        raise SystemExit("Expected isolated Redis worker arguments")
    asyncio.run(_worker(*sys.argv[2:]))
