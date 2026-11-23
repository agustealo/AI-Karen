"""KIS-GRAPH-01C2R-K: real PostgreSQL auth and transcript across HTTP/SSE.

This test keeps Karen's authentic FastAPI ingress, SecureAuthMiddleware,
AuthService.validate_session, PostgreSQL conversation repository and canonical
ConversationRuntimeGateway. It replaces only model-token production, not
session authorization or transcript storage. No deployed-host, actual model
cancellation, or full ChatRuntime orchestration claim is made.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.auth import auth_middleware, auth_service
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk, ChatStreamEventType,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.database.models import AuthSession, AuthUser, Base, Tenant
from ai_karen_engine.services.auth.auth_service import AuthService
from ai_karen_engine.services.auth.config import AuthConfig, Environment
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


@pytest.mark.asyncio
@pytest.mark.timeout(100)
async def test_live_postgres_authenticated_sse_disconnect_and_transcript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real PostgreSQL authorization, wire-level abort, commit, replay, isolation."""
    if os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1":
        pytest.skip("requires an explicitly marked disposable PostgreSQL database")
    dsn = os.getenv("CHAT_TEST_DATABASE_URL", "")
    parsed = urlparse(dsn)
    if (
        parsed.scheme != "postgresql+asyncpg"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port != 5432
        or parsed.path != "/ai_karen"
    ):
        raise ValueError("Refusing non-disposable/non-loopback database")

    report_path = Path(os.getenv(
        "KAREN_CHAT_AUTH_TRANSCRIPT_REPORT",
        str(tmp_path / "chat-auth-transcript-postgres.json"),
    ))
    if report_path.suffix != ".json":
        raise ValueError("PostgreSQL SSE evidence must use JSON format")

    identity = [(uuid4(), uuid4()), (uuid4(), uuid4())]
    (tenant_a, user_a), (tenant_b, user_b) = identity
    issued_at = datetime.now(timezone.utc)
    secret = f"postgres-wire-{uuid4().hex}{uuid4().hex}"
    config = AuthConfig(
        environment=Environment.LOCAL,
        jwt_secret_key=secret,
        bcrypt_rounds=10,
    )
    engine = create_async_engine(dsn, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    auth = AuthService(config)
    auth._initialized = True

    # Reuse AuthService.validate_session's real SQL. Only the test DB factory
    # is selected here; no mock of validate_session, queries or outcomes.
    @asynccontextmanager
    async def auth_db_scope():
        async with sessions() as session:
            yield session

    auth._session_scope = auth_db_scope
    canonical_auth = object.__new__(auth_middleware.SecureAuthMiddleware)
    canonical_auth.jwt_secret = secret
    canonical_auth.jwt_algorithm = "HS256"
    canonical_auth.redis_client = None
    monkeypatch.setattr(
        auth_middleware, "get_auth_middleware", lambda: canonical_auth,
    )

    async def get_real_auth() -> AuthService:
        return auth

    monkeypatch.setattr(auth_service, "get_auth_service", get_real_auth)
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)

    def signed(owner: UUID, tenant: UUID, *, signing_key: str = secret) -> str:
        return jwt.encode({
            "sub": str(owner),
            "tenant_id": str(tenant),
            "iss": "ai-karen",
            "aud": "ai-karen-users",
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(minutes=10)).timestamp()),
            "roles": ["admin"],  # DB must supersede stale caller claims
            "permissions": ["unauthorized:grant"],
            "email": "stale@example.invalid",
        }, signing_key, algorithm="HS256")

    bearer_a, bearer_b = signed(user_a, tenant_a), signed(user_b, tenant_b)
    forged = signed(user_a, tenant_a, signing_key="wrong-signing-secret")
    cross_tenant = signed(user_b, tenant_a)
    initial_sessions = [
        (user_a, bearer_a),
        (user_b, bearer_b),
        (user_b, cross_tenant),
    ]

    gateway = ConversationRuntimeGateway(
        repository=PostgresConversationRepository(session_factory=sessions),
    )

    class ControlledModelProducer:
        """Only model token generation is controlled, never PostgreSQL writes."""

        def __init__(self) -> None:
            self.requests = []
            self.commits = []
            self.aborted = asyncio.Event()
            self.interrupt_started = asyncio.Event()
            self.interrupt_once = True

        async def execute_stream(self, request):
            self.requests.append(request)
            message = request.messages[-1]["content"]
            should_interrupt = message == "repeat-this-question" and self.interrupt_once
            if should_interrupt:
                self.interrupt_once = False
            try:
                yield ChatStreamChunk(
                    type=ChatStreamEventType.CONTENT,
                    content="canonical response body",
                    correlation_id=request.context.correlation_id,
                )
                if should_interrupt:
                    self.interrupt_started.set()
                    await asyncio.Event().wait()
                receipt = await gateway.persist_completed_turn(
                    request.context,
                    user_text=message,
                    assistant_text="canonical response body",
                    response_metadata={
                        "actual_provider": "controlled-wire-provider",
                        "actual_model": "controlled-model",
                        "response_source": "controlled_model_fixture",
                    },
                )
                if receipt.status != "persisted" or receipt.persisted_messages != 2:
                    raise RuntimeError("canonical_transcript_commit_not_verified")
                self.commits.append((request, receipt))
                yield ChatStreamChunk(
                    type=ChatStreamEventType.COMPLETE,
                    content="",
                    correlation_id=request.context.correlation_id,
                    metadata={
                        "transcript_persistence_status": "persisted",
                        "conversation_id": receipt.conversation_id,
                        "user_message_id": receipt.user_message_id,
                        "assistant_message_id": receipt.assistant_message_id,
                    },
                )
            finally:
                if should_interrupt:
                    self.aborted.set()

    producer = ControlledModelProducer()
    monkeypatch.setattr(ingress, "get_chat_runtime", lambda: producer)

    report = {
        "schema_version": 1,
        "test": "KIS-GRAPH-01C2R-K",
        "status": "incomplete",
        "transport": "real_loopback_tcp_uvicorn_httpx",
        "jwt_authority": "real_secure_auth_middleware",
        "durable_session_authority": "real_auth_service_postgresql",
        "transcript_authority": "real_conversation_runtime_gateway_postgresql",
        "model_tokens": "controlled_fixture",
        "authorization_denials": 0,
        "completed_streams": 0,
        "durable_message_rows": 0,
        "aborted_transcript_rows": None,
        "disconnect_finalized": False,
        "retry_committed_pair": False,
        "tenant_history_isolation": False,
        "scope_guard": "local_disposable_ai_karen_only",
        "limitations": [
            "Token generation uses a controlled provider, not live inference",
            "Canonical ChatRuntime planning/dispatch is not executed by this fixture",
            "One committed retry follows a disconnected socket; it is not network POST idempotency",
            "No actual browser, reverse proxy, remote worker or model-cancellation proof",
            "No database-to-wire atomic revocation guarantee",
            "Minimal disposable test conversation schema, not a migration rollout",
        ],
    }
    failure_type = None
    cleanup_error_type = None
    server_task = None
    listener = None
    server = None
    seeded = False
    started = time.perf_counter()
    ids_to_clean: list[str] = []

    app = FastAPI()
    app.include_router(ingress.router, prefix="/api")

    def headers(token: str, correlation: str | None = None) -> dict[str, str]:
        value = {"Authorization": f"Bearer {token}"}
        if correlation:
            value["X-Correlation-Id"] = correlation
        return value

    async def exchange(
        client: httpx.AsyncClient, token: str, content: str,
    ) -> tuple[list[dict | str], object]:
        trace = f"postgres-wire-{uuid4().hex[:10]}"
        frames = []
        async with client.stream(
            "POST", "/api/chat/stream",
            headers=headers(token, trace),
            json={"message": content, "session_id": "postgres-wire-session"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-correlation-id"] == trace
            assert response.headers["x-response-id"]
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                value = line[6:]
                frames.append("[DONE]" if value == "[DONE]" else json.loads(value))
        assert [x["type"] if isinstance(x, dict) else x for x in frames] == [
            "content", "complete", "[DONE]",
        ]
        assert frames[0]["correlation_id"] == trace
        assert frames[1]["correlation_id"] == trace
        assert frames[1]["metadata"]["transcript_persistence_status"] == "persisted"
        assert producer.requests[-1].context.roles == ["user"]
        assert producer.requests[-1].context.permissions == []
        return frames, producer.commits[-1]

    try:
        # These schema fixtures are in the disposable CI database ONLY.
        # They match the existing canonical transcript PostgreSQL isolation
        # test and reuse its production-owned repository and transaction path.
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(
                sync,
                tables=[Tenant.__table__, AuthUser.__table__, AuthSession.__table__],
                checkfirst=True,
            ))
            await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    title TEXT,
                    conversation_metadata JSONB DEFAULT '{}'::jsonb,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now(),
                    session_id TEXT,
                    ui_context JSONB DEFAULT '{}'::jsonb,
                    ai_insights JSONB DEFAULT '{}'::jsonb,
                    user_settings JSONB DEFAULT '{}'::jsonb,
                    summary TEXT,
                    tags TEXT[],
                    last_ai_response_id TEXT,
                    tenant_id UUID NOT NULL
                )
            """))
            await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id UUID PRIMARY KEY,
                    conversation_id UUID NOT NULL
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_metadata JSONB DEFAULT '{}'::jsonb,
                    function_call JSONB,
                    function_response JSONB,
                    created_at TIMESTAMP DEFAULT now()
                )
            """))

        async with sessions() as session:
            async with session.begin():
                for index, (tenant, user) in enumerate(identity):
                    session.add(Tenant(
                        id=tenant, name=f"Wire test tenant {index}",
                        slug=f"wire-{tenant.hex}", is_active=True,
                    ))
                    session.add(AuthUser(
                        user_id=user, tenant_id=tenant,
                        email=f"wire-{user.hex}@example.invalid",
                        username=f"wire-{user.hex}", full_name="Wire Test",
                        password_hash="not-used-for-bearer-session",
                        roles=["user"], preferences={},
                        is_verified=True, is_active=True,
                    ))
                await session.flush()
                for index, (user, token) in enumerate(initial_sessions):
                    session.add(AuthSession(
                        session_token=uuid4(), user_id=user,
                        access_token=token,
                        refresh_token=f"wire-{index}-{uuid4().hex}",
                        expires_in=3600, is_active=True,
                    ))
        seeded = True

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            app, log_level="error", lifespan="off", access_log=False,
        ))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        for _ in range(300):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise AssertionError("Uvicorn failed to start")
            await asyncio.sleep(0.025)
        assert server.started

        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(8.0, connect=3.0),
            trust_env=False,
        ) as client:
            for token in (None, forged, cross_tenant):
                before = len(producer.requests)
                response = await client.post(
                    "/api/chat/stream",
                    json={"message": "not-authorized"},
                    headers=headers(token) if token else {},
                )
                assert response.status_code == 401
                assert len(producer.requests) == before
                report["authorization_denials"] += 1

            # First attempt releases a visible content frame, then physically
            # loses its HTTP consumer before complete/DB commit.
            async with client.stream(
                "POST", "/api/chat/stream",
                headers=headers(bearer_a),
                json={
                    "message": "repeat-this-question",
                    "session_id": "postgres-wire-session",
                },
            ) as response:
                assert response.status_code == 200
                first = None
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        first = json.loads(line[6:])
                        break
                assert first and first["type"] == "content"
            await asyncio.wait_for(producer.aborted.wait(), timeout=7)
            assert producer.interrupt_started.is_set()
            assert not producer.commits
            report["disconnect_finalized"] = True

            async with sessions() as session:
                message_count = (await session.execute(
                    text("SELECT COUNT(*) FROM messages"),
                )).scalar_one()
                conversation_count = (await session.execute(
                    text("SELECT COUNT(*) FROM conversations"),
                )).scalar_one()
                assert message_count == 0 and conversation_count == 0
            report["aborted_transcript_rows"] = 0

            # Retry is a new authenticated HTTP request with the same user
            # text. Since the first attempt wrote no rows, this one can
            # commit exactly one canonical user/assistant pair.
            frames_a, (request_a, receipt_a) = await exchange(
                client, bearer_a, "repeat-this-question",
            )
            ids_to_clean.append(receipt_a.conversation_id)
            assert len(producer.commits) == 1
            assert frames_a[1]["metadata"]["conversation_id"] == receipt_a.conversation_id
            assert receipt_a.persisted_messages == 2
            report["completed_streams"] += 1
            report["retry_committed_pair"] = True

            frames_b, (request_b, receipt_b) = await exchange(
                client, bearer_b, "tenant-b-independent-turn",
            )
            ids_to_clean.append(receipt_b.conversation_id)
            assert request_a.context.user_id == str(user_a)
            assert request_a.context.tenant_id == str(tenant_a)
            assert request_b.context.user_id == str(user_b)
            assert request_b.context.tenant_id == str(tenant_b)
            assert receipt_a.conversation_id != receipt_b.conversation_id
            report["completed_streams"] += 1

            # True committed readback through the canonical owner gateway
            # and fresh repository transaction, not the streaming fixture.
            from dataclasses import replace
            snapshot_a = await gateway.get_owned_snapshot(replace(
                request_a.context, conversation_id=receipt_a.conversation_id,
            ))
            snapshot_b = await gateway.get_owned_snapshot(replace(
                request_b.context, conversation_id=receipt_b.conversation_id,
            ))
            assert [r.role for r in snapshot_a.messages] == ["user", "assistant"]
            assert [r.role for r in snapshot_b.messages] == ["user", "assistant"]
            assert [r.content for r in snapshot_a.messages] == [
                "repeat-this-question", "canonical response body",
            ]
            assert [r.content for r in snapshot_b.messages] == [
                "tenant-b-independent-turn", "canonical response body",
            ]
            assert snapshot_a.messages[1].metadata["response_source"] == (
                "controlled_model_fixture"
            )
            assert snapshot_a.messages[1].metadata["authorized_user_id"] == str(user_a)

            # Cross-tenant and same-tenant ownership checks are enforced by
            # ConversationRuntimeGateway before any transcript is disclosed.
            foreign = replace(
                request_b.context, conversation_id=receipt_a.conversation_id,
            )
            with pytest.raises(RuntimeError, match="conversation_not_found"):
                await gateway.get_owned_snapshot(foreign)
            foreign_write = await gateway.persist_completed_turn(
                foreign, user_text="foreign edit",
                assistant_text="must never persist",
            )
            assert foreign_write.status == "rejected"
            report["tenant_history_isolation"] = True

            # Canonical same-request replay is idempotent at the repository.
            # This is NOT a claim of HTTP network POST idempotency.
            duplicate = await gateway.persist_completed_turn(
                request_a.context,
                user_text="repeat-this-question",
                assistant_text="canonical response body",
                response_metadata={"response_source": "controlled_model_fixture"},
            )
            assert duplicate.status == "already_persisted"
            assert duplicate.persisted_messages == 0

            # The signed access token remains cryptographically valid. Only
            # committed PostgreSQL session revocation can now deny it.
            async with sessions() as session:
                async with session.begin():
                    row = (await session.execute(select(AuthSession).where(
                        AuthSession.user_id == user_a,
                        AuthSession.access_token == bearer_a,
                    ))).scalar_one()
                    row.is_active = False
                    row.invalidated_at = datetime.utcnow()
                    row.invalidation_reason = "ci_wire_revocation"

            before = len(producer.requests)
            response = await client.post(
                "/api/chat/stream",
                headers=headers(bearer_a),
                json={"message": "revoked-should-not-execute"},
            )
            assert response.status_code == 401
            assert len(producer.requests) == before
            report["authorization_denials"] += 1

        async with sessions() as session:
            count = (await session.execute(text(
                "SELECT count(*) FROM messages WHERE conversation_id IN "
                "(:a, :b)"
            ), {
                "a": UUID(receipt_a.conversation_id),
                "b": UUID(receipt_b.conversation_id),
            })).scalar_one()
            assert count == 4
            report["durable_message_rows"] = count
        assert engine.pool.checkedout() == 0
        report["status"] = "complete"
    except BaseException as exc:
        failure_type = type(exc).__name__
        raise
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            try:
                await asyncio.wait_for(server_task, timeout=10)
            except BaseException as exc:
                cleanup_error_type = type(exc).__name__
                server_task.cancel()
        if listener is not None:
            listener.close()
        if seeded:
            try:
                async with sessions() as session:
                    async with session.begin():
                        for conversation_id in ids_to_clean:
                            await session.execute(text(
                                "DELETE FROM messages WHERE conversation_id = :id",
                            ), {"id": UUID(conversation_id)})
                            await session.execute(text(
                                "DELETE FROM conversations WHERE conversation_id = :id",
                            ), {"id": UUID(conversation_id)})
                        await session.execute(delete(AuthSession).where(
                            AuthSession.user_id.in_([user_a, user_b]),
                        ))
                        await session.execute(delete(AuthUser).where(
                            AuthUser.user_id.in_([user_a, user_b]),
                        ))
                        await session.execute(delete(Tenant).where(
                            Tenant.id.in_([tenant_a, tenant_b]),
                        ))
            except BaseException as exc:
                cleanup_error_type = type(exc).__name__
        try:
            checked_out = engine.pool.checkedout()
        except BaseException:
            checked_out = -1
        report["checked_out_after_cleanup"] = checked_out
        try:
            await engine.dispose()
        except BaseException as exc:
            cleanup_error_type = type(exc).__name__
        report["error_type"] = failure_type
        report["cleanup_error_type"] = cleanup_error_type
        report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if failure_type is not None or cleanup_error_type is not None or checked_out:
            report["status"] = "incomplete"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if failure_type is None:
            assert cleanup_error_type is None
            assert checked_out == 0
