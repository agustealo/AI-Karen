"""
Authentication Service for CoPilot Architecture.

This service provides comprehensive authentication functionality including
user management, session management, and token validation.
"""

import asyncio
import hashlib
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from contextvars import ContextVar
import jwt
import bcrypt
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.core.services.base import BaseService
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.models import AuthUser, AuthSession, Tenant
from ai_karen_engine.database.models.session_security import AuthRefreshTokenHistory
from ai_karen_engine.services.auth.config import AuthConfig, load_auth_config

logger = get_logger(__name__)

# Context variable for thread-safe session management in shared service instances
_db_session_ctx: ContextVar[Optional[AsyncSession]] = ContextVar(
    "auth_db_session", default=None
)

# Stable PostgreSQL advisory-lock key for the one-time first-admin bootstrap.
_FIRST_ADMIN_BOOTSTRAP_LOCK_KEY = 1262571077


class UserRole(str, Enum):
    """User role enumeration."""

    USER = "user"
    ADMIN = "admin"
    SECURITY_OFFICER = "security_officer"
    AGENT = "agent"


class UserStatus(str, Enum):
    """User status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING_VERIFICATION = "pending_verification"


@dataclass
class UserAccount:
    """User account data structure."""

    id: str
    email: str
    username: str
    full_name: str
    password_hash: str
    roles: List[UserRole] = field(default_factory=list)
    status: UserStatus = UserStatus.ACTIVE
    is_verified: bool = True
    two_factor_enabled: bool = False
    two_factor_secret: Optional[str] = None
    password_changed_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    locked_until: Optional[datetime] = None
    failed_login_attempts: int = 0
    preferences: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """Session data structure."""

    id: str
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: datetime = field(default_factory=datetime.utcnow)
    ip_address: str = "unknown"
    user_agent: str = ""
    device_fingerprint: str = ""
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuthService(BaseService):
    """Canonical authentication service.

    Database state is authoritative for users and sessions. The service is not
    considered initialized until configuration validation and the migration-owned
    auth schema preflight have both succeeded.
    """

    def __init__(self, config: Optional[AuthConfig] = None) -> None:
        """Initialize the Authentication Service."""
        self._config = config if config is not None else load_auth_config()
        super().__init__(self._config)
        self._initialized = False
        self._tables_ensured = False
        self._lock: Optional[asyncio.Lock] = None

        # Database session will be injected
        self._db_session: Optional[AsyncSession] = None
        self._db_client: Optional[MultiTenantPostgresClient] = None

        # Bounded runtime caches (optimization only; database is the authority)
        self._active_sessions: Dict[str, Session] = {}
        self._user_cache: Dict[str, UserAccount] = {}

        logger.debug(
            "AuthService initialized with environment=%s, jwt_algorithm=%s",
            self._config.environment.value,
            self._config.jwt_algorithm,
        )

    @property
    def config(self) -> AuthConfig:
        """Return the authenticated configuration."""
        return self._config

    @config.setter
    def config(self, value: AuthConfig) -> None:
        """Set the configuration from BaseService initialization."""
        self._config = value

    @property
    def lock(self) -> asyncio.Lock:
        """Get or create the async lock lazily to ensure correct event loop attachment."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _validate_config(self) -> None:
        """Validate auth configuration using the canonical AuthConfig contract."""
        self._config.validate()

    async def initialize(self) -> None:
        """Initialize auth only after durable schema readiness is established."""
        if self._initialized:
            return

        logger.debug("Evaluating auth service initialization task state")
        current_task = asyncio.current_task()
        if getattr(self, "_initializing_task", None) == current_task:
            return

        logger.debug("Acquiring auth service initialization lock")
        async with self.lock:
            logger.debug("Acquired auth service initialization lock")
            if self._initialized:
                return

            self._initializing_task = current_task
            try:
                self._validate_config()
                logger.info("Verifying migration-owned authentication schema")
                await self._ensure_database_tables()

                self._initialized = True
                logger.info("Authentication Service fully ready")
            except Exception as exc:
                self._initialized = False
                self._tables_ensured = False
                logger.error(
                    "Failed to initialize Authentication Service: %s",
                    exc,
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Authentication Service initialization failed: {exc}"
                ) from exc
            finally:
                self._initializing_task = None

    async def _ensure_database_tables(self) -> None:
        """Verify migration-owned auth tables exist; never create schema at runtime."""
        if self._tables_ensured:
            return

        required = {
            "tenants",
            "auth_users",
            "auth_sessions",
            "auth_refresh_token_history",
        }
        try:
            client = self._get_db_client()
            async with client.get_async_session() as session:
                result = await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
                    ),
                    {"tables": list(required)},
                )
                present = {str(row[0]) for row in result.fetchall()}
            missing = required - present
            if missing:
                raise RuntimeError(
                    "Missing migration-owned auth tables: " + ", ".join(sorted(missing))
                )
            self._tables_ensured = True
            logger.info("Migration-owned auth tables verified")
        except Exception as e:
            logger.error("Auth schema preflight failed: %s", e)
            raise RuntimeError("AuthService database preflight failed") from e

    def set_db_session(self, session: AsyncSession) -> None:
        """Set the database session for the current execution context."""
        _db_session_ctx.set(session)

    def _get_db_client(self) -> MultiTenantPostgresClient:
        """Return a cached database client for fallback sessions."""
        if self._db_client is None:
            self._db_client = MultiTenantPostgresClient()
        return self._db_client

    @asynccontextmanager
    async def _session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a session scope using context-local or fallback client sessions."""
        session = _db_session_ctx.get()
        if session is not None:
            yield session
            return
        async with self._get_db_client().get_async_session() as session:
            yield session

    async def _resolve_tenant_id(
        self,
        session: AsyncSession,
        tenant_identifier: Optional[str],
    ) -> Optional[uuid.UUID]:
        """Resolve a configured tenant UUID or slug without inventing scope."""
        if not tenant_identifier:
            return None
        try:
            return uuid.UUID(str(tenant_identifier))
        except ValueError:
            pass

        result = await session.execute(
            select(Tenant).where(Tenant.slug == tenant_identifier)
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant.id

        logger.warning("Unknown tenant identifier '%s'; refusing tenant assignment", tenant_identifier)
        return None

    def _build_user_account(self, auth_user: AuthUser) -> UserAccount:
        """Map AuthUser ORM model to UserAccount."""
        now = datetime.utcnow()
        status = UserStatus.ACTIVE if auth_user.is_active else UserStatus.INACTIVE
        if auth_user.locked_until and auth_user.locked_until > now:
            status = UserStatus.LOCKED

        return UserAccount(
            id=str(auth_user.user_id),
            email=auth_user.email,
            username=auth_user.username or "",
            full_name=auth_user.full_name or "",
            password_hash=auth_user.password_hash,
            tenant_id=str(auth_user.tenant_id) if auth_user.tenant_id else "",
            roles=list(auth_user.roles or []),
            preferences=auth_user.preferences or {},
            is_verified=auth_user.is_verified,
            two_factor_enabled=auth_user.two_factor_enabled,
            created_at=auth_user.created_at or now,
            updated_at=auth_user.updated_at or now,
            last_login=auth_user.last_login,
            failed_login_attempts=auth_user.failed_login_attempts,
            locked_until=auth_user.locked_until,
            status=status,
        )

    async def _persist_auth_session(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        ip_address: str,
        user_agent: str,
        device_fingerprint: str,
    ) -> None:
        """Persist a session record to the database when possible."""
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            logger.warning(
                "Skipping DB session persistence; invalid user id: %s", user_id
            )
            return

        try:
            async with self._session_scope() as db_session:
                db_session.add(
                    AuthSession(
                        session_token=uuid.uuid4(),
                        user_id=user_uuid,
                        access_token=access_token,
                        refresh_token=refresh_token,
                        expires_in=self.config.refresh_token_expire_days * 24 * 60 * 60,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        device_fingerprint=device_fingerprint,
                        is_active=True,
                    )
                )
                await db_session.flush()
        except Exception as e:
            logger.error("Failed to persist session to database: %s", e)

    async def authenticate_user(
        self,
        login_identifier: str,
        password: str,
        *,
        ip_address: str = "unknown",
        user_agent: str = "",
    ) -> Tuple[Optional[UserAccount], Optional[str], Optional[str]]:
        """Authenticate a user with durable user, session, and tenant authority."""
        if not self._initialized:
            logger.info(
                "AuthService not initialized, performing lazy initialization..."
            )
            await self.initialize()

        try:
            user = await self.get_user(login_identifier)
            if not user:
                logger.warning(
                    "Authentication failed: user not found - %s", login_identifier
                )
                return None, None, "Invalid credentials"

            if user.status == UserStatus.LOCKED:
                if user.locked_until and user.locked_until > datetime.utcnow():
                    logger.warning(
                        "Authentication failed: account locked - %s", login_identifier
                    )
                    return None, None, "Account locked"
                await self._unlock_user_account(user.id)

            if user.status != UserStatus.ACTIVE:
                logger.warning(
                    "Authentication failed: account not active - %s", login_identifier
                )
                return None, None, "Account inactive"

            if not self._verify_password(password, user.password_hash):
                await self._increment_failed_login_attempts(user.id)
                logger.warning(
                    "Authentication failed: invalid password - %s", login_identifier
                )
                return None, None, "Invalid credentials"

            if not user.is_verified:
                logger.warning(
                    "Authentication failed: email not verified - %s", login_identifier
                )
                return None, None, "Email not verified"

            if not user.tenant_id:
                logger.error("Authentication refused for user without durable tenant: %s", user.id)
                return None, None, "Tenant context unavailable"

            await self._reset_failed_login_attempts(user.id)
            await self._update_last_login(user.id)

            access_token = self._generate_access_token(user)
            refresh_token = self._generate_refresh_token()

            device_fingerprint = self._generate_device_fingerprint(
                user_agent, ip_address
            )
            session = Session(
                id=secrets.token_urlsafe(32),
                user_id=user.id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=datetime.utcnow()
                + timedelta(minutes=self.config.access_token_expire_minutes),
                ip_address=ip_address,
                user_agent=user_agent,
                device_fingerprint=device_fingerprint,
            )

            self._active_sessions[session.id] = session

            await self._persist_auth_session(
                user_id=user.id,
                access_token=access_token,
                refresh_token=refresh_token,
                ip_address=ip_address,
                user_agent=user_agent,
                device_fingerprint=device_fingerprint,
            )

            logger.info("User authenticated successfully - %s", login_identifier)
            return user, access_token, refresh_token

        except Exception as e:
            logger.error("Error authenticating user: %s", e)
            return None, None, "Authentication failed"

    async def create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        *,
        username: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[UserRole]] = None,
        is_verified: bool = False,
    ) -> Tuple[Optional[UserAccount], Optional[str]]:
        """Create a user using the supplied durable tenant when provided."""
        if not self._initialized:
            await self.initialize()

        try:
            if not self._validate_email(email):
                return None, "Invalid email address"

            password_error = self._validate_password(password)
            if password_error:
                return None, password_error

            async with self._session_scope() as session:
                existing_user = await session.execute(
                    select(AuthUser).where(AuthUser.email == email)
                )
                if existing_user.scalar_one_or_none():
                    return None, "User with this email already exists"

                password_hash = self._hash_password(password)
                resolved_tenant_id = await self._resolve_tenant_id(session, tenant_id)
                if tenant_id and resolved_tenant_id is None:
                    return None, "Tenant not found"

                roles_payload = [
                    role.value if isinstance(role, UserRole) else str(role)
                    for role in (roles or [UserRole.USER])
                ]

                auth_user = AuthUser(
                    user_id=uuid.uuid4(),
                    email=email,
                    username=username or email.split("@")[0],
                    full_name=full_name,
                    password_hash=password_hash,
                    tenant_id=resolved_tenant_id,
                    roles=roles_payload,
                    preferences={},
                    is_verified=is_verified,
                    is_active=True,
                )
                session.add(auth_user)
                await session.flush()

                user = self._build_user_account(auth_user)
                if not is_verified:
                    user.status = UserStatus.PENDING_VERIFICATION

                self._user_cache[user.id] = user

            logger.info("User created successfully - %s", email)
            return user, None

        except Exception as e:
            logger.error("Error creating user: %s", e)
            return None, str(e)

    async def validate_token(self, token: str) -> Optional[UserAccount]:
        """Validate an access token and return its durable user."""
        if not self._initialized:
            await self.initialize()

        try:
            payload = jwt.decode(
                token,
                self.config.jwt_secret_key,
                algorithms=[self.config.jwt_algorithm],
                options={"verify_aud": False},
            )

            if payload.get("exp", 0) < time.time():
                logger.warning("Token expired")
                return None

            user_id = payload.get("sub")
            if not user_id:
                logger.warning("Invalid token: missing user ID")
                return None

            user = await self.get_user_by_id(user_id)
            if not user:
                logger.warning(f"User not found: {user_id}")
                return None

            if user.status != UserStatus.ACTIVE:
                logger.warning(f"User not active: {user_id}")
                return None

            if not user.tenant_id:
                logger.warning("Invalid token subject has no durable tenant: %s", user_id)
                return None

            return user

        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None
        except Exception as e:
            logger.error(f"Error validating token: {e}")
            return None

    @staticmethod
    def _hash_refresh_token(refresh_token: str) -> str:
        """Hash a refresh token for durable replay detection."""
        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    async def _mark_refresh_replay(
        self,
        db_session: AsyncSession,
        history: AuthRefreshTokenHistory,
    ) -> None:
        """Revoke the replayed session family and mark the history record."""
        now = datetime.utcnow()
        history.replayed_at = now
        result = await db_session.execute(
            select(AuthSession).where(AuthSession.session_token == history.session_id)
        )
        replayed_session = result.scalar_one_or_none()
        if replayed_session and replayed_session.is_active:
            replayed_session.is_active = False
            replayed_session.invalidated_at = now
            replayed_session.invalidation_reason = "refresh_token_replay"
        await db_session.flush()

        await self._emit_audit_event(
            action="auth.session.refresh_replay",
            actor_user_id=str(history.user_id),
            target_user_id=str(history.user_id),
            status="denied",
            reason_code="refresh_token_replay",
            session_id=str(history.session_id),
        )

    async def refresh_access_token(
        self, refresh_token: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Rotate a refresh token and issue a new access/refresh token pair."""
        if not self._initialized:
            await self.initialize()

        presented_hash = self._hash_refresh_token(refresh_token)

        try:
            async with self._session_scope() as db_session:
                prior_result = await db_session.execute(
                    select(AuthRefreshTokenHistory).where(
                        AuthRefreshTokenHistory.token_hash == presented_hash
                    )
                )
                prior_history = prior_result.scalar_one_or_none()
                if prior_history:
                    await self._mark_refresh_replay(db_session, prior_history)
                    return None, None, "Refresh token replay detected"

                result = await db_session.execute(
                    select(AuthSession)
                    .where(
                        AuthSession.refresh_token == refresh_token,
                        AuthSession.is_active,
                    )
                    .with_for_update()
                )
                db_auth_session = result.scalar_one_or_none()

                if not db_auth_session:
                    replay_result = await db_session.execute(
                        select(AuthRefreshTokenHistory).where(
                            AuthRefreshTokenHistory.token_hash == presented_hash
                        )
                    )
                    replay_history = replay_result.scalar_one_or_none()
                    if replay_history:
                        await self._mark_refresh_replay(db_session, replay_history)
                        return None, None, "Refresh token replay detected"
                    return None, None, "Invalid refresh token"

                if db_auth_session.expires_in:
                    expires_at = db_auth_session.created_at + timedelta(
                        seconds=db_auth_session.expires_in
                    )
                    if expires_at < datetime.utcnow():
                        db_auth_session.is_active = False
                        db_auth_session.invalidated_at = datetime.utcnow()
                        db_auth_session.invalidation_reason = "refresh_token_expired"
                        await db_session.flush()
                        return None, None, "Session expired"

                user_result = await db_session.execute(
                    select(AuthUser).where(AuthUser.user_id == db_auth_session.user_id)
                )
                auth_user = user_result.scalar_one_or_none()
                if not auth_user or not auth_user.is_active:
                    db_auth_session.is_active = False
                    db_auth_session.invalidated_at = datetime.utcnow()
                    db_auth_session.invalidation_reason = "user_inactive"
                    await db_session.flush()
                    return None, None, "User not found or inactive"
                if not auth_user.tenant_id:
                    return None, None, "Tenant context unavailable"

                new_access_token = self._generate_access_token(
                    self._build_user_account(auth_user)
                )
                new_refresh_token = self._generate_refresh_token()

                db_session.add(
                    AuthRefreshTokenHistory(
                        session_id=db_auth_session.session_token,
                        user_id=db_auth_session.user_id,
                        token_hash=presented_hash,
                    )
                )
                db_auth_session.access_token = new_access_token
                db_auth_session.refresh_token = new_refresh_token
                db_auth_session.last_accessed = datetime.utcnow()
                await db_session.flush()

                for cached_session in self._active_sessions.values():
                    if cached_session.refresh_token == refresh_token and cached_session.is_active:
                        cached_session.access_token = new_access_token
                        cached_session.refresh_token = new_refresh_token
                        cached_session.last_used = datetime.utcnow()
                        break

                await self._emit_audit_event(
                    action="auth.session.refresh_rotated",
                    actor_user_id=str(auth_user.user_id),
                    target_user_id=str(auth_user.user_id),
                    status="success",
                    session_id=str(db_auth_session.session_token),
                )

                logger.info(
                    "Refresh token rotated successfully for user %s", auth_user.user_id
                )
                return new_access_token, new_refresh_token, None

        except Exception as e:
            logger.error("Database refresh token rotation failed: %s", e)
            return None, None, "Database unavailable"

    async def logout(self, refresh_token: str) -> None:
        """Logout a user by invalidating their refresh token."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._session_scope() as db_session:
                result = await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.refresh_token == refresh_token
                    )
                )
                db_auth_session = result.scalar_one_or_none()
                if db_auth_session:
                    db_auth_session.is_active = False
                    db_auth_session.invalidated_at = datetime.utcnow()
                    db_auth_session.invalidation_reason = "logout"
                    await db_session.flush()
                    logger.info(
                        "User logged out successfully: %s", db_auth_session.user_id
                    )
                    for cached_session in self._active_sessions.values():
                        if cached_session.refresh_token == refresh_token:
                            cached_session.is_active = False
                            break
                    return
        except Exception as e:
            logger.error("Database logout failed: %s", e)
            raise

    async def get_user(self, identifier: str) -> Optional[UserAccount]:
        if not self._initialized:
            await self.initialize()

        user = await self.get_user_by_id(identifier)
        if user:
            return user
        user = await self.get_user_by_email(identifier)
        if user:
            return user
        return await self.get_user_by_username(identifier)

    async def get_user_by_id(self, user_id: str) -> Optional[UserAccount]:
        if not self._initialized:
            await self.initialize()
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return None
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthUser).where(AuthUser.user_id == user_uuid)
                )
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return None
                user = self._build_user_account(auth_user)
                self._user_cache[user.id] = user
                return user
        except Exception as e:
            logger.error("Error fetching user by id: %s", e)
            return None

    async def get_user_by_email(self, email: str) -> Optional[UserAccount]:
        if not self._initialized:
            await self.initialize()
        for user in self._user_cache.values():
            if user.email == email:
                return user
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthUser).where(AuthUser.email == email, AuthUser.is_active)
                )
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return None
                user = self._build_user_account(auth_user)
                self._user_cache[user.id] = user
                return user
        except Exception as e:
            logger.error("Error fetching user by email: %s", e)
            return None

    async def get_user_by_username(self, username: str) -> Optional[UserAccount]:
        if not self._initialized:
            await self.initialize()
        normalized_username = username.strip().lower()
        if not normalized_username:
            return None
        for user in self._user_cache.values():
            if (user.username or "").strip().lower() == normalized_username:
                return user
            email = (user.email or "").strip().lower()
            if email == normalized_username or email.split("@", 1)[0] == normalized_username:
                return user
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthUser).where(
                        (func.lower(AuthUser.username) == normalized_username)
                        | (func.lower(AuthUser.email) == normalized_username)
                        | (func.lower(func.split_part(AuthUser.email, "@", 1)) == normalized_username)
                    )
                )
                auth_user = result.scalar_one_or_none()
                if auth_user:
                    user = self._build_user_account(auth_user)
                    self._user_cache[user.id] = user
                    return user
                return None
        except Exception as e:
            logger.error("Error fetching user by username: %s", e)
            return None

    async def get_all_users(self) -> List[UserAccount]:
        if not self._initialized:
            await self.initialize()
        try:
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser))
                return [self._build_user_account(u) for u in result.scalars().all()]
        except Exception as e:
            logger.error("Error getting all users: %s", e)
            return []

    async def list_users(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[UserAccount]:
        if not self._initialized:
            await self.initialize()
        try:
            async with self._session_scope() as session:
                query = select(AuthUser)
                if tenant_id:
                    query = query.where(AuthUser.tenant_id == tenant_id)
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return [self._build_user_account(u) for u in result.scalars().all()]
        except Exception as e:
            logger.error("Error listing users: %s", e)
            return []

    async def create_session(
        self,
        user_id: str,
        ip_address: str = "unknown",
        user_agent: str = "",
        device_fingerprint: str = "",
    ) -> Session:
        if not self._initialized:
            await self.initialize()
        user = await self.get_user_by_id(user_id)
        if not user or not user.tenant_id:
            raise ValueError("Cannot create session without durable tenant context")
        access_token = self._generate_access_token(user)
        refresh_token = self._generate_refresh_token()
        session = Session(
            id=secrets.token_urlsafe(32),
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.utcnow()
            + timedelta(minutes=self.config.access_token_expire_minutes),
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint
            or self._generate_device_fingerprint(user_agent, ip_address),
        )
        self._active_sessions[session.id] = session
        await self._persist_auth_session(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=session.device_fingerprint,
        )
        logger.info("Session created for user %s", user_id)
        return session

    async def validate_session(
        self, session_token: str, ip_address: str = "unknown", user_agent: str = ""
    ) -> Optional[UserAccount]:
        if not self._initialized:
            await self.initialize()
        try:
            async with self._session_scope() as db_session:
                result = await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.access_token == session_token,
                        AuthSession.is_active,
                    )
                )
                db_auth_session = result.scalar_one_or_none()
                if not db_auth_session:
                    return None
                try:
                    payload = jwt.decode(
                        session_token,
                        self.config.jwt_secret_key,
                        algorithms=[self.config.jwt_algorithm],
                        options={"verify_aud": False},
                    )
                    if payload.get("exp", 0) < time.time():
                        return None
                except Exception:
                    return None
                if db_auth_session.device_fingerprint:
                    current_fingerprint = self._generate_device_fingerprint(user_agent, ip_address)
                    if db_auth_session.device_fingerprint != current_fingerprint:
                        logger.warning(
                            "Device fingerprint mismatch for session %s",
                            db_auth_session.session_token,
                        )
                user_result = await db_session.execute(
                    select(AuthUser).where(AuthUser.user_id == db_auth_session.user_id)
                )
                auth_user = user_result.scalar_one_or_none()
                if not auth_user or not auth_user.is_active or not auth_user.tenant_id:
                    db_auth_session.is_active = False
                    db_auth_session.invalidated_at = datetime.utcnow()
                    db_auth_session.invalidation_reason = "user_or_tenant_inactive"
                    await db_session.flush()
                    return None
                db_auth_session.last_accessed = datetime.utcnow()
                await db_session.flush()
                user = self._build_user_account(auth_user)
                self._user_cache[user.id] = user
                return user
        except Exception as exc:
            logger.error("Database session validation failed; rejecting session: %s", exc)
            return None

    async def list_sessions(
        self,
        user_id: Optional[str] = None,
        *,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        try:
            async with self._session_scope() as session:
                query = select(AuthSession)
                if user_id:
                    try:
                        user_uuid = uuid.UUID(str(user_id))
                        query = query.where(AuthSession.user_id == user_uuid)
                    except ValueError:
                        return []
                if active_only:
                    query = query.where(AuthSession.is_active)
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                sessions = result.scalars().all()
                return [
                    {
                        "session_token": str(s.session_token),
                        "user_id": str(s.user_id),
                        "access_token": s.access_token,
                        "refresh_token": s.refresh_token,
                        "expires_in": s.expires_in,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                        "last_accessed": s.last_accessed.isoformat() if s.last_accessed else None,
                        "ip_address": s.ip_address,
                        "user_agent": s.user_agent,
                        "device_fingerprint": s.device_fingerprint,
                        "is_active": s.is_active,
                        "invalidated_at": s.invalidated_at.isoformat() if s.invalidated_at else None,
                        "invalidation_reason": s.invalidation_reason,
                    }
                    for s in sessions
                ]
        except Exception as e:
            logger.error("Error listing sessions: %s", e)
            return []

    async def revoke_session(self, session_token: str, reason: str = "manual_revoke") -> bool:
        if not self._initialized:
            await self.initialize()
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthSession).where(
                        AuthSession.session_token == uuid.UUID(str(session_token))
                        if self._is_valid_uuid(session_token)
                        else AuthSession.access_token == session_token
                    )
                )
                db_session = result.scalar_one_or_none()
                if not db_session:
                    return False
                db_session.is_active = False
                db_session.invalidated_at = datetime.utcnow()
                db_session.invalidation_reason = reason
                await session.flush()
                return True
        except Exception as e:
            logger.error("Error revoking session: %s", e)
            return False

    async def revoke_all_sessions(
        self,
        user_id: str,
        reason: str = "global_revoke",
    ) -> int:
        if not self._initialized:
            await self.initialize()
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return 0
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == user_uuid,
                        AuthSession.is_active,
                    )
                )
                db_sessions = result.scalars().all()
                count = 0
                for db_session in db_sessions:
                    db_session.is_active = False
                    db_session.invalidated_at = datetime.utcnow()
                    db_session.invalidation_reason = reason
                    count += 1
                await session.flush()
                for cached_session in self._active_sessions.values():
                    if cached_session.user_id == user_id:
                        cached_session.is_active = False
                return count
        except Exception as e:
            logger.error("Error revoking all sessions: %s", e)
            return 0

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except ValueError:
            return False

    async def change_user_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> Optional[str]:
        if not self._initialized:
            await self.initialize()
        password_error = self._validate_password(new_password)
        if password_error:
            return password_error
        if current_password == new_password:
            return "New password must be different from current password"
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return "Invalid user ID"
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthUser).where(AuthUser.user_id == user_uuid).with_for_update()
                )
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return "User not found"
                if not self._verify_password(current_password, auth_user.password_hash):
                    await self._emit_audit_event(
                        action="auth.password.change",
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        status="denied",
                        reason_code="current_password_mismatch",
                    )
                    return "Current password is incorrect"
                auth_user.password_hash = self._hash_password(new_password)
                auth_user.updated_at = datetime.utcnow()
                sessions_result = await session.execute(
                    select(AuthSession)
                    .where(AuthSession.user_id == user_uuid, AuthSession.is_active)
                    .with_for_update()
                )
                active_sessions = sessions_result.scalars().all()
                now = datetime.utcnow()
                for db_session in active_sessions:
                    db_session.is_active = False
                    db_session.invalidated_at = now
                    db_session.invalidation_reason = "password_changed"
                await session.flush()
                self._user_cache.pop(user_id, None)
                for cached_session in self._active_sessions.values():
                    if cached_session.user_id == user_id:
                        cached_session.is_active = False
                await self._emit_audit_event(
                    action="auth.password.change",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    status="success",
                    reason_code="password_changed",
                    metadata={"revoked_session_count": len(active_sessions)},
                )
                return None
        except Exception as exc:
            logger.error("Password change failed for user %s: %s", user_id, exc)
            return "Password update failed"

    def _hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=self.config.bcrypt_rounds)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def _generate_access_token(self, user: UserAccount) -> str:
        user_type = "admin" if "admin" in user.roles or UserRole.ADMIN in user.roles else "user"
        if not user.tenant_id:
            raise ValueError("Cannot issue access token without durable tenant context")
        extra_payload = {
            "email": user.email,
            "user_type": user_type,
            "permissions": list(user.roles),
            "roles": user.roles,
            "tenant_id": user.tenant_id,
        }
        return self._generate_access_token_by_id(user.id, extra_payload)

    def _generate_access_token_by_id(
        self, user_id: str, extra_payload: Optional[Dict[str, Any]] = None
    ) -> str:
        now = int(time.time())
        token_id = secrets.token_urlsafe(32)
        payload = {
            "sub": user_id,
            "iat": now,
            "exp": now + (self.config.access_token_expire_minutes * 60),
            "token_id": token_id,
            "jti": token_id,
            "iss": "ai-karen",
            "aud": "ai-karen-users",
        }
        if extra_payload:
            payload.update(extra_payload)
        if "user_type" not in payload:
            payload["user_type"] = "user"
        if "permissions" not in payload:
            payload["permissions"] = []
        if "email" not in payload:
            payload["email"] = ""
        return jwt.encode(
            payload, self.config.jwt_secret_key, algorithm=self.config.jwt_algorithm
        )

    def _generate_refresh_token(self) -> str:
        return secrets.token_urlsafe(64)

    def _generate_device_fingerprint(self, user_agent: str, ip: str) -> str:
        data = f"{user_agent}:{ip}".encode()
        return hashlib.sha256(data).hexdigest()

    def _validate_email(self, email: str) -> bool:
        import re
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None

    def _validate_password(self, password: str) -> Optional[str]:
        if len(password) < self.config.password_min_length:
            return f"Password must be at least {self.config.password_min_length} characters long"
        if self.config.password_require_complexity:
            has_upper = any(c.isupper() for c in password)
            has_lower = any(c.islower() for c in password)
            has_digit = any(c.isdigit() for c in password)
            has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
            if not (has_upper and has_lower and has_digit and has_special):
                return "Password must contain at least one uppercase letter, one lowercase letter, one digit, and one special character"
        return None

    async def _increment_failed_login_attempts(self, user_id: str) -> None:
        try:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                logger.warning("Invalid user id for failed login update: %s", user_id)
                return
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return
                auth_user.failed_login_attempts = (auth_user.failed_login_attempts or 0) + 1
                if auth_user.failed_login_attempts >= self.config.max_failed_login_attempts:
                    auth_user.locked_until = datetime.utcnow() + timedelta(
                        minutes=self.config.account_lockout_minutes
                    )
                await session.flush()
                cached = self._user_cache.get(str(auth_user.user_id))
                if cached:
                    cached.failed_login_attempts = auth_user.failed_login_attempts
                    cached.locked_until = auth_user.locked_until
                    if cached.locked_until and cached.locked_until > datetime.utcnow():
                        cached.status = UserStatus.LOCKED
                logger.warning("Incremented failed login attempts for user %s", user_id)
        except Exception as e:
            logger.error("Failed to increment failed login attempts: %s", e)

    async def _reset_failed_login_attempts(self, user_id: str) -> None:
        try:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                logger.warning("Invalid user id for failed login reset: %s", user_id)
                return
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return
                auth_user.failed_login_attempts = 0
                auth_user.locked_until = None
                await session.flush()
                cached = self._user_cache.get(str(auth_user.user_id))
                if cached:
                    cached.failed_login_attempts = 0
                    cached.locked_until = None
                    if cached.status == UserStatus.LOCKED:
                        cached.status = UserStatus.ACTIVE
                logger.info("Reset failed login attempts for user %s", user_id)
        except Exception as e:
            logger.error("Failed to reset failed login attempts: %s", e)

    async def _lock_user_account(self, user_id: str) -> None:
        try:
            locked_until = datetime.utcnow() + timedelta(minutes=self.config.account_lockout_minutes)
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                logger.warning("Invalid user id for lock: %s", user_id)
                return
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return
                auth_user.locked_until = locked_until
                await session.flush()
                cached = self._user_cache.get(str(auth_user.user_id))
                if cached:
                    cached.locked_until = locked_until
                    cached.status = UserStatus.LOCKED
                logger.warning("Locked user account %s", user_id)
        except Exception as e:
            logger.error("Failed to lock user account: %s", e)

    async def _unlock_user_account(self, user_id: str) -> None:
        try:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                logger.warning("Invalid user id for unlock: %s", user_id)
                return
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return
                auth_user.locked_until = None
                auth_user.failed_login_attempts = 0
                await session.flush()
                cached = self._user_cache.get(str(auth_user.user_id))
                if cached:
                    cached.locked_until = None
                    cached.failed_login_attempts = 0
                    cached.status = UserStatus.ACTIVE
                logger.info("Unlocked user account %s", user_id)
        except Exception as e:
            logger.error("Failed to unlock user account: %s", e)

    async def _update_last_login(self, user_id: str) -> None:
        try:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                logger.warning("Invalid user id for last login update: %s", user_id)
                return
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return
                auth_user.last_login = datetime.utcnow()
                await session.flush()
                cached = self._user_cache.get(str(auth_user.user_id))
                if cached:
                    cached.last_login = auth_user.last_login
                logger.info("Updated last login time for user %s", user_id)
        except Exception as e:
            logger.error("Failed to update last login time: %s", e)

    async def update_user_profile(
        self,
        user_id: str,
        email: Optional[str] = None,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[UserAccount], Optional[str]]:
        try:
            try:
                if isinstance(user_id, str) and not user_id.replace("-", "").isalnum():
                    user_uuid = None
                else:
                    user_uuid = uuid.UUID(str(user_id))
            except (ValueError, AttributeError):
                logger.warning("Invalid user id format for profile update: %s", user_id)
                user_uuid = None
            if not user_uuid:
                return None, "Invalid user ID"
            async with self._session_scope() as session:
                result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return None, "User not found"
                if email is not None:
                    existing_user = await session.execute(
                        select(AuthUser).where(AuthUser.email == email, AuthUser.user_id != user_uuid)
                    )
                    if existing_user.scalar_one_or_none():
                        return None, "User with this email already exists"
                    auth_user.email = email
                if username is not None:
                    existing_user = await session.execute(
                        select(AuthUser).where(AuthUser.username == username, AuthUser.user_id != user_uuid)
                    )
                    if existing_user.scalar_one_or_none():
                        return None, "User with this username already exists"
                    auth_user.username = username
                if full_name is not None:
                    auth_user.full_name = full_name
                if preferences is not None:
                    if not auth_user.preferences:
                        auth_user.preferences = {}
                    if isinstance(preferences, dict):
                        auth_user.preferences.update(preferences)
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(auth_user, "preferences")
                await session.flush()
                await session.refresh(auth_user)
                user_account = self._build_user_account(auth_user)
                self._user_cache[str(auth_user.user_id)] = user_account
                logger.info("User profile updated for user %s", user_id)
                return user_account, None
        except Exception as e:
            logger.error("Failed to update user profile: %s", e)
            return None, str(e)

    async def _emit_audit_event(
        self,
        action: str,
        actor_user_id: Optional[str],
        target_user_id: Optional[str],
        status: str,
        reason_code: Optional[str] = None,
        session_id: Optional[str] = None,
        ip_address: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = {
            "action": action,
            "actor_user_id": actor_user_id,
            "target_user_id": target_user_id,
            "tenant_id": None,
            "session_id": session_id,
            "status": status,
            "reason_code": reason_code,
            "ip_address": ip_address,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        if target_user_id:
            try:
                target = await self.get_user_by_id(target_user_id)
                if target:
                    event["tenant_id"] = target.tenant_id
            except Exception:
                pass
        try:
            logger.info("AUTH_AUDIT %s", event)
        except Exception:
            pass

    async def update_user(
        self,
        user_id: str,
        *,
        full_name: Optional[str] = None,
        roles: Optional[List[str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
        is_verified: Optional[bool] = None,
    ) -> UserAccount:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError as exc:
            raise ValueError("Invalid user ID") from exc
        async with self._session_scope() as session:
            result = await session.execute(select(AuthUser).where(AuthUser.user_id == user_uuid))
            auth_user = result.scalar_one_or_none()
            if not auth_user:
                raise ValueError("User not found")
            if full_name is not None:
                auth_user.full_name = full_name
            if roles is not None:
                auth_user.roles = [
                    role.value if isinstance(role, UserRole) else str(role) for role in roles
                ]
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(auth_user, "roles")
            if preferences is not None:
                current_preferences = dict(auth_user.preferences or {})
                current_preferences.update(preferences)
                auth_user.preferences = current_preferences
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(auth_user, "preferences")
            if is_active is not None:
                auth_user.is_active = is_active
            if is_verified is not None:
                auth_user.is_verified = is_verified
            auth_user.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(auth_user)
            user_account = self._build_user_account(auth_user)
            self._user_cache[str(auth_user.user_id)] = user_account
            await self._emit_audit_event(
                action="auth.user.updated",
                actor_user_id=None,
                target_user_id=user_id,
                status="success",
                metadata={
                    "updated_fields": [
                        k
                        for k, v in {
                            "full_name": full_name,
                            "roles": roles,
                            "preferences": preferences,
                            "is_active": is_active,
                            "is_verified": is_verified,
                        }.items()
                        if v is not None
                    ]
                },
            )
            return user_account

    async def set_user_status(
        self,
        user_id: str,
        is_active: bool,
        *,
        reason: Optional[str] = None,
    ) -> UserAccount:
        user = await self.update_user(user_id, is_active=is_active)
        if not is_active:
            await self.revoke_all_sessions(user_id, reason=reason or "account_disabled")
        await self._emit_audit_event(
            action="auth.account.status_changed",
            actor_user_id=None,
            target_user_id=user_id,
            status="success",
            reason_code=reason,
            metadata={"is_active": is_active},
        )
        return user

    async def set_user_roles(
        self,
        user_id: str,
        roles: List[str],
        *,
        reason: Optional[str] = None,
    ) -> UserAccount:
        user = await self.update_user(user_id, roles=roles)
        await self._emit_audit_event(
            action="auth.role.assigned",
            actor_user_id=None,
            target_user_id=user_id,
            status="success",
            reason_code=reason,
            metadata={"roles": roles},
        )
        return user

    async def update_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any],
        *,
        merge: bool = True,
    ) -> UserAccount:
        if merge:
            existing = await self.get_user_by_id(user_id)
            if existing:
                merged = dict(existing.preferences or {})
                merged.update(preferences)
                preferences = merged
        user = await self.update_user(user_id, preferences=preferences)
        await self._emit_audit_event(
            action="auth.user.updated",
            actor_user_id=None,
            target_user_id=user_id,
            status="success",
            metadata={"preferences_updated": list(preferences.keys())},
        )
        return user

    async def health_check(self) -> bool:
        """Require canonical initialization state and a live database connection."""
        if not self._initialized or not self._tables_ensured:
            return False
        try:
            async with self._session_scope() as session:
                await session.execute(text("SELECT 1"))

            test_user_id = "test_user"
            token = self._generate_access_token_by_id(test_user_id)
            payload = jwt.decode(
                token,
                self.config.jwt_secret_key,
                algorithms=[self.config.jwt_algorithm],
                options={"verify_aud": False},
            )
            return payload.get("sub") == test_user_id
        except Exception as e:
            logger.error("Authentication Service health check failed: %s", e)
            return False

    async def get_auth_stats(self) -> Dict[str, Any]:
        try:
            from sqlalchemy import select, func, text
            from ai_karen_engine.database.models import AuthUser, AuthSession
            from ai_karen_engine.database.client import MultiTenantPostgresClient
            if not self._db_session:
                try:
                    temp_client = MultiTenantPostgresClient()
                    async with temp_client.get_async_session() as session:
                        result = await session.execute(select(func.count()).select_from(AuthUser))
                        total_users = result.scalar() or 0
                        result = await session.execute(
                            select(func.count()).select_from(AuthUser).where(AuthUser.is_active)
                        )
                        active_users = result.scalar() or 0
                        result = await session.execute(select(func.count()).select_from(AuthSession))
                        total_sessions = result.scalar() or 0
                        result = await session.execute(
                            select(func.count())
                            .select_from(AuthSession)
                            .where(
                                AuthSession.is_active,
                                AuthSession.last_used >= text("NOW() - INTERVAL '24 hours'"),
                            )
                        )
                        active_sessions = result.scalar() or 0
                    return {
                        "total_users": total_users,
                        "active_users": active_users,
                        "total_sessions": total_sessions,
                        "active_sessions": active_sessions,
                        "service_status": "running" if self._initialized else "stopped",
                    }
                except Exception as temp_error:
                    logger.warning(f"Could not use temporary database client: {temp_error}")
                    return {
                        "total_users": 0,
                        "active_users": 0,
                        "total_sessions": 0,
                        "active_sessions": 0,
                        "service_status": "error",
                        "error": "Database session not available",
                    }
            result = await self._db_session.execute(select(func.count()).select_from(AuthUser))
            total_users = result.scalar() or 0
            result = await self._db_session.execute(
                select(func.count()).select_from(AuthUser).where(AuthUser.is_active)
            )
            active_users = result.scalar() or 0
            result = await self._db_session.execute(select(func.count()).select_from(AuthSession))
            total_sessions = result.scalar() or 0
            result = await self._db_session.execute(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.is_active, AuthSession.last_used >= text("NOW() - INTERVAL '24 hours'"))
            )
            active_sessions = result.scalar() or 0
            return {
                "total_users": total_users,
                "active_users": active_users,
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "service_status": "running" if self._initialized else "stopped",
            }
        except Exception as e:
            logger.error(f"Failed to get auth stats: {e}")
            return {
                "total_users": 0,
                "active_users": 0,
                "total_sessions": 0,
                "active_sessions": 0,
                "service_status": "error",
                "error": str(e),
            }

    async def is_first_run(self) -> bool:
        """Check if this is the first run (no users exist)."""
        try:
            if not self._db_session:
                temp_client = MultiTenantPostgresClient()
                async with temp_client.get_async_session() as session:
                    result = await session.execute(select(func.count()).select_from(AuthUser))
                    return (result.scalar() or 0) == 0
            result = await self._db_session.execute(select(func.count()).select_from(AuthUser))
            return (result.scalar() or 0) == 0
        except Exception as exc:
            logger.error("Failed to determine first-run status: %s", exc)
            raise RuntimeError("First-run state unavailable") from exc

    async def create_first_admin(
        self, email: str, password: str, full_name: str
    ) -> UserAccount:
        """Atomically create the installation tenant and first admin user.

        A PostgreSQL transaction-scoped advisory lock serializes bootstrap
        across processes and workers. Tenant creation/resolution, the user-count
        check, and first-admin creation all occur in the caller's transaction.
        """
        async with self._session_scope() as session:
            context_token = _db_session_ctx.set(session)
            try:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _FIRST_ADMIN_BOOTSTRAP_LOCK_KEY},
                )
                result = await session.execute(select(func.count()).select_from(AuthUser))
                if (result.scalar() or 0) != 0:
                    raise ValueError("First-run setup has already been completed")

                tenant_slug = os.getenv("KARI_FIRST_RUN_TENANT_SLUG", "installation").strip()
                tenant_name = os.getenv("KARI_FIRST_RUN_TENANT_NAME", "AI KAREN").strip()
                if not tenant_slug or not tenant_name:
                    raise ValueError("First-run tenant configuration is invalid")

                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.slug == tenant_slug).with_for_update()
                )
                tenant = tenant_result.scalar_one_or_none()
                if tenant is None:
                    tenant = Tenant(
                        name=tenant_name,
                        slug=tenant_slug,
                        subscription_tier="basic",
                        settings={"bootstrap": True},
                        is_active=True,
                    )
                    session.add(tenant)
                    await session.flush()
                elif not tenant.is_active:
                    raise ValueError("First-run tenant is inactive")

                user, error = await self.create_user(
                    email=email,
                    password=password,
                    full_name=full_name,
                    tenant_id=str(tenant.id),
                    roles=[UserRole.ADMIN, UserRole.USER],
                    is_verified=True,
                )
                if not user:
                    raise ValueError(f"Failed to create first admin user: {error}")
                if user.tenant_id != str(tenant.id):
                    raise RuntimeError("First admin tenant assignment failed")

                await self._emit_audit_event(
                    action="auth.first_admin.created",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    status="success",
                    metadata={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
                )
                logger.info(
                    "First admin user created for tenant %s: %s", tenant.id, email
                )
                return user
            finally:
                _db_session_ctx.reset(context_token)

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        logger.info("Authentication Service started successfully")

    async def stop(self) -> None:
        if not self._initialized:
            return
        self._active_sessions.clear()
        self._user_cache.clear()
        self._tables_ensured = False
        self._initialized = False
        logger.info("Authentication Service stopped successfully")
