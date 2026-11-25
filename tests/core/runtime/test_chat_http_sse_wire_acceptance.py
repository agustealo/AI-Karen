"""KIS-GRAPH-01C2R-J: observed canonical SSE over a real HTTP socket.

A genuine Uvicorn listener and httpx TCP client exercise the actual FastAPI
chat ingress, signed JWT verification and strict session-identity checks.
The canonical AuthService's durable-session result and ChatRuntime's model
stream are controlled, not claims of real PostgreSQL authentication or inference.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
import uvicorn
from fastapi import FastAPI

from ai_karen_engine.api_routes.chat import runtime as chat_ingress
from ai_karen_engine.auth import auth_middleware, auth_service
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk, ChatStreamEventType,
)
from ai_karen_engine.core.security.auth_config import auth_config


@pytest.mark.asyncio
@pytest.mark.timeout(65)
async def test_canonical_chat_sse_over_signed_authenticated_http_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    owner_a, owner_b = str(uuid4()), str(uuid4())
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    secret = f"wire-contract-{uuid4().hex}{uuid4().hex}"
    session_records: dict[str, SimpleNamespace] = {}
    verified_tokens: list[str] = []

    class CanonicalSessionProbe(auth_service.AuthService):
        """Real AuthService witness sealing; only PostgreSQL readback is controlled."""

        def __init__(self):
            self._runtime_witness_key = secrets.token_bytes(32)

        async def validate_session(
            self, token: str, *, strict_errors: bool = False,
            _witness_sink=None,
        ) -> SimpleNamespace | None:
            assert strict_errors is True
            verified_tokens.append(token)
            account = session_records.get(token)
            if account is not None and _witness_sink is not None:
                _witness_sink(self._issue_session_witness(
                    session_id=account.session_id, user_id=account.id,
                    tenant_id=account.tenant_id,
                    access_token_digest=hashlib.sha256(
                        token.encode("utf-8")
                    ).hexdigest(),
                ))
            return account

        async def revalidate_session_identity(
            self, *, session_id, user_id, tenant_id, access_token_digest,
        ) -> SimpleNamespace | None:
            for token, account in session_records.items():
                if (
                    account.session_id == session_id
                    and account.id == user_id and account.tenant_id == tenant_id
                    and hashlib.sha256(token.encode("utf-8")).hexdigest()
                    == access_token_digest
                ):
                    return account
            return None

    session_authority = CanonicalSessionProbe()

    async def get_active_session_authority() -> CanonicalSessionProbe:
        return session_authority

    # Keep the actual SecureAuthMiddleware signature, issuer, audience, tenant
    # and session identity validation. Only session storage readback is a probe.
    auth = object.__new__(auth_middleware.SecureAuthMiddleware)
    auth.jwt_secret = secret
    auth.jwt_algorithm = "HS256"
    auth.redis_client = None
    monkeypatch.setattr(
        auth_middleware, "get_auth_middleware", lambda: auth,
    )
    monkeypatch.setattr(
        auth_service, "get_auth_service", get_active_session_authority,
    )
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)

    def bearer(
        owner: str, tenant: str, *,
        signing_secret: str = secret,
    ) -> str:
        issued = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": owner,
                "tenant_id": tenant,
                "email": "stale@example.invalid",
                "roles": ["admin"],
                "permissions": ["unsafe:grant"],
                "iss": "ai-karen",
                "aud": "ai-karen-users",
                "iat": int(issued.timestamp()),
                "exp": int((issued + timedelta(minutes=10)).timestamp()),
            },
            signing_secret,
            algorithm="HS256",
        )

    def register(token: str, owner: str, tenant: str) -> None:
        session_records[token] = SimpleNamespace(
            id=owner, tenant_id=tenant, roles=["user"],
            email="current@example.invalid", status="active",
            is_verified=True, session_id=str(uuid4()),
        )

    token_a, token_b = bearer(owner_a, tenant_a), bearer(owner_b, tenant_b)
    register(token_a, owner_a, tenant_a)
    register(token_b, owner_b, tenant_b)

    class ObservedRuntime:
        def __init__(self) -> None:
            self.requests: list = []
            self.disconnect_finalized = asyncio.Event()
            self.disconnect_started = asyncio.Event()

        async def execute_stream(self, request):
            self.requests.append(request)
            stopping = request.messages[-1]["content"] == "disconnect"
            try:
                yield ChatStreamChunk(
                    type=ChatStreamEventType.CONTENT,
                    content="verified transport fixture",
                    correlation_id=request.context.correlation_id,
                )
                if stopping:
                    self.disconnect_started.set()
                    # Only an actual HTTP socket disconnect can release this.
                    await asyncio.Event().wait()
                yield ChatStreamChunk(
                    type=ChatStreamEventType.COMPLETE,
                    content="",
                    correlation_id=request.context.correlation_id,
                )
            finally:
                if stopping:
                    self.disconnect_finalized.set()

    runtime = ObservedRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: runtime)

    app = FastAPI()
    app.include_router(chat_ingress.router, prefix="/api")
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
    started = time.perf_counter()
    completed = 0
    rejected = 0
    first_content_ms: list[float] = []
    error_type: str | None = None
    cleanup_error_type: str | None = None
    report: dict = {
        "schema_version": 1,
        "test": "KIS-GRAPH-01C2R-J",
        "status": "incomplete",
        "real_tcp_http": True,
        "signed_jwt_verification": "actual",
        "durable_auth_session_readback": "controlled",
        "chat_runtime_model_stream": "controlled",
        "sse_completed": 0,
        "rejected_before_runtime": 0,
        "disconnect_finalized": False,
        "limitations": [
            "AuthService session readback is a controlled fixture, not real PostgreSQL",
            "Model execution and transcript persistence are controlled, not production inference",
            "Local CI TCP observations are not deployment, SLO or DB-to-wire atomicity proof",
        ],
    }

    def headers(token: str, correlation: str | None = None) -> dict[str, str]:
        outgoing = {"Authorization": f"Bearer {token}"}
        if correlation is not None:
            outgoing["X-Correlation-Id"] = correlation
        return outgoing

    async def collect_sse(
        client: httpx.AsyncClient, token: str, *,
        message: str, correlation: str,
    ) -> tuple[list[dict | str], dict[str, str], float]:
        t0 = time.perf_counter()
        frames: list[dict | str] = []
        first_content: float | None = None
        async with client.stream(
            "POST", "/api/chat/stream",
            json={"message": message, "session_id": "wire-session"},
            headers=headers(token, correlation),
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-correlation-id"] == correlation
            assert response.headers.get("x-response-id")
            assert response.headers["cache-control"] == "no-cache"
            wire_headers = dict(response.headers)
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw == "[DONE]":
                    frames.append(raw)
                    continue
                packet = json.loads(raw)
                if packet["type"] == "content" and first_content is None:
                    first_content = (time.perf_counter() - t0) * 1000
                frames.append(packet)
        assert first_content is not None
        return frames, wire_headers, round(first_content, 3)

    try:
        for _ in range(200):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise AssertionError("Uvicorn exited before accepting HTTP traffic")
            await asyncio.sleep(0.025)
        assert server.started, "Socket-backed Uvicorn startup timed out"

        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(7.0, connect=3.0),
            trust_env=False,
        ) as client:
            # Neither unauthenticated requests nor merely signed, revoked,
            # cross-tenant, or wrong-signature claims may enter ChatRuntime.
            forged = bearer(owner_a, tenant_a, signing_secret="wrong-secret")
            register(forged, owner_a, tenant_a)
            mismatched = bearer(owner_b, tenant_a)
            register(mismatched, owner_b, tenant_b)
            for token in (None, forged, mismatched):
                count_before = len(runtime.requests)
                response = await client.post(
                    "/api/chat/stream",
                    json={"message": "should never execute"},
                    headers=headers(token) if token else {},
                )
                assert response.status_code == 401
                assert len(runtime.requests) == count_before
                assert "verified transport fixture" not in response.text
                rejected += 1

            for index in range(8):
                owner, tenant, token = (
                    (owner_a, tenant_a, token_a) if index % 2 == 0
                    else (owner_b, tenant_b, token_b)
                )
                correlation = f"wire-{index}-{uuid4().hex[:12]}"
                frames, _, first_ms = await collect_sse(
                    client, token, message="complete", correlation=correlation,
                )
                assert [f["type"] if isinstance(f, dict) else f
                        for f in frames] == ["content", "complete", "[DONE]"]
                assert frames[0]["content"] == "verified transport fixture"
                assert frames[0]["correlation_id"] == correlation
                assert frames[1]["correlation_id"] == correlation
                request = runtime.requests[-1]
                assert request.context.user_id == owner
                assert request.context.tenant_id == tenant
                assert request.context.roles == ["user"]
                assert request.context.permissions == []
                assert request.metadata["transport"] == "sse"
                first_content_ms.append(first_ms)
                completed += 1

            count_before = len(runtime.requests)
            session_records.pop(token_a)
            response = await client.post(
                "/api/chat/stream",
                json={"message": "revoked session may not run"},
                headers=headers(token_a),
            )
            assert response.status_code == 401
            assert len(runtime.requests) == count_before
            rejected += 1

            # The final proof is a real network disconnect, not .aclose()
            # on an in-process test generator.
            await asyncio.wait_for(
                _disconnect_after_content(client, token_b, runtime),
                timeout=10,
            )
            assert runtime.disconnect_started.is_set()
            await asyncio.wait_for(runtime.disconnect_finalized.wait(), timeout=6)
            assert len(runtime.requests) == completed + 1

        times = sorted(first_content_ms)
        report.update({
            "status": "complete",
            "sse_completed": completed,
            "rejected_before_runtime": rejected,
            "disconnect_finalized": True,
            "first_content_p50_ms": times[(len(times) - 1) // 2],
            "first_content_p95_ms": times[(len(times) * 95 + 99) // 100 - 1],
            "session_validation_calls": len(verified_tokens),
        })
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=10)
        except BaseException as exc:
            cleanup_error_type = type(exc).__name__
            server_task.cancel()
        finally:
            listener.close()
        report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        report["error_type"] = error_type
        report["cleanup_error_type"] = cleanup_error_type
        if error_type is not None or cleanup_error_type is not None:
            report["status"] = "incomplete"
        report_path = Path(os.getenv(
            "KAREN_CHAT_WIRE_REPORT", str(tmp_path / "http-sse-wire-report.json"),
        ))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if error_type is None:
            assert cleanup_error_type is None


async def _disconnect_after_content(
    client: httpx.AsyncClient, token: str, runtime,
) -> None:
    seen_content = False
    async with client.stream(
        "POST", "/api/chat/stream",
        json={"message": "disconnect", "session_id": "wire-session"},
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            packet = json.loads(line[6:])
            if packet["type"] == "content":
                seen_content = True
                break
    assert seen_content
    assert not runtime.disconnect_finalized.is_set() or (
        runtime.disconnect_started.is_set()
    )
