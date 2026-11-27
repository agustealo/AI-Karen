"""Internal signal contract: no fake delivery or cross-owner channel."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_karen_engine.config.runtime import RuntimeSettings
from ai_karen_engine.core.realtime import inbox_invalidation as invalidation
from ai_karen_engine.platform.memory import redis as redis_module

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
FOREIGN = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def test_invalidation_channel_is_exact_owner_and_namespace():
    make = invalidation.inbox_invalidation_channel
    expected = f"kari:communications:inbox:tenant:{TENANT}:user:{OWNER}"
    assert make(prefix="kari", tenant_id=TENANT.upper(), user_id=OWNER.upper()) == expected
    assert make(prefix="kari", tenant_id=FOREIGN, user_id=OWNER) != expected
    assert make(prefix="kari", tenant_id=TENANT, user_id=FOREIGN) != expected
    assert make(prefix="isolated", tenant_id=TENANT, user_id=OWNER) != expected
    for prefix in ("", "*", "kari:other", "kari\n"):
        with pytest.raises(ValueError):
            make(prefix=prefix, tenant_id=TENANT, user_id=OWNER)
    with pytest.raises(ValueError):
        make(prefix="kari", tenant_id=TENANT, user_id="*")


def test_invalidation_config_defaults_and_strict_overrides(monkeypatch):
    settings = RuntimeSettings()
    assert settings.features.enable_communications_invalidation is False
    assert settings.timeouts.communications_invalidation_timeout_ms == 250
    monkeypatch.setenv("KARI_ENABLE_COMMUNICATIONS_INVALIDATION", "true")
    monkeypatch.setenv("KARI_COMMUNICATIONS_INVALIDATION_TIMEOUT_MS", "500")
    settings.apply_env_overrides()
    assert settings.features.enable_communications_invalidation is True
    assert settings.timeouts.communications_invalidation_timeout_ms == 500
    monkeypatch.setenv("KARI_COMMUNICATIONS_INVALIDATION_TIMEOUT_MS", "1001")
    with pytest.raises(ValueError, match="timeout"):
        RuntimeSettings().apply_env_overrides()
    monkeypatch.setenv("KARI_COMMUNICATIONS_INVALIDATION_TIMEOUT_MS", "250")
    monkeypatch.setenv("KARI_ENABLE_COMMUNICATIONS_INVALIDATION", "maybe")
    with pytest.raises(ValueError, match="boolean"):
        RuntimeSettings().apply_env_overrides()


@pytest.fixture
def configured(monkeypatch):
    settings = RuntimeSettings()
    settings.features.enable_communications_invalidation = True
    client = SimpleNamespace(publish=AsyncMock(return_value=0))
    manager = SimpleNamespace(prefix="kari", client=client, is_degraded=Mock(return_value=False))
    get_manager = Mock(return_value=manager)
    monkeypatch.setattr(invalidation, "get_runtime_settings", lambda: settings)
    monkeypatch.setattr(redis_module, "get_redis_manager", get_manager)
    return settings, client, manager, get_manager


@pytest.mark.asyncio
async def test_disabled_does_not_resolve_redis(configured):
    settings, client, _, get_manager = configured
    settings.features.enable_communications_invalidation = False
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    get_manager.assert_not_called()
    client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_publishes_only_owner_channel_and_constant_signal(configured, caplog):
    _, client, _, _ = configured
    with caplog.at_level("INFO"):
        await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    client.publish.assert_awaited_once_with(
        f"kari:communications:inbox:tenant:{TENANT}:user:{OWNER}",
        invalidation.INBOX_INVALIDATION_SIGNAL,
    )
    assert "broker_acknowledged" in caplog.text
    assert "delivered" not in caplog.text


@pytest.mark.asyncio
async def test_degraded_and_invalid_scope_never_publish(configured):
    _, client, manager, _ = configured
    manager.is_degraded.return_value = True
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    manager.is_degraded.return_value = False
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id="*")
    manager.client = None
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_broker_failure_is_not_a_durable_write_failure(configured, caplog):
    _, client, _, _ = configured
    client.publish.side_effect = RuntimeError("private redis credential")
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    client.publish.assert_awaited_once()
    assert "invalidation.unavailable" in caplog.text
    assert "private redis credential" not in caplog.text
    assert "broker_acknowledged" not in caplog.text


@pytest.mark.asyncio
async def test_timeout_never_retries(configured):
    settings, client, _, _ = configured
    settings.timeouts.communications_invalidation_timeout_ms = 1

    async def delayed(*args):
        await asyncio.sleep(1)

    client.publish.side_effect = delayed
    await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)
    client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_propagates(configured):
    _, client, _, _ = configured
    client.publish.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await invalidation.publish_inbox_invalidation(tenant_id=TENANT, user_id=OWNER)


def test_wait_config_is_default_off_and_bounded(monkeypatch):
    settings = RuntimeSettings()
    assert settings.features.enable_communications_invalidation_wait is False
    assert settings.timeouts.communications_invalidation_wait_seconds == 10
    settings.features.enable_communications_invalidation_wait = True
    assert any("wait requires" in issue for issue in settings.validate())
    monkeypatch.setenv("KARI_COMMUNICATIONS_INVALIDATION_WAIT_SECONDS", "16")
    with pytest.raises(ValueError, match="WAIT_SECONDS"):
        settings.apply_env_overrides()


class Subscription:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.subscribe = AsyncMock()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def get_message(self, **kwargs):
        return next(self.frames)


async def connected():
    return False


@pytest.mark.asyncio
async def test_wait_requires_real_ack_and_exact_owner_signal(configured):
    settings, client, manager, _ = configured
    settings.features.enable_communications_invalidation_wait = True
    manager.max_connections = 10
    channel = invalidation.inbox_invalidation_channel(prefix="kari", tenant_id=TENANT, user_id=OWNER)
    ack = {"type": "subscribe", "channel": channel, "data": 1}
    signal = {"type": "message", "channel": channel, "data": invalidation.INBOX_INVALIDATION_SIGNAL}
    sub = Subscription([ack, signal])
    client.pubsub = Mock(return_value=sub)
    assert await invalidation.wait_for_inbox_invalidation(
        tenant_id=TENANT, user_id=OWNER, disconnected=connected,
    ) is True
    sub.subscribe.assert_awaited_once_with(channel)
    assert sub.closed
    for frames in ([signal], [ack, {**signal, "channel": channel.replace(OWNER, FOREIGN)}],
                   [ack, {**signal, "data": "private data"}], [ack, ack]):
        sub = Subscription(frames)
        client.pubsub.return_value = sub
        with pytest.raises(invalidation.InboxInvalidationUnavailable):
            await invalidation.wait_for_inbox_invalidation(
                tenant_id=TENANT, user_id=OWNER, disconnected=connected,
            )
        assert sub.closed


@pytest.mark.asyncio
async def test_wait_cancellation_releases_owner_and_pool_reservation(configured, caplog):
    settings, client, manager, _ = configured
    settings.features.enable_communications_invalidation_wait = True
    manager.max_connections = 10
    channel = invalidation.inbox_invalidation_channel(prefix="kari", tenant_id=TENANT, user_id=OWNER)
    ack = {"type": "subscribe", "channel": channel, "data": 1}
    signal = {"type": "message", "channel": channel, "data": invalidation.INBOX_INVALIDATION_SIGNAL}
    entered = asyncio.Event()

    async def receive(**kwargs):
        if not entered.is_set():
            entered.set()
            return ack
        await asyncio.Event().wait()

    sub = Subscription([])
    sub.get_message = receive
    client.pubsub = Mock(return_value=sub)
    task = asyncio.create_task(invalidation.wait_for_inbox_invalidation(
        tenant_id=TENANT, user_id=OWNER, disconnected=connected,
    ))
    await entered.wait()
    trace = "fe95b316-10ac-42ee-92ce-0cdbe4c5a7a6"
    with pytest.raises(invalidation.InboxInvalidationUnavailable):
        await invalidation.wait_for_inbox_invalidation(
            tenant_id=TENANT, user_id=OWNER, disconnected=connected, correlation_id=trace,
        )
    failures = [r for r in caplog.records if getattr(r, "reason", None) == "duplicate_owner"]
    assert len(failures) == 1
    assert failures[0].correlation_id == trace
    assert failures[0].error_type == "InboxInvalidationUnavailable"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sub.closed
    replacement = Subscription([ack, signal])
    client.pubsub.return_value = replacement
    assert await invalidation.wait_for_inbox_invalidation(
        tenant_id=TENANT, user_id=OWNER, disconnected=connected,
    ) is True
    assert replacement.closed
