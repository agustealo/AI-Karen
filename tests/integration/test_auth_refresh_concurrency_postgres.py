from __future__ import annotations

import asyncio
import hashlib
import os
import uuid

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.database.models import AuthSession, AuthUser, Base, Tenant
from ai_karen_engine.database.models.session_security import AuthRefreshTokenHistory
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.services.auth.config import AuthConfig, Environment


pytestmark = pytest.mark.asyncio


def _auth_config() -> AuthConfig:
    return AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key="postgres-concurrency-test-secret-32-bytes-minimum",
        bcrypt_rounds=10,
    )


async def test_same_refresh_token_concurrency_allows_one_rotation_then_revokes_family() -> None:
    database_url = os.environ["AUTH_TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    ordered_tables = [
        Tenant.__table__,
        AuthUser.__table__,
        AuthSession.__table__,
        AuthRefreshTokenHistory.__table__,
    ]

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.drop_all(
                sync_connection,
                tables=list(reversed(ordered_tables)),
                checkfirst=True,
            )
        )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=ordered_tables,
                checkfirst=True,
            )
        )

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    refresh_token = "R1-concurrent-refresh-token"

    seed_service = AuthService(_auth_config())
    seed_service._initialized = True

    async with session_factory() as db_session:
        async with db_session.begin():
            db_session.add(
                Tenant(
                    id=tenant_id,
                    name="Refresh Concurrency Tenant",
                    slug="refresh-concurrency",
                    subscription_tier="basic",
                    settings={},
                    is_active=True,
                )
            )
            db_session.add(
                AuthUser(
                    user_id=user_id,
                    email="concurrency@example.test",
                    username="concurrency",
                    full_name="Concurrency Test",
                    password_hash=seed_service._hash_password("Original1!"),
                    tenant_id=tenant_id,
                    roles=["user"],
                    preferences={},
                    is_verified=True,
                    is_active=True,
                )
            )
            db_session.add(
                AuthSession(
                    session_token=session_id,
                    user_id=user_id,
                    access_token="initial-access-token",
                    refresh_token=refresh_token,
                    expires_in=3600,
                    is_active=True,
                )
            )

    async def rotate_once() -> tuple[str | None, str | None, str | None]:
        service = AuthService(_auth_config())
        service._initialized = True
        async with session_factory() as db_session:
            async with db_session.begin():
                service.set_db_session(db_session)
                return await service.refresh_access_token(refresh_token)

    first, second = await asyncio.gather(rotate_once(), rotate_once())
    results = [first, second]

    successes = [result for result in results if result[2] is None]
    replays = [result for result in results if result[2] == "Refresh token replay detected"]

    assert len(successes) == 1
    assert len(replays) == 1
    assert successes[0][0]
    assert successes[0][1]
    assert successes[0][1] != refresh_token

    rotated_access_token = successes[0][0]
    assert rotated_access_token is not None
    decoded = jwt.decode(
        rotated_access_token,
        _auth_config().jwt_secret_key,
        algorithms=[_auth_config().jwt_algorithm],
        options={"verify_aud": False},
    )
    assert decoded["tenant_id"] == str(tenant_id)

    async with session_factory() as db_session:
        session_result = await db_session.execute(
            select(AuthSession).where(AuthSession.session_token == session_id)
        )
        durable_session = session_result.scalar_one()

        history_result = await db_session.execute(
            select(AuthRefreshTokenHistory).where(
                AuthRefreshTokenHistory.session_id == session_id
            )
        )
        history = history_result.scalars().all()

        assert durable_session.is_active is False
        assert durable_session.invalidation_reason == "refresh_token_replay"
        assert len(history) == 1
        assert history[0].token_hash == hashlib.sha256(refresh_token.encode()).hexdigest()
        assert history[0].replayed_at is not None

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.drop_all(
                sync_connection,
                tables=list(reversed(ordered_tables)),
                checkfirst=True,
            )
        )
    await engine.dispose()


@pytest.mark.parametrize("winner", ["revocation", "persistence"])
@pytest.mark.parametrize("target", ["transcript", "memory"])
async def test_private_session_fence_serializes_revocation(winner, target, monkeypatch):
    """Exercise real auth row locks against both canonical mutation owners."""
    from contextlib import asynccontextmanager
    from ai_karen_engine.core.memory.protocols import VaultContext
    from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata
    from ai_karen_engine.platform.memory.postgres.ledger_models import (
        Base as LedgerBase, ConsentScope, MemoryAssertion, MemoryEvent, RetentionPolicy,
    )
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError, PostgresNeuroVault,
    )
    from datetime import datetime
    from sqlalchemy import text
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.auth import auth_service
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.services.database.repositories.conversation_repository import Message
    from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
        PostgresConversationRepository,
    )

    engine = create_async_engine(os.environ["AUTH_TEST_DATABASE_URL"], pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tables = [Tenant.__table__, AuthUser.__table__, AuthSession.__table__]
    service = AuthService(_auth_config())
    service._initialized = True
    tenant, user, session, conversation = [uuid.uuid4() for _ in range(4)]
    access = jwt.encode(
        {"sub": str(user), "tenant_id": str(tenant), "aud": "ai-karen-users",
         "iss": "ai-karen", "exp": int(__import__("time").time()) + 3600},
        service.config.jwt_secret_key, algorithm=service.config.jwt_algorithm,
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        if target == "memory":
            await conn.run_sync(lambda sync: LedgerBase.metadata.create_all(
                sync, tables=[MemoryEvent.__table__, MemoryAssertion.__table__,
                              ConsentScope.__table__, RetentionPolicy.__table__],
            ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
                user_id UUID NOT NULL, conversation_metadata JSONB NOT NULL DEFAULT '{}'
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id UUID PRIMARY KEY, conversation_id UUID NOT NULL
                    REFERENCES conversations(conversation_id),
                role TEXT NOT NULL, content TEXT NOT NULL,
                message_metadata JSONB, created_at TIMESTAMP
            )
        """))
    try:
        async with factory.begin() as db:
            db.add(Tenant(id=tenant, name=str(tenant), slug=str(tenant),
                          subscription_tier="basic", settings={}, is_active=True))
            db.add(AuthUser(user_id=user, tenant_id=tenant, email=f"{user}@example.test",
                            username=str(user), password_hash="test-only", roles=["admin"],
                            preferences={}, is_active=True, is_verified=True))
            await db.flush()
            db.add(AuthSession(session_token=session, user_id=user, access_token=access,
                               refresh_token=str(uuid.uuid4()), expires_in=3600, is_active=True))
            await db.execute(text("""
                INSERT INTO conversations (conversation_id, tenant_id, user_id)
                VALUES (:cid, :tid, :uid)
            """), {"cid": conversation, "tid": tenant, "uid": user})
        principal = UserData(user_id=str(user), tenant_id=str(tenant),
                             roles=["admin"], permissions=["data:read"])
        context = ChatExecutionContext(
            user_id=str(user), tenant_id=str(tenant), conversation_id=str(conversation),
            session_id="test-session", request_id="fence-test", correlation_id="fence-test",
            authenticated_user=principal,
        )
        async with factory.begin() as db:
            service.set_db_session(db)
            try:
                account, witness = await service.validate_session_with_witness(access)
            finally:
                from ai_karen_engine.services.auth.auth_service import _db_session_ctx
                _db_session_ctx.set(None)
        assert account is not None and witness is not None
        assert service.bind_issued_session_principal(witness, principal)
        assert service.bind_issued_session_execution(witness, principal, context)
        principal._runtime_session_witness = (principal, witness)
        # The repository's fence is under test, not the attachment reader.
        monkeypatch.setattr(ChatExecutionContext, "has_runtime_attachment_scope", lambda self: True)

        async def get_issuer():
            return service

        monkeypatch.setattr(auth_service, "get_auth_service", get_issuer)
        repo = PostgresConversationRepository(session_factory=factory)
        common = {"authorized_user_id": str(user), "request_id": context.request_id,
                  "correlation_id": context.correlation_id}
        pair = [
            Message(id=str(uuid.uuid4()), conversation_id=str(conversation),
                    tenant_id=str(tenant), role=role, content=role,
                    metadata=dict(common), created_at=datetime.utcnow())
            for role in ("user", "assistant")
        ]

        locked = asyncio.Event()
        release = asyncio.Event()
        original = service.revalidate_issued_session_in_transaction

        async def paused_fence(*args, **kwargs):
            account = await original(*args, **kwargs)
            if winner == "persistence":
                locked.set()
                await release.wait()
            return account

        monkeypatch.setattr(service, "revalidate_issued_session_in_transaction", paused_fence)

        async def revoke():
            async with factory.begin() as db:
                row = (await db.execute(select(AuthSession).where(
                    AuthSession.session_token == session
                ).with_for_update())).scalar_one()
                row.is_active = False
                await db.flush()
                if winner == "revocation":
                    locked.set()
                    await release.wait()

        @asynccontextmanager
        async def vault_session():
            async with factory() as db:
                await db.begin()
                try:
                    yield db
                finally:
                    if db.in_transaction():
                        await db.rollback()

        vault = PostgresNeuroVault(session_factory=vault_session)
        vault_context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=context.request_id, correlation_id=context.correlation_id,
            session_id=context.session_id, conversation_id=context.conversation_id,
            actor_id=str(user), policy_context={"memory_write_authorized": True},
            private_execution=context,
        )
        entry = MemoryEntry(
            id=str(uuid.uuid4()), content="Synthetic private memory concurrency proof",
            metadata=MemoryMetadata(tenant_id=str(tenant), user_id=str(user), source="chat_user"),
        )

        async def persist():
            if target == "transcript":
                return await repo.add_completed_turn(*pair, private_execution=context)
            try:
                return await vault.persist(entry, context=vault_context)
            except NeuroVaultAuthorizationError as exc:
                return exc

        first = asyncio.create_task(revoke() if winner == "revocation" else persist())
        second = None
        try:
            await asyncio.wait_for(locked.wait(), 10)
            second = asyncio.create_task(persist() if winner == "revocation" else revoke())
            # A competing transaction must not finish while the winner holds its lock.
            done, _ = await asyncio.wait({second}, timeout=0.2)
            assert not done
            release.set()
            results = await asyncio.wait_for(asyncio.gather(first, second), 10)
            receipt = results[1] if winner == "revocation" else results[0]
            if target == "transcript":
                assert receipt.success is (winner == "persistence")
                if winner == "revocation":
                    assert receipt.error == "attachment_session_denied"
            elif winner == "revocation":
                assert isinstance(receipt, NeuroVaultAuthorizationError)
                assert str(receipt) == "attachment_session_denied"
            else:
                assert receipt.persisted is True
            async with factory() as db:
                count = (await db.execute(text(
                    "SELECT count(*) FROM messages WHERE conversation_id = :cid"
                ), {"cid": conversation})).scalar_one()
                active = (await db.execute(select(AuthSession.is_active).where(
                    AuthSession.session_token == session
                ))).scalar_one()
                if target == "memory":
                    from sqlalchemy import func
                    for model in (MemoryEvent, MemoryAssertion):
                        durable_count = (await db.execute(
                            select(func.count()).select_from(model).where(
                                model.tenant_id == tenant, model.user_id == user,
                            )
                        )).scalar_one()
                        assert durable_count == (1 if winner == "persistence" else 0)
            assert count == (2 if winner == "persistence" and target == "transcript" else 0)
            assert active is False
            if target == "memory":
                # A previously successful receipt cannot bypass revoked authority.
                with pytest.raises(NeuroVaultAuthorizationError, match="attachment_session_denied"):
                    await vault.persist(entry, context=vault_context)
        finally:
            release.set()
            for task in (first, second):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (first, second) if task is not None),
                                 return_exceptions=True)
    finally:
        async with factory.begin() as db:
            await db.execute(text("DELETE FROM messages WHERE conversation_id = :cid"), {"cid": conversation})
            await db.execute(text("DELETE FROM conversations WHERE conversation_id = :cid"), {"cid": conversation})
            from sqlalchemy import delete
            if target == "memory":
                await db.execute(delete(MemoryAssertion).where(MemoryAssertion.tenant_id == tenant))
                await db.execute(delete(MemoryEvent).where(MemoryEvent.tenant_id == tenant))
            await db.execute(delete(AuthSession).where(AuthSession.session_token == session))
            await db.execute(delete(AuthUser).where(AuthUser.user_id == user))
            await db.execute(delete(Tenant).where(Tenant.id == tenant))
        await engine.dispose()
