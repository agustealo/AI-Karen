"""Host channel activation must not enable generic plugin execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels.activation import (
    ChannelActivationConflict,
    ChannelActivationDenied,
    ChannelActivationService,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SESSION = "authenticated-admin-session"


def connection(enabled=False, revision=2):
    return ChannelConnection(
        tenant_id=TENANT, connection_id="conn-telegram",
        installation_id="telegram-bot", provider_account_id="telegram-account",
        credential_handle="vault://telegram-account", enabled=enabled,
        revision=revision,
    )


def plan(action="channel.activate", *, allowed=True, session_id=SESSION):
    return AuthorizedExecutionPlan(
        execution_id="channel-config-1",
        policy_decision_id="policy-1",
        authorized_user_id=USER,
        authorized_tenant_id=TENANT,
        authorized_session_id=session_id,
        allowed_plugins=["telegram-bot"] if allowed else [],
        allowed_capabilities=[action],
    )


def components(*, active=True, role="admin", verified=True, valid=True):
    catalog = SimpleNamespace(
        capabilities=SimpleNamespace(communication_channel=SimpleNamespace(
            transport="telegram-bot",
        )),
        rbac=SimpleNamespace(allowed_roles=["admin"]),
    )
    registration = SimpleNamespace(state=ExtensionLifecycleState.DISABLED)
    adapter = SimpleNamespace(
        validate_config=AsyncMock(),
        start=AsyncMock(),
        stop=AsyncMock(),
    )
    kernel = SimpleNamespace(
        get_catalog_manifest=lambda _: catalog,
        get_record=lambda _: {"is_valid": valid},
        get_channel_activation_manifest=lambda _: catalog if valid else None,
        loader=SimpleNamespace(load_extension=lambda _: adapter),
        runtime_registry=SimpleNamespace(get=lambda _: registration),
    )
    before = connection()
    repo = SimpleNamespace(
        get_connection=AsyncMock(return_value=before),
        set_connection_enabled=AsyncMock(return_value=connection(True, 3)),
    )
    user = SimpleNamespace(
        id=USER, tenant_id=TENANT,
        status=UserStatus.ACTIVE if active else UserStatus.LOCKED,
        roles=[role], is_verified=verified,
    )
    lookup = AsyncMock(return_value=user)
    service = ChannelActivationService(
        kernel=kernel, repository=repo, principal_lookup=lookup,
    )
    return service, repo, kernel, adapter, lookup, registration


@pytest.mark.asyncio
async def test_authorized_admin_activates_only_tenant_connection():
    service, repo, kernel, adapter, lookup, registration = components()
    opened = await service.activate(
        tenant_id=TENANT, connection_id="conn-telegram", user_id=USER,
        session_id=SESSION, authorized_plan=plan(), adapter=adapter,
        settings={"private_chats_only": True},
    )
    assert opened.enabled and opened.revision == 3
    assert registration.state is ExtensionLifecycleState.DISABLED
    lookup.assert_awaited_once_with(tenant_id=TENANT, user_id=USER)
    adapter.validate_config.assert_awaited_once_with({"private_chats_only": True})
    adapter.start.assert_awaited_once()
    prepared = adapter.start.await_args.kwargs["connection"]
    assert prepared.enabled and prepared.revision == 3
    repo.set_connection_enabled.assert_awaited_once_with(
        tenant_id=TENANT, connection_id="conn-telegram",
        expected_revision=2, enabled=True,
    )
    adapter.stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,verified,active", [
    ("user", True, True), ("admin", False, True), ("admin", True, False),
])
async def test_non_admin_or_unverified_actor_cannot_start(role, verified, active):
    service, repo, _, adapter, _, _ = components(
        role=role, verified=verified, active=active,
    )
    with pytest.raises(ChannelActivationDenied):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram",
            user_id=USER, session_id=SESSION, authorized_plan=plan(),
            adapter=adapter, settings={},
        )
    adapter.start.assert_not_awaited()
    repo.set_connection_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_session_plan_denied_before_transport_start():
    service, repo, _, adapter, _, _ = components()
    with pytest.raises(ChannelActivationDenied, match="RuntimePolicy"):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram",
            user_id=USER, session_id=SESSION,
            authorized_plan=plan(session_id="other-session"),
            adapter=adapter, settings={},
        )
    adapter.start.assert_not_awaited()
    repo.set_connection_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_manually_disabled_is_not_activated():
    service, repo, kernel, adapter, _, _ = components()
    kernel.get_channel_activation_manifest = lambda _: None
    with pytest.raises(ChannelActivationDenied, match="manually disabled"):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram", user_id=USER,
            session_id=SESSION, authorized_plan=plan(), adapter=adapter, settings={},
        )
    adapter.start.assert_not_awaited()
    repo.set_connection_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_cas_race_rolls_back_transport_activation():
    service, repo, _, adapter, _, _ = components()
    repo.set_connection_enabled.return_value = None
    with pytest.raises(ChannelActivationConflict):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram",
            user_id=USER, session_id=SESSION,
            authorized_plan=plan(), adapter=adapter, settings={},
        )
    adapter.start.assert_awaited_once()
    adapter.stop.assert_awaited_once()
    assert adapter.stop.await_args.kwargs["connection"].revision == 3


@pytest.mark.asyncio
async def test_partial_start_error_stops_adapter_before_persisting():
    service, repo, _, adapter, _, _ = components()
    adapter.start.side_effect = OSError("credential failed")
    with pytest.raises(OSError):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram",
            user_id=USER, session_id=SESSION,
            authorized_plan=plan(), adapter=adapter, settings={},
        )
    adapter.stop.assert_awaited_once()
    repo.set_connection_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivation_revokes_durable_account_before_adapter_stop():
    service, repo, _, adapter, _, registration = components()
    repo.get_connection.return_value = connection(True, 3)
    repo.set_connection_enabled.return_value = connection(False, 4)
    events = []
    async def persist(**kwargs):
        events.append("db_revoke")
        return connection(False, 4)
    async def stop(**kwargs):
        events.append("adapter_stop")
    repo.set_connection_enabled.side_effect = persist
    adapter.stop.side_effect = stop

    closed = await service.deactivate(
        tenant_id=TENANT, connection_id="conn-telegram",
        user_id=USER, session_id=SESSION, authorized_plan=plan("channel.deactivate"),
        adapter=adapter,
    )
    assert closed.enabled is False
    assert closed.revision == 4
    assert events == ["db_revoke", "adapter_stop"]
    assert registration.state is ExtensionLifecycleState.DISABLED
    adapter.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_remains_durable_even_if_adapter_stop_fails():
    service, repo, _, adapter, _, _ = components()
    repo.get_connection.return_value = connection(True, 3)
    repo.set_connection_enabled.return_value = connection(False, 4)
    adapter.stop.side_effect = RuntimeError("native stop failed")
    closed = await service.deactivate(
        tenant_id=TENANT, connection_id="conn-telegram",
        user_id=USER, session_id=SESSION, authorized_plan=plan("channel.deactivate"),
        adapter=adapter,
    )
    assert closed.enabled is False
    repo.set_connection_enabled.assert_awaited_once_with(
        tenant_id=TENANT, connection_id="conn-telegram",
        expected_revision=3, enabled=False,
    )


@pytest.mark.asyncio
async def test_noncanonical_adapter_cannot_activate():
    service, repo, _, adapter, _, _ = components()
    other = SimpleNamespace(
        validate_config=AsyncMock(), start=AsyncMock(), stop=AsyncMock(),
    )
    with pytest.raises(ChannelActivationDenied, match="canonical loader"):
        await service.activate(
            tenant_id=TENANT, connection_id="conn-telegram",
            user_id=USER, session_id=SESSION,
            authorized_plan=plan(), adapter=other, settings={},
        )
    adapter.start.assert_not_awaited()
    other.start.assert_not_awaited()
    repo.set_connection_enabled.assert_not_awaited()


def test_kernel_exposes_channel_catalog_without_enabling_generic_execution(tmp_path, monkeypatch):
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
    # Use the real Telegram declaration, not a duplicate local provider schema.
    import json
    plugin_path = (
        tmp_path / "telegram-bot"
    )
    plugin_path.mkdir()
    source = __import__("pathlib").Path(__file__).resolve().parents[2] / (
        "src/ai_karen_engine/extensions/plugins/telegram-bot/manifest.json"
    )
    declaration = ExtensionManifest.from_dict(json.loads(source.read_text()))
    kernel = PluginKernel(tmp_path)
    kernel._catalog_manifests["telegram-bot"] = declaration
    registration = SimpleNamespace(state=ExtensionLifecycleState.DISABLED)
    monkeypatch.setattr(
        kernel.runtime_registry, "get",
        lambda plugin_id: registration if plugin_id == "telegram-bot" else None,
    )
    monkeypatch.setattr(
        kernel, "get_record", lambda plugin_id: {"is_valid": True},
    )
    assert kernel.get_channel_activation_manifest("telegram-bot") is declaration

    # Durable operator shutdown overrides even an already configured connection.
    disabled = plugin_path / ".karen-manual-disabled"
    disabled.write_text("disabled")
    assert kernel.get_channel_activation_manifest("telegram-bot") is None
    disabled.unlink()

    # A channel illegally enabled for generic plugin execution is not
    # simultaneously granted the separate host transport authority.
    registration.state = ExtensionLifecycleState.ENABLED
    assert kernel.get_channel_activation_manifest("telegram-bot") is None
