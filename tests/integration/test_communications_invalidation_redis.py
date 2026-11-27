"""Live Redis proof of the canonical invalidation boundary, not browser delivery."""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi import Request

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.realtime.inbox_invalidation import (
    InboxInvalidationUnavailable,
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


async def _initialize(prefix: str, *, pool_size: int = 6, wait_limit: int = 2, wait_seconds: int = 10):
    settings = get_runtime_settings()
    settings.features.enable_communications_invalidation = True
    settings.features.enable_communications_invalidation_wait = True
    settings.timeouts.communications_invalidation_timeout_ms = 1000
    settings.timeouts.communications_invalidation_wait_seconds = wait_seconds
    settings.timeouts.communications_invalidation_max_waiters = wait_limit
    manager = await initialize_redis_manager(
        redis_url=_target(), max_connections=pool_size, prefix=prefix,
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


@pytest.mark.asyncio
async def test_real_optional_redis_application_lifecycle(monkeypatch):
    """Exercise actual pool startup, unavailable transport and clean restart."""
    if os.environ.get("KAREN_TEST_DISPOSABLE_REDIS") != "1":
        pytest.skip("Explicit disposable Redis opt-in required")
    target = _target()

    from fastapi import FastAPI

    from ai_karen_engine.core.runtime.operational_health import OperationalHealthService
    from ai_karen_engine.platform.memory.redis import get_redis_manager
    from ai_karen_engine.server.application_runtime import (
        initialize_application_redis,
        shutdown_application_redis,
    )

    for name in (
        "KARI_ENABLE_MEMORY_SERVICE", "ENABLE_RATE_LIMITING", "AUTH_ENABLE_RATE_LIMITING",
    ):
        monkeypatch.setenv(name, "false")
    settings = get_runtime_settings()
    monkeypatch.setattr(settings.features, "enable_communications_invalidation", True)
    monkeypatch.setattr(settings.features, "enable_communications_invalidation_wait", True)
    monkeypatch.setattr(settings.timeouts, "communications_invalidation_timeout_ms", 1000)
    monkeypatch.setattr(settings.timeouts, "communications_invalidation_wait_seconds", 10)
    monkeypatch.setattr(settings.timeouts, "communications_invalidation_max_waiters", 2)
    health = OperationalHealthService()

    async def healthy_database():
        # Isolate the Redis dependency in the actual readiness composition.
        # This test does not establish database health.
        return {"ready": True}

    monkeypatch.setattr(health, "_database_check", healthy_database)
    assert health.redis_required() is False
    assert health.redis_lifecycle_enabled() is True
    tenant, owner = str(uuid.uuid4()), str(uuid.uuid4())

    # Ensure each cycle starts without a pre-initialized process singleton.
    await shutdown_redis_manager()
    app = FastAPI()
    unavailable = None
    try:
        # Hold an ephemeral loopback TCP port without listening: no external
        # target, no guessed port, no destructive action on the live broker.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{reserved.getsockname()[1]}/0")
            await initialize_application_redis(app)
            unavailable = app.state.redis_connection_manager
            assert unavailable is get_redis_manager()
            assert not await unavailable.is_healthy()
            readiness = await health.readiness(environment="development")
            assert readiness.ready is True
            assert readiness.checks["redis"] == {"ready": True, "status": "not_required"}
            with pytest.raises(InboxInvalidationUnavailable):
                await asyncio.wait_for(
                    wait_for_inbox_invalidation(
                        tenant_id=tenant, user_id=owner, disconnected=_connected,
                    ),
                    timeout=5,
                )
            # The same unavailable broker must still gate mandatory readiness.
            monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "true")
            mandatory = await health.readiness(environment="development")
            assert mandatory.ready is False
            assert mandatory.checks["redis"]["ready"] is False
            monkeypatch.setenv("AUTH_ENABLE_RATE_LIMITING", "false")
    finally:
        await shutdown_application_redis(app)
        await shutdown_application_redis(app)
    assert app.state.redis_connection_manager is None
    assert unavailable is not None and unavailable.client is None

    # A fresh application lifecycle on the real disposable broker recovers
    # without creating a parallel manager or changing global readiness policy.
    monkeypatch.setenv("REDIS_URL", target)
    app = FastAPI()
    manager = None
    task = None
    try:
        await initialize_application_redis(app)
        manager = app.state.redis_connection_manager
        assert manager is get_redis_manager() and manager is not unavailable
        assert await manager.is_healthy()
        client = manager.client
        assert client is not None
        await initialize_application_redis(app)
        assert app.state.redis_connection_manager is manager
        assert manager.client is client
        channel = inbox_invalidation_channel(
            prefix=manager.prefix, tenant_id=tenant, user_id=owner,
        )
        task = asyncio.create_task(wait_for_inbox_invalidation(
            tenant_id=tenant, user_id=owner, disconnected=_connected,
        ))
        await _wait_for_counts(client, [channel], 1)
        await publish_inbox_invalidation(tenant_id=tenant, user_id=owner)
        assert await asyncio.wait_for(task, timeout=5) is True
        await _wait_for_counts(client, [channel], 0)
        readiness = await health.readiness(environment="development")
        assert readiness.ready is True
        assert readiness.checks["redis"] == {"ready": True, "status": "not_required"}
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await shutdown_application_redis(app)
        await shutdown_application_redis(app)
    assert app.state.redis_connection_manager is None
    assert manager is not None and manager.client is None


@pytest.mark.asyncio
async def test_real_redis_wait_releases_on_asgi_disconnect_through_http_middleware():
    """Exercise the real broker under layered ASGI receive boundaries."""
    if os.environ.get("KAREN_TEST_DISPOSABLE_REDIS") != "1":
        pytest.skip("Explicit disposable Redis opt-in required")
    _target()

    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    from ai_karen_engine.server.middleware import observe_bodyless_request_disconnect

    prefix = "kcomm-disconnect-" + uuid.uuid4().hex
    tenant, owner = str(uuid.uuid4()), str(uuid.uuid4())
    manager = await _initialize(prefix)
    client = manager.client
    assert client is not None
    channel = inbox_invalidation_channel(prefix=prefix, tenant_id=tenant, user_id=owner)
    app = FastAPI()
    incoming = asyncio.Queue()
    disconnect_observed = asyncio.Event()
    running = None
    replacement = None

    async def passthrough(request: Request, call_next):
        return await call_next(request)

    # Real Starlette middleware crosses the receive checkpoints that immediate
    # Request.is_disconnected() polling can miss.
    for _ in range(3):
        app.add_middleware(BaseHTTPMiddleware, dispatch=passthrough)

    @app.get("/wait")
    async def wait(request: Request):
        async with observe_bodyless_request_disconnect(request) as disconnected:
            try:
                await wait_for_inbox_invalidation(
                    tenant_id=tenant, user_id=owner, disconnected=disconnected,
                )
            except InboxInvalidationUnavailable:
                assert await disconnected()
                disconnect_observed.set()
                return JSONResponse({"detail": "unavailable"}, status_code=503)
        pytest.fail("Disconnected wait must not return a successful hint")

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/wait", "raw_path": b"/wait", "query_string": b"",
        "root_path": "", "headers": [], "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    async def send(_message):
        pass

    try:
        incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        running = asyncio.create_task(app(scope, incoming.get, send))
        await _wait_for_counts(client, [channel], 1)
        incoming.put_nowait({"type": "http.disconnect"})

        # The configured wait is ten seconds. Cleanup must happen well before
        # idle expiry, without publishing a hint or waiting out that deadline.
        await asyncio.wait_for(disconnect_observed.wait(), timeout=3)
        await asyncio.wait_for(running, timeout=3)
        await _wait_for_counts(client, [channel], 0)

        replacement = asyncio.create_task(wait_for_inbox_invalidation(
            tenant_id=tenant, user_id=owner, disconnected=_connected,
        ))
        await _wait_for_counts(client, [channel], 1)
        await publish_inbox_invalidation(tenant_id=tenant, user_id=owner)
        assert await asyncio.wait_for(replacement, timeout=3) is True
        await _wait_for_counts(client, [channel], 0)
    finally:
        for task in (running, replacement):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await shutdown_redis_manager()


async def _capacity_worker(prefix: str, tenant: str, first: str, second: str, third: str) -> None:
    """Saturate one worker's actual shared pool without using private counters."""
    tasks = []
    try:
        # The configured limit is four, but the pool-minus-two bound must
        # admit only two waits. Keep two real connections simultaneously usable.
        manager = await _initialize(prefix, pool_size=4, wait_limit=4, wait_seconds=15)
        client = manager.client
        assert client is not None
        channels = [
            inbox_invalidation_channel(prefix=prefix, tenant_id=tenant, user_id=owner)
            for owner in (first, second, third)
        ]

        async def wait(owner: str) -> bool:
            return await wait_for_inbox_invalidation(
                tenant_id=tenant, user_id=owner, disconnected=_connected,
            )

        tasks.extend(asyncio.create_task(wait(owner)) for owner in (first, second))
        await _wait_for_counts(client, channels[:2], 1)
        # Fail immediately, rather than silently queuing or allocating a
        # third subscriber. Duplicate ownership must also fail at saturation.
        for owner in (first, third):
            with pytest.raises(InboxInvalidationUnavailable):
                await asyncio.wait_for(wait(owner), timeout=2)
        await _wait_for_counts(client, [channels[2]], 0)
        assert all(not task.done() for task in tasks)

        # Both clients pin distinct physical connections from the existing
        # manager pool. Sequential ordinary PINGs alone could reuse one slot.
        async with client.client() as left, client.client() as right:
            assert await left.client_id() != await right.client_id()
            assert await left.ping() is True
            assert await right.ping() is True

        sys.stdout.write("KCOMM_CAPACITY_READY\n")
        sys.stdout.flush()

        assert await asyncio.wait_for(tasks[0], timeout=12) is True
        # The previously rejected owner must now be able to acquire the freed
        # slot while the second original owner is still subscribed.
        assert not tasks[1].done()
        tasks.append(asyncio.create_task(wait(third)))
        await _wait_for_counts(client, channels[1:], 1)
        sys.stdout.write("KCOMM_CAPACITY_REPLACEMENT_READY\n")
        sys.stdout.flush()
        assert await asyncio.wait_for(tasks[2], timeout=10) is True
        assert await asyncio.wait_for(tasks[1], timeout=10) is True
        await _wait_for_counts(client, channels, 0)
        assert await client.ping() is True
        sys.stdout.write("KCOMM_CAPACITY_RESULT=passed\n")
        sys.stdout.flush()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await shutdown_redis_manager()


async def _capacity_ready(process: asyncio.subprocess.Process, marker: bytes) -> None:
    assert process.stdout is not None
    async with asyncio.timeout(10):
        while True:
            line = await process.stdout.readline()
            if not line:
                raise AssertionError("Capacity worker exited before readiness")
            if line.strip() == marker:
                return


@pytest.mark.asyncio
async def test_real_redis_independent_worker_capacity_and_reserved_connections():
    """Two independently saturated workers, real pool and broker observations."""
    if os.environ.get("KAREN_TEST_DISPOSABLE_REDIS") != "1":
        pytest.skip("Explicit disposable Redis opt-in required")
    _target()
    prefix = "kcomm-capacity-" + uuid.uuid4().hex
    tenant = str(uuid.uuid4())
    owners = [tuple(str(uuid.uuid4()) for _ in range(3)) for _ in range(2)]
    channels = [
        [inbox_invalidation_channel(prefix=prefix, tenant_id=tenant, user_id=owner) for owner in group]
        for group in owners
    ]
    processes = []
    try:
        manager = await _initialize(prefix)
        client = manager.client
        assert client is not None
        for group in owners:
            processes.append(await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).resolve()), "--capacity", prefix, tenant, *group,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            ))
        await asyncio.gather(*(_capacity_ready(proc, b"KCOMM_CAPACITY_READY") for proc in processes))
        await _wait_for_counts(client, [ch for group in channels for ch in group[:2]], 1)
        await _wait_for_counts(client, [group[2] for group in channels], 0)

        for group in owners:
            await publish_inbox_invalidation(tenant_id=tenant, user_id=group[0])
        await asyncio.gather(*(
            _capacity_ready(proc, b"KCOMM_CAPACITY_REPLACEMENT_READY") for proc in processes
        ))
        await _wait_for_counts(client, [group[0] for group in channels], 0)
        await _wait_for_counts(client, [ch for group in channels for ch in group[1:]], 1)

        # Publish to the replacements only, prove the second original owner
        # stays subscribed until its own signal, then release all reservations.
        for group in owners:
            await publish_inbox_invalidation(tenant_id=tenant, user_id=group[2])
        await _wait_for_counts(client, [group[2] for group in channels], 0)
        await _wait_for_counts(client, [group[1] for group in channels], 1)
        for group in owners:
            await publish_inbox_invalidation(tenant_id=tenant, user_id=group[1])

        results = await asyncio.wait_for(
            asyncio.gather(*(proc.communicate() for proc in processes)), timeout=12,
        )
        for index, (proc, (stdout, _stderr)) in enumerate(zip(processes, results)):
            assert proc.returncode == 0, f"Capacity worker {index} failed"
            markers = [
                line for line in stdout.decode("utf-8").splitlines()
                if line.startswith("KCOMM_CAPACITY_RESULT=")
            ]
            assert markers == ["KCOMM_CAPACITY_RESULT=passed"]
        await _wait_for_counts(client, [ch for group in channels for ch in group], 0)
    finally:
        for proc in processes:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        await asyncio.gather(*(proc.wait() for proc in processes), return_exceptions=True)
        await shutdown_redis_manager()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--wait":
        asyncio.run(_worker(*sys.argv[2:]))
    elif len(sys.argv) == 7 and sys.argv[1] == "--capacity":
        asyncio.run(_capacity_worker(*sys.argv[2:]))
    else:
        raise SystemExit("Expected isolated Redis worker arguments")
