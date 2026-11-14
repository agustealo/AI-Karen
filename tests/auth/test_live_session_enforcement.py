"""Durable active-session enforcement for every protected auth request.

Run against the canonical AuthService and SecureAuthMiddleware with controlled
database/session fixtures. No network, login bypass, or fabricated JWT success.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest

from ai_karen_engine.auth import auth_service as auth_facade
from ai_karen_engine.auth.auth_middleware import (
    AuthenticationError,
    SecureAuthMiddleware,
)
from ai_karen_engine.services.auth.auth_service import AuthService


USER_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
JWT_SECRET = "session-contract-test-secret"


def token(tenant_id: str = TENANT_ID) -> str:
    return jwt.encode(
        {
            "sub": USER_ID,
            "tenant_id": tenant_id,
            "roles": ["admin"],
            "permissions": ["legacy:grant"],
            "email": "old@example.org",
            "iss": "ai-karen",
            "aud": "ai-karen-users",
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp()),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def account(tenant_id: str = TENANT_ID):
    return SimpleNamespace(
        id=USER_ID,
        tenant_id=tenant_id,
        roles=["user"],
        email="current@example.org",
    )


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []


class FakeDbSession:
    def __init__(self, *rows, fail_commit: bool = False):
        self.rows = list(rows)
        self.statements = []
        self.flushed = False
        self.committed = False
        self.fail_commit = fail_commit
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.rows:
            raise AssertionError("Unexpected extra database query")
        return FakeResult(self.rows.pop(0))

    async def flush(self):
        self.flushed = True

    async def commit(self):
        if self.fail_commit:
            raise OSError("commit unavailable")
        self.committed = True

    def add(self, row):
        self.added.append(row)


def session_service(db: FakeDbSession):
    service = object.__new__(AuthService)
    service._initialized = True
    service._config = SimpleNamespace(
        jwt_secret_key=JWT_SECRET,
        jwt_algorithm="HS256",
    )
    service._user_cache = {}

    @asynccontextmanager
    async def scope():
        yield db

    service._session_scope = scope
    service._build_user_account = lambda user: account(str(user.tenant_id))
    return service


@pytest.mark.asyncio
async def test_revoked_session_rejects_still_signed_access_token():
    db = FakeDbSession(None)
    svc = session_service(db)

    assert await svc.validate_session(token()) is None
    assert len(db.statements) == 1
    sql = str(db.statements[0])
    assert "auth_sessions.user_id" in sql
    assert "auth_sessions.is_active" in sql
    assert "auth_sessions.access_token" in sql


@pytest.mark.asyncio
async def test_active_session_returns_only_matching_durable_tenant():
    active = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        access_token=token(),
        is_active=True,
        device_fingerprint=None,
        expires_in=3600,
        created_at=datetime.utcnow(),
        last_accessed=None,
    )
    principal = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        is_active=True,
        is_verified=True,
    )
    db = FakeDbSession(active, principal)
    svc = session_service(db)

    result = await svc.validate_session(token())
    assert result is not None
    assert result.tenant_id == TENANT_ID
    assert db.flushed
    assert len(db.statements) == 2


@pytest.mark.asyncio
async def test_stale_tenant_claim_is_rejected_even_with_active_database_row():
    active = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        is_active=True,
        device_fingerprint=None,
        expires_in=3600,
        created_at=datetime.utcnow(),
    )
    user = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        tenant_id=uuid.UUID(OTHER_TENANT_ID),
        is_active=True,
        is_verified=True,
    )
    db = FakeDbSession(active, user)
    svc = session_service(db)

    assert await svc.validate_session(token()) is None
    assert not db.flushed


@pytest.mark.asyncio
async def test_database_error_never_falls_back_to_jwt_only_access():
    class Down:
        async def execute(self, statement):
            raise OSError("database offline")

    svc = session_service(Down())
    assert await svc.validate_session(token()) is None


@pytest.mark.asyncio
async def test_session_issuance_commits_before_success_and_rejects_commit_failure():
    class FakePersistence:
        def __init__(self, fail: bool):
            self.fail = fail
            self.add_count = 0
            self.flushed = False
            self.committed = False

        def add(self, value):
            assert str(value.user_id) == USER_ID
            self.add_count += 1

        async def flush(self):
            self.flushed = True

        async def commit(self):
            if self.fail:
                raise OSError("commit unavailable")
            self.committed = True

    for should_fail in (False, True):
        db = FakePersistence(should_fail)
        svc = object.__new__(AuthService)
        svc._config = SimpleNamespace(refresh_token_expire_days=30)

        @asynccontextmanager
        async def scope():
            yield db

        svc._session_scope = scope
        issuance = svc._persist_auth_session(
            user_id=USER_ID,
            access_token="signed-access-token",
            refresh_token="opaque-refresh-token",
            ip_address="127.0.0.1",
            user_agent="test-client",
            device_fingerprint="fingerprint",
        )
        if should_fail:
            with pytest.raises(RuntimeError, match="Durable session persistence unavailable"):
                await issuance
        else:
            await issuance
        assert db.add_count == 1
        assert db.flushed
        assert db.committed is not should_fail


@pytest.mark.asyncio
async def test_login_denied_when_durable_session_persistence_fails():
    svc = object.__new__(AuthService)
    svc._initialized = True
    svc._active_sessions = {}
    existing = SimpleNamespace(
        id=USER_ID,
        tenant_id=TENANT_ID,
        status=SimpleNamespace(value="active"),
        locked_until=None,
        is_verified=True,
        password_hash="irrelevant",
    )

    # Real canonical login path, with side effects controlled, must refuse to
    # return an access token when PostgreSQL persistence is unavailable.
    from ai_karen_engine.services.auth.auth_service import UserStatus
    existing.status = UserStatus.ACTIVE
    svc.get_user = AsyncMock(return_value=existing)
    svc._verify_password = lambda *_: True
    svc._reset_failed_login_attempts = AsyncMock()
    svc._update_last_login = AsyncMock()
    svc._generate_access_token = lambda *_: "would-be-access-token"
    svc._generate_refresh_token = lambda: "would-be-refresh-token"
    svc._generate_device_fingerprint = lambda *_: "fingerprint"
    svc._persist_auth_session = AsyncMock(
        side_effect=RuntimeError("Durable session persistence unavailable")
    )

    user, access, error = await svc.authenticate_user("user@example.org", "secret")
    assert user is None and access is None
    assert error == "Authentication failed"
    assert svc._active_sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_commit", [False, True])
async def test_logout_invalidates_only_after_committed_database_revoke(fail_commit):
    row = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        refresh_token="secret-refresh",
        is_active=True,
        invalidated_at=None,
        invalidation_reason=None,
    )
    cache = SimpleNamespace(refresh_token="secret-refresh", is_active=True)
    db = FakeDbSession(row, fail_commit=fail_commit)
    svc = session_service(db)
    svc._active_sessions = {"session": cache}

    if fail_commit:
        with pytest.raises(OSError):
            await svc.logout("secret-refresh")
        assert cache.is_active
    else:
        await svc.logout("secret-refresh")
        assert db.committed
        assert cache.is_active is False
    assert db.flushed
    assert row.invalidation_reason == "logout"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_commit", [False, True])
async def test_password_revocation_and_audit_require_database_commit(fail_commit):
    current_user = SimpleNamespace(password_hash="original", updated_at=None)
    active_session = SimpleNamespace(
        is_active=True, invalidated_at=None, invalidation_reason=None
    )
    db = FakeDbSession(
        current_user, [active_session], fail_commit=fail_commit
    )
    svc = session_service(db)
    cached = SimpleNamespace(user_id=USER_ID, is_active=True)
    svc._active_sessions = {"session": cached}
    svc._user_cache = {USER_ID: account()}
    svc._validate_password = lambda password: None
    svc._verify_password = lambda current, stored: True
    svc._hash_password = lambda password: "new-hash"
    svc._emit_audit_event = AsyncMock()

    error = await svc.change_user_password(
        USER_ID, "old-secret", "new-secret"
    )
    if fail_commit:
        assert error == "Password update failed"
        assert cached.is_active
        svc._emit_audit_event.assert_not_awaited()
    else:
        assert error is None
        assert db.committed
        assert cached.is_active is False
        assert svc._user_cache == {}
        svc._emit_audit_event.assert_awaited_once()
    assert current_user.password_hash == "new-hash"
    assert active_session.invalidation_reason == "password_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_commit", [False, True])
async def test_refresh_rotation_and_audit_require_database_commit(fail_commit):
    live_session = SimpleNamespace(
        session_token=uuid.uuid4(),
        user_id=uuid.UUID(USER_ID),
        created_at=datetime.utcnow(),
        expires_in=3600,
        access_token="old-access",
        refresh_token="old-refresh",
        is_active=True,
        last_accessed=None,
    )
    db_user = SimpleNamespace(
        user_id=uuid.UUID(USER_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        is_active=True,
    )
    db = FakeDbSession(None, live_session, db_user, fail_commit=fail_commit)
    svc = session_service(db)
    cached = SimpleNamespace(
        refresh_token="old-refresh",
        access_token="old-access",
        is_active=True,
        last_used=None,
    )
    svc._active_sessions = {"session": cached}
    svc._generate_access_token = lambda user: "new-access"
    svc._generate_refresh_token = lambda: "new-refresh"
    svc._emit_audit_event = AsyncMock()

    access, refresh, error = await svc.refresh_access_token("old-refresh")
    if fail_commit:
        assert (access, refresh, error) == (None, None, "Database unavailable")
        assert cached.access_token == "old-access"
        assert cached.refresh_token == "old-refresh"
        svc._emit_audit_event.assert_not_awaited()
    else:
        assert (access, refresh, error) == ("new-access", "new-refresh", None)
        assert db.committed
        assert cached.access_token == "new-access"
        assert cached.refresh_token == "new-refresh"
        svc._emit_audit_event.assert_awaited_once()
    assert db.flushed
    assert len(db.added) == 1


def middleware():
    instance = object.__new__(SecureAuthMiddleware)
    instance.is_public_endpoint = lambda path: path.startswith("/api/auth/login")
    instance._extract_token_from_request = lambda request: "signed-token"
    instance._extract_session_token_from_request = lambda request: None
    instance._verify_access_token = lambda value: {
        "sub": USER_ID,
        "tenant_id": TENANT_ID,
        "roles": ["admin"],
        "email": "old@example.org",
        "permissions": ["legacy:grant"],
    }
    return instance


@pytest.mark.asyncio
async def test_middleware_uses_backend_roles_not_stale_jwt_claims(monkeypatch):
    authoritative = SimpleNamespace(validate_session=AsyncMock(return_value=account()))

    async def auth_svc():
        return authoritative

    monkeypatch.setattr(auth_facade, "get_auth_service", auth_svc)
    result = await middleware().get_current_user(
        SimpleNamespace(url=SimpleNamespace(path="/api/auth/me"))
    )
    assert result["user_id"] == USER_ID
    assert result["tenant_id"] == TENANT_ID
    assert result["roles"] == ["user"]
    assert result["permissions"] == []
    assert result["email"] == "current@example.org"
    authoritative.validate_session.assert_awaited_once_with("signed-token")


@pytest.mark.asyncio
async def test_middleware_refuses_revoked_or_rotated_token(monkeypatch):
    async def auth_svc():
        return SimpleNamespace(validate_session=AsyncMock(return_value=None))

    monkeypatch.setattr(auth_facade, "get_auth_service", auth_svc)

    with pytest.raises(AuthenticationError, match="Session expired or revoked") as exc:
        await middleware().get_current_user(
            SimpleNamespace(url=SimpleNamespace(path="/api/auth/me"))
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_middleware_refuses_cross_tenant_active_session(monkeypatch):
    async def auth_svc():
        return SimpleNamespace(
            validate_session=AsyncMock(return_value=account(OTHER_TENANT_ID))
        )

    monkeypatch.setattr(auth_facade, "get_auth_service", auth_svc)
    with pytest.raises(AuthenticationError, match="identity or tenant mismatch") as exc:
        await middleware().get_current_user(
            SimpleNamespace(url=SimpleNamespace(path="/api/auth/me"))
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_middleware_fails_closed_when_database_unavailable(monkeypatch):
    async def auth_svc():
        raise OSError("private database detail")

    monkeypatch.setattr(auth_facade, "get_auth_service", auth_svc)
    with pytest.raises(AuthenticationError, match="Session verification unavailable") as exc:
        await middleware().get_current_user(
            SimpleNamespace(url=SimpleNamespace(path="/api/auth/me"))
        )
    assert exc.value.status_code == 503
    assert "private" not in str(exc.value)


@pytest.mark.asyncio
async def test_public_login_remains_unauthenticated_without_valid_session(monkeypatch):
    async def auth_svc():
        return SimpleNamespace(validate_session=AsyncMock(return_value=None))

    monkeypatch.setattr(auth_facade, "get_auth_service", auth_svc)
    result = await middleware().get_current_user(
        SimpleNamespace(url=SimpleNamespace(path="/api/auth/login"))
    )
    assert result["authenticated"] is False
    assert result["tenant_id"] is None
