"""KOC-04D: SQL-owned connection provisioning and one-use native proofs."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TOKEN = "a" * 43
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()


class Result:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def scalar_one_or_none(self):
        return self.scalar


class Session:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    async def execute(self, statement, args):
        self.calls.append((str(statement), dict(args)))
        return self.values.pop(0)


def install(monkeypatch, session):
    @asynccontextmanager
    async def scope(tenant_id):
        assert tenant_id == TENANT
        yield session
    monkeypatch.setattr(module, "async_transaction_scope", scope)


def connection():
    return ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="telegram-bot", provider_account_id="telegram-account",
        credential_handle="vault://telegram", revision=3, enabled=True,
    )


def connection_row():
    return {
        "tenant_id": TENANT, "connection_id": "new-id",
        "installation_id": "telegram-bot",
        "provider_account_id": "telegram-account",
        "credential_handle": "vault://telegram", "revision": 1,
        "enabled": False,
    }


def binding_row():
    return {
        "binding_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "tenant_id": TENANT, "connection_id": "conn",
        "external_sender_id": "901", "user_id": USER, "revision": 1,
    }


@pytest.mark.asyncio
async def test_connection_insert_is_disabled_and_never_overwrites_an_account(monkeypatch):
    session = Session(Result(row=connection_row()))
    install(monkeypatch, session)
    created = await SqlChannelRepository().create_connection(
        tenant_id=TENANT, installation_id="telegram-bot",
        provider_account_id="telegram-account",
        credential_handle="vault://telegram",
    )
    assert created and not created.enabled and created.revision == 1
    query, args = session.calls[0]
    assert "ON CONFLICT DO NOTHING" in query
    assert "false, 1" in query
    assert "CAST(:tenant AS uuid)" in query
    assert args["tenant"] == TENANT
    assert args["credential"] == "vault://telegram"


@pytest.mark.asyncio
async def test_duplicate_account_returns_no_connection(monkeypatch):
    session = Session(Result(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().create_connection(
        tenant_id=TENANT, installation_id="telegram-bot",
        provider_account_id="telegram-account", credential_handle="vault://telegram",
    ) is None


@pytest.mark.asyncio
async def test_issue_revokes_previous_code_and_never_stores_plaintext(monkeypatch):
    session = Session(Result(), Result(scalar="cccccccc-cccc-cccc-cccc-cccccccccccc"))
    install(monkeypatch, session)
    key = await SqlChannelRepository().issue_link_challenge(
        tenant_id=TENANT, connection_id="conn", user_id=USER,
        proof_digest=DIGEST, ttl_seconds=600,
    )
    assert key == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    first, second = session.calls
    assert "SET revoked_at = clock_timestamp()" in first[0]
    assert "consumed_at IS NULL AND revoked_at IS NULL" in first[0]
    assert "public.channel_link_challenges" in second[0]
    assert "c.enabled = true" in second[0]
    assert "u.is_active = true AND u.is_verified = true" in second[0]
    assert "c.revision" in second[0]
    assert "now() + make_interval(secs => :ttl)" in second[0]
    assert second[1]["digest"] == DIGEST
    assert TOKEN not in str(session.calls)


@pytest.mark.asyncio
async def test_consume_verified_link_uses_database_identity_and_one_use_lock(monkeypatch):
    session = Session(Result(row=binding_row()))
    install(monkeypatch, session)
    binding = await SqlChannelRepository().consume_verified_link(
        connection=connection(), external_sender_id="901", proof_digest=DIGEST,
    )
    assert binding is not None and binding.user_id == USER
    assert binding.external_sender_id == "901"
    query, args = session.calls[0]
    for condition in (
        "FOR UPDATE OF p",
        "p.expires_at > clock_timestamp()",
        "p.consumed_at IS NULL AND p.revoked_at IS NULL",
        "c.revision = p.connection_revision",
        "c.enabled = true",
        "u.is_active = true AND u.is_verified = true",
        "ON CONFLICT (tenant_id, connection_id, external_sender_id)",
        "DO NOTHING",
        "UPDATE public.channel_link_challenges p",
        "SET consumed_at = clock_timestamp()",
        "EXISTS (SELECT 1 FROM consumed)",
    ):
        assert condition in query
    assert args["tenant"] == TENANT
    assert args["sender"] == "901"
    assert args["digest"] == DIGEST
    assert "user" not in args and TOKEN not in str(session.calls)


@pytest.mark.asyncio
async def test_consumed_or_revoked_or_duplicate_link_is_not_accepted(monkeypatch):
    session = Session(Result(row=None))
    install(monkeypatch, session)
    assert await SqlChannelRepository().consume_verified_link(
        connection=connection(), external_sender_id="901", proof_digest=DIGEST,
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("digest,ttl", [
    ("abc", 600), ("g" * 64, 600), (DIGEST, 10), (DIGEST, 1000),
])
async def test_invalid_proof_never_queries_database(digest, ttl):
    with pytest.raises(ValueError):
        await SqlChannelRepository().issue_link_challenge(
            tenant_id=TENANT, connection_id="conn", user_id=USER,
            proof_digest=digest, ttl_seconds=ttl,
        )


def test_link_schema_enforces_tenant_foreign_keys_one_use_and_rls():
    path = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20261017020000_32_channel_link_proof.sql"
    )
    sql = path.read_text()
    assert "FOREIGN KEY (tenant_id, user_id)" in sql
    assert "FOREIGN KEY (tenant_id, connection_id)" in sql
    assert "consumed_at IS NULL AND revoked_at IS NULL" in sql
    assert "expires_at <= created_at + interval '15 minutes'" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app.current_tenant_id" in sql
    assert "proof_digest char(64) NOT NULL" in sql
    assert "secret_token text" not in sql.lower()
