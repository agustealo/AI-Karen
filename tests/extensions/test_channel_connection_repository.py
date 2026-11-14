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

    def all(self):
        return self.value

    def scalar_one_or_none(self):
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


@pytest.mark.asyncio
async def test_personal_channel_inventory_is_bounded_by_exact_tenant_and_owner(monkeypatch):
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    session = Session([row()])
    install(monkeypatch, session)
    connections = await SqlChannelRepository().list_personal_owned_connections(
        tenant_id=TENANT, user_id=user,
    )
    assert len(connections) == 1
    assert connections[0].connection_id == "telegram-conn"
    assert connections[0].enabled is False
    query, args = session.calls[0]
    assert "JOIN public.channel_connection_owners o" in query
    assert "o.tenant_id = c.tenant_id" in query
    assert "o.connection_id = c.connection_id" in query
    assert "c.tenant_id = CAST(:tenant AS uuid)" in query
    assert "o.user_id = CAST(:user AS uuid)" in query
    assert "LIMIT 51" in query
    assert args == {"tenant": TENANT, "user": user}


@pytest.mark.asyncio
async def test_personal_inventory_does_not_silently_truncate_owner_rows(monkeypatch):
    session = Session([row()] * 51)
    install(monkeypatch, session)
    with pytest.raises(RuntimeError, match="inventory limit exceeded"):
        await SqlChannelRepository().list_personal_owned_connections(
            tenant_id=TENANT, user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )


@pytest.mark.asyncio
async def test_personal_inventory_rejects_untrusted_identity_without_database_work(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_personal_owned_connections(
            tenant_id=TENANT, user_id="not-a-uuid",
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_active_historical_consent_providers_are_owner_and_tenant_scoped(monkeypatch):
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    connection = "telegram-conn"
    session = Session([
        {"provider_id": "old-managed-operator"},
        {"provider_id": "previous-managed-operator"},
    ])
    install(monkeypatch, session)
    providers = await SqlChannelRepository().list_active_personal_consent_providers(
        tenant_id=TENANT, connection_id=connection, user_id=user,
    )
    assert providers == ["old-managed-operator", "previous-managed-operator"]
    query, args = session.calls[0]
    assert "public.channel_personal_pairing_consents p" in query
    assert "JOIN public.channel_connection_owners o" in query
    assert "o.user_id = p.user_id" in query
    assert "JOIN public.channel_connections c" in query
    assert "p.revoked_at IS NULL" in query
    assert "u.is_active = true" in query
    assert "u.is_verified = true" in query
    assert "p.tenant_id = CAST(:tenant AS uuid)" in query
    assert "p.connection_id = :connection" in query
    assert "p.user_id = CAST(:user AS uuid)" in query
    assert "LIMIT 17" in query
    assert args == {"tenant": TENANT, "connection": connection, "user": user}


@pytest.mark.asyncio
async def test_active_historical_consent_inventory_empty_is_not_fabricated(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    assert await SqlChannelRepository().list_active_personal_consent_providers(
        tenant_id=TENANT, connection_id="telegram-conn",
        user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ) == []


@pytest.mark.asyncio
async def test_active_historical_consent_inventory_refuses_silent_truncation(monkeypatch):
    session = Session([{"provider_id": f"operator-{i}"} for i in range(17)])
    install(monkeypatch, session)
    with pytest.raises(RuntimeError, match="inventory limit exceeded"):
        await SqlChannelRepository().list_active_personal_consent_providers(
            tenant_id=TENANT, connection_id="telegram-conn",
            user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )


@pytest.mark.asyncio
async def test_active_historical_consent_inventory_rejects_untrusted_identity(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_active_personal_consent_providers(
            tenant_id=TENANT, connection_id="telegram-conn",
            user_id="forged-user",
        )
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_active_personal_consent_providers(
            tenant_id=TENANT, connection_id="",
            user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_retired_consent_inventory_uses_exact_owner_active_user_and_tenant_rls(monkeypatch):
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    session = Session([
        {"connection_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
         "provider_id": "retired-operator", "policy_version": "legacy-v1"},
    ])
    install(monkeypatch, session)
    records = await SqlChannelRepository().list_owned_active_personal_consents(
        tenant_id=TENANT, user_id=user,
    )
    assert records == [{
        "connection_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "provider_id": "retired-operator",
        "policy_version": "legacy-v1",
    }]
    query, args = session.calls[0]
    assert "public.channel_personal_pairing_consents p" in query
    assert "JOIN public.channel_connection_owners o" in query
    assert "o.user_id = p.user_id" in query
    assert "JOIN public.channel_connections c" in query
    assert "JOIN public.auth_users u" in query
    assert "p.revoked_at IS NULL" in query
    assert "u.is_active = true" in query
    assert "u.is_verified = true" in query
    assert "p.tenant_id = CAST(:tenant AS uuid)" in query
    assert "p.user_id = CAST(:user AS uuid)" in query
    assert "LIMIT 51" in query
    assert args == {"tenant": TENANT, "user": user}


@pytest.mark.asyncio
async def test_retired_consent_inventory_does_not_invent_or_truncate(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    assert await SqlChannelRepository().list_owned_active_personal_consents(
        tenant_id=TENANT, user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ) == []
    session.value = [
        {"connection_id": "conn", "provider_id": f"provider-{i}",
         "policy_version": "v1"} for i in range(51)
    ]
    with pytest.raises(RuntimeError, match="inventory limit exceeded"):
        await SqlChannelRepository().list_owned_active_personal_consents(
            tenant_id=TENANT, user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )


@pytest.mark.asyncio
async def test_retired_consent_inventory_rejects_bad_user_before_database(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_owned_active_personal_consents(
            tenant_id=TENANT, user_id="forged-user",
        )
    assert session.calls == []



@pytest.mark.asyncio
async def test_retired_deletion_request_inventory_is_owner_and_tenant_scoped(monkeypatch):
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    request_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    session = Session([{
        "request_id": request_id,
        "connection_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "provider_id": "retired-operator",
        "connection_revision": 7,
        "status": "provider_claimed",
        "session_reference": "must-not-return",
        "credential_scope": "must-not-return",
        "provider_receipt_id": "must-not-return",
    }])
    install(monkeypatch, session)
    records = await SqlChannelRepository().list_owned_personal_credential_deletion_requests(
        tenant_id=TENANT, user_id=user,
    )
    assert records == [{
        "request_id": request_id,
        "connection_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "provider_id": "retired-operator",
        "connection_revision": 7,
        "status": "provider_claimed",
    }]
    query, params = session.calls[0]
    assert "JOIN public.channel_connection_owners o" in query
    assert "o.user_id = d.user_id" in query
    assert "JOIN public.channel_connections c" in query
    assert "JOIN public.auth_users u" in query
    assert "u.is_active = true" in query and "u.is_verified = true" in query
    assert "d.tenant_id = CAST(:tenant AS uuid)" in query
    assert "d.user_id = CAST(:user AS uuid)" in query
    assert "LIMIT 51" in query
    assert params == {"tenant": TENANT, "user": user}
    selected = query.split("FROM public.channel_personal_credential_deletions")[0]
    for secret in ("session_reference", "credential_scope", "provider_receipt_id", "credential_handle"):
        assert secret not in selected


@pytest.mark.asyncio
async def test_retired_deletion_request_inventory_is_empty_or_fails_closed_on_overflow(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    kwargs = {"tenant_id": TENANT, "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
    assert await SqlChannelRepository().list_owned_personal_credential_deletion_requests(**kwargs) == []
    session.value = [{
        "request_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "connection_id": "conn", "provider_id": "provider",
        "connection_revision": 1, "status": "requested",
    }] * 51
    with pytest.raises(RuntimeError, match="inventory limit exceeded"):
        await SqlChannelRepository().list_owned_personal_credential_deletion_requests(**kwargs)


@pytest.mark.asyncio
async def test_retired_deletion_request_inventory_rejects_forged_identity_before_sql(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_owned_personal_credential_deletion_requests(
            tenant_id=TENANT, user_id="not-an-authenticated-user",
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_retirement_evidence_inventory_is_scoped_bounded_and_secretless(monkeypatch):
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    connection = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    stored = {
        "connection_id": connection, "revision": 7, "enabled": False,
        "retirement_locked": True,
        "active_consent": True, "unresolved_pairing": True,
        "deletion_request_recorded": True, "unverified_deletion_request": True,
        "inbox_not_completed": False, "outbound_not_confirmed": True,
        "credential_handle": "vault://private",
    }
    session = Session([stored])
    install(monkeypatch, session)
    result = await SqlChannelRepository().list_owned_personal_retirement_evidence(
        tenant_id=TENANT, user_id=user,
    )
    assert result == [{
        "connection_id": connection, "connection_revision": 7,
        "connection_enabled": False, "retirement_held": True,
        "active_consent": True,
        "unresolved_pairing": True, "deletion_request_recorded": True,
        "unverified_deletion_request": True, "inbox_not_completed": False,
        "outbound_not_confirmed": True,
    }]
    query, args = session.calls[0]
    for term in ("JOIN public.channel_connection_owners o",
                 "JOIN public.auth_users u", "u.is_active = true",
                 "u.is_verified = true", "c.tenant_id = CAST(:tenant AS uuid)",
                 "o.user_id = CAST(:user AS uuid)", "LIMIT 51",
                 "channel_personal_pairing_state",
                 "channel_personal_credential_deletions",
                 "channel_inbox", "channel_outbox"):
        assert term in query
    assert args == {"tenant": TENANT, "user": user}
    selected = query.split("FROM public.channel_connections c")[0]
    for secret in ("credential_handle", "provider_account_id",
                   "session_reference", "provider_receipt_id", "message_text"):
        assert secret not in selected


@pytest.mark.asyncio
async def test_retirement_evidence_denies_overflow_and_invalid_identity(monkeypatch):
    session = Session([])
    install(monkeypatch, session)
    tenant_user = {
        "tenant_id": TENANT,
        "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }
    assert await SqlChannelRepository().list_owned_personal_retirement_evidence(
        **tenant_user,
    ) == []
    session.value = [object()] * 51
    with pytest.raises(RuntimeError, match="inventory limit exceeded"):
        await SqlChannelRepository().list_owned_personal_retirement_evidence(
            **tenant_user,
        )
    session.calls.clear()
    with pytest.raises(ValueError):
        await SqlChannelRepository().list_owned_personal_retirement_evidence(
            tenant_id=TENANT, user_id="invalid-actor",
        )
    assert session.calls == []


class RetirementSession:
    """Deterministic repository SQL transcript, without inventing DB success."""

    def __init__(self, *, connection=None, existing=None, revision=2):
        self.connection = connection if connection is not None else {
            "revision": 1, "enabled": True, "retirement_locked": False,
            "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        }
        self.existing = existing
        self.revision = revision
        self.calls = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, dict(params)))
        if "SELECT c.revision, c.enabled, c.retirement_locked" in sql:
            return Result(self.connection)
        if "SELECT hold_id, requested_revision" in sql:
            return Result(self.existing)
        if "UPDATE public.channel_connections" in sql:
            return Result(self.revision)
        if "INSERT INTO public.channel_personal_retirement_holds" in sql:
            return Result("dddddddd-dddd-dddd-dddd-dddddddddddd")
        raise AssertionError("Unexpected retirement repository SQL")


@pytest.mark.asyncio
async def test_retirement_hold_atomically_fences_revision_and_persists_actor(monkeypatch):
    session = RetirementSession()
    install(monkeypatch, session)
    operator = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    idem = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    result = await SqlChannelRepository().place_personal_retirement_hold(
        tenant_id=TENANT, connection_id="personal-connection",
        operator_user_id=operator, expected_revision=1, idempotency_key=idem,
    )
    assert result == {
        "hold_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "connection_revision": 2, "created_new": True,
    }
    assert len(session.calls) == 4
    assert "FOR UPDATE OF c" in session.calls[0][0]
    assert "JOIN public.channel_connection_owners o" in session.calls[0][0]
    assert "actor.is_verified = true" in session.calls[0][0]
    assert "retirement_locked = true" in session.calls[2][0]
    assert "revision = revision + 1" in session.calls[2][0]
    assert "enabled = false" in session.calls[2][0]
    assert session.calls[3][1]["operator"] == operator
    assert session.calls[3][1]["owner"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert session.calls[3][1]["idempotency"] == idem


@pytest.mark.asyncio
async def test_retirement_hold_exact_replay_is_idempotent_and_never_rewrites(monkeypatch):
    operator = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    idem = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    session = RetirementSession(
        connection={
            "revision": 2, "enabled": False, "retirement_locked": True,
            "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        },
        existing={
            "hold_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "owner_user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "operator_user_id": operator, "idempotency_key": idem,
            "requested_revision": 1, "fenced_revision": 2,
        },
    )
    install(monkeypatch, session)
    args = dict(tenant_id=TENANT, connection_id="personal-connection",
                operator_user_id=operator, expected_revision=1,
                idempotency_key=idem)
    result = await SqlChannelRepository().place_personal_retirement_hold(**args)
    assert result["created_new"] is False
    assert len(session.calls) == 2

    from ai_karen_engine.persistence.repositories.channel_repository import (
        ChannelRetirementConflict,
    )
    with pytest.raises(ChannelRetirementConflict):
        await SqlChannelRepository().place_personal_retirement_hold(
            **{**args, "idempotency_key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
        )
    assert len(session.calls) == 4


@pytest.mark.asyncio
async def test_retirement_hold_wrong_scope_stale_revision_and_invalid_inputs_denied(monkeypatch):
    from ai_karen_engine.persistence.repositories.channel_repository import (
        ChannelAdmissionDenied, ChannelRetirementConflict,
    )
    operator = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    idem = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    args = dict(tenant_id=TENANT, connection_id="personal-connection",
                operator_user_id=operator, expected_revision=1,
                idempotency_key=idem)
    session = RetirementSession()
    install(monkeypatch, session)
    for change in (
        {"expected_revision": True},
        {"expected_revision": 0},
        {"operator_user_id": "not-a-uuid"},
        {"idempotency_key": "not-a-uuid"},
        {"connection_id": " "},
    ):
        with pytest.raises(ValueError):
            await SqlChannelRepository().place_personal_retirement_hold(
                **{**args, **change},
            )
    assert session.calls == []

    session.connection = None
    with pytest.raises(ChannelAdmissionDenied):
        await SqlChannelRepository().place_personal_retirement_hold(**args)
    assert len(session.calls) == 1

    session.calls.clear()
    session.connection = {
        "revision": 2, "enabled": True, "retirement_locked": False,
        "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }
    with pytest.raises(ChannelRetirementConflict, match="Stale"):
        await SqlChannelRepository().place_personal_retirement_hold(**args)
    assert len(session.calls) == 2

    session.calls.clear()
    session.connection["retirement_locked"] = True
    with pytest.raises(ChannelRetirementConflict, match="already"):
        await SqlChannelRepository().place_personal_retirement_hold(**args)
    assert len(session.calls) == 2
