"""DB-owned channel connection activation and credential-revision fencing."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class Session:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def execute(self, stmt, params):
        self.calls.append((str(stmt), dict(params)))
        return Result(self.value)


def install(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant_id):
        assert tenant_id == TENANT
        yield session
    monkeypatch.setattr(module, "async_transaction_scope", scope)


def row(*, enabled=False, revision=2):
    return {
        "tenant_id": TENANT,
        "connection_id": "telegram-conn",
        "installation_id": "telegram-bot",
        "provider_account_id": "native-account",
        "credential_handle": "vault://telegram-account",
        "revision": revision,
        "enabled": enabled,
    }


@pytest.mark.asyncio
async def test_inactive_connection_can_be_read_only_inside_its_tenant(monkeypatch):
    session = Session(row())
    install(monkeypatch, session)
    connection = await SqlChannelRepository().get_connection(
        tenant_id=TENANT, connection_id="telegram-conn",
    )
    assert connection is not None
    assert connection.enabled is False
    assert connection.revision == 2
    assert connection.credential_handle == "vault://telegram-account"
    query, args = session.calls[0]
    assert "public.channel_connections" in query
    assert "tenant_id = CAST(:tenant AS uuid)" in query
    assert args == {"tenant": TENANT, "connection": "telegram-conn"}


@pytest.mark.asyncio
async def test_activation_cas_fences_revision_and_current_enabled_state(monkeypatch):
    session = Session(row(enabled=True, revision=3))
    install(monkeypatch, session)
    connection = await SqlChannelRepository().set_connection_enabled(
        tenant_id=TENANT, connection_id="telegram-conn",
        expected_revision=2, enabled=True,
    )
    assert connection is not None and connection.enabled is True
    assert connection.revision == 3
    query, args = session.calls[0]
    assert "revision = revision + 1" in query
    assert "enabled IS DISTINCT FROM :enabled" in query
    assert "revision = :revision" in query
    assert "tenant_id = CAST(:tenant AS uuid)" in query
    assert args == {
        "tenant": TENANT, "connection": "telegram-conn",
        "revision": 2, "enabled": True,
    }


@pytest.mark.asyncio
async def test_credential_rotation_or_concurrent_operator_causes_cas_miss(monkeypatch):
    session = Session(None)
    install(monkeypatch, session)
    assert await SqlChannelRepository().set_connection_enabled(
        tenant_id=TENANT, connection_id="telegram-conn",
        expected_revision=2, enabled=True,
    ) is None


@pytest.mark.asyncio
async def test_deactivation_also_advances_revision_and_fences_live_adapters(monkeypatch):
    session = Session(row(enabled=False, revision=4))
    install(monkeypatch, session)
    disabled = await SqlChannelRepository().set_connection_enabled(
        tenant_id=TENANT, connection_id="telegram-conn",
        expected_revision=3, enabled=False,
    )
    assert disabled is not None and not disabled.enabled
    assert disabled.revision == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_revision,bad_state", [
    (0, True), (-1, False), (1, "yes"), (1, None),
])
async def test_invalid_lifecycle_transition_never_touches_sql(bad_revision, bad_state):
    with pytest.raises(ValueError, match="Invalid"):
        await SqlChannelRepository().set_connection_enabled(
            tenant_id=TENANT, connection_id="telegram-conn",
            expected_revision=bad_revision, enabled=bad_state,
        )
