"""
AuthUser Service for AI Karen Engine.
Provides comprehensive user management with database integration,
authentication, and LLM system integration.
"""

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import and_, desc, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.models import (
    AuthUser,
    Tenant,
    TenantConversation,
    TenantMemoryEntry,
)
from ai_karen_engine.utils.auth import create_session, validate_session

logger = logging.getLogger(__name__)


class UserServiceError(Exception):
    """Base exception for user service errors."""

    pass


class UserNotFoundError(UserServiceError):
    """Exception raised when a user is not found."""

    pass


class TenantNotFoundError(UserServiceError):
    """Exception raised when a tenant is not found."""

    pass


class UserAlreadyExistsError(UserServiceError):
    """Exception raised when trying to create a user that already exists."""

    pass


class UserService(BaseService):
    """
    Comprehensive user management service with database integration.
    Handles user authentication, profile management, and LLM system integration.
    """

    def __init__(
        self,
        config: ServiceConfig,
        db_client: Optional[MultiTenantPostgresClient] = None,
    ):
        super().__init__(config)
        self.db_client = db_client or MultiTenantPostgresClient()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the user service."""
        try:
            self.logger.info("Initializing AuthUser Service")

            # Create default tenant if it doesn't exist
            await self._ensure_default_tenant()

            self._initialized = True
            self.logger.info("AuthUser Service initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize AuthUser Service: {e}")
            raise

    async def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        self.logger.info("AuthUser Service started")

    async def stop(self) -> None:
        self.logger.info("AuthUser Service stopped")

    async def health_check(self) -> bool:
        """Check if the user service is healthy."""
        try:
            # Test database connection
            from sqlalchemy import text

            with self._get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            self.logger.error(f"AuthUser service health check failed: {e}")
            return False

    @contextmanager
    def _get_session(self):
        """Get database session with proper error handling."""
        session = self.db_client.get_sync_session()  # type: ignore
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _ensure_default_tenant(self) -> None:
        """Ensure the default tenant exists."""
        try:
            with self._get_session() as session:
                default_tenant = session.query(Tenant).filter_by(slug="default").first()
                if not default_tenant:
                    default_tenant = Tenant(
                        name="Default Tenant",
                        slug="default",
                        subscription_tier="basic",
                        settings={
                            "max_users": 1000,
                            "features": ["chat", "memory", "llm"],
                        },
                    )
                    session.add(default_tenant)
                    session.commit()

                    # Create tenant schema
                    self.db_client.create_tenant_schema(default_tenant.id)  # type: ignore

                    self.logger.info(f"Created default tenant: {default_tenant.id}")
        except Exception as e:
            self.logger.error(f"Failed to ensure default tenant: {e}")
            raise

    # AuthUser Management Methods

    async def create_user(
        self,
        email: str,
        roles: Optional[List[str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> AuthUser:
        """
        Create a new user.

        Args:
            email: AuthUser email address
            roles: List of user roles (defaults to ["user"])
            preferences: AuthUser preferences dictionary
            tenant_id: Tenant ID (defaults to default tenant)

        Returns:
            Created AuthUser instance

        Raises:
            UserAlreadyExistsError: If user already exists
            TenantNotFoundError: If tenant doesn't exist
        """
        try:
            with self._get_session() as session:
                # Get tenant
                if tenant_id is None:
                    tenant = session.query(Tenant).filter_by(slug="default").first()
                    if not tenant:
                        raise TenantNotFoundError("Default tenant not found")
                    tenant_id = tenant.id
                else:
                    if isinstance(tenant_id, str):
                        tenant_id = uuid.UUID(tenant_id)
                    tenant = session.query(Tenant).filter_by(id=tenant_id).first()
                    if not tenant:
                        raise TenantNotFoundError(f"Tenant {tenant_id} not found")

                # Check if user already exists
                existing_user = (
                    session.query(AuthUser)
                    .filter(
                        and_(AuthUser.email == email, AuthUser.tenant_id == tenant_id)
                    )
                    .first()
                )
                if existing_user:
                    raise UserAlreadyExistsError(
                        f"AuthUser {email} already exists in tenant {tenant_id}"
                    )

                # Create user
                user = AuthUser(
                    tenant_id=tenant_id,
                    email=email,
                    roles=roles or ["user"],
                    preferences=preferences or self._get_default_preferences(),
                    is_active=True,
                )

                session.add(user)
                session.commit()

                # Ensure tenant schema exists
                self.db_client.create_tenant_schema(tenant_id)  # type: ignore

                self.logger.info(
                    f"Created user: {user.id} ({email}) in tenant {tenant_id}"
                )
                return user

        except (UserAlreadyExistsError, TenantNotFoundError):
            raise
        except IntegrityError as e:
            raise UserAlreadyExistsError(f"AuthUser {email} already exists") from e
        except Exception as e:
            self.logger.error(f"Failed to create user {email}: {e}")
            raise UserServiceError(f"Failed to create user: {e}") from e

    async def get_user(
        self,
        user_id: Union[str, uuid.UUID],
        tenant_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> AuthUser:
        """
        Get user by ID.

        Args:
            user_id: AuthUser ID
            tenant_id: Optional tenant ID for additional filtering

        Returns:
            AuthUser instance

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)
            if isinstance(tenant_id, str):
                tenant_id = uuid.UUID(tenant_id)

            with self._get_session() as session:
                query = session.query(AuthUser).filter(AuthUser.id == user_id)
                if tenant_id:
                    query = query.filter(AuthUser.tenant_id == tenant_id)

                user = query.first()
                if not user:
                    raise UserNotFoundError(f"AuthUser {user_id} not found")

                return user

        except UserNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to get user {user_id}: {e}")
            raise UserServiceError(f"Failed to get user: {e}") from e

    async def get_user_by_email(
        self, email: str, tenant_id: Optional[Union[str, uuid.UUID]] = None
    ) -> AuthUser:
        """
        Get user by email.

        Args:
            email: AuthUser email address
            tenant_id: Optional tenant ID for filtering

        Returns:
            AuthUser instance

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        try:
            if isinstance(tenant_id, str):
                tenant_id = uuid.UUID(tenant_id)

            with self._get_session() as session:
                query = session.query(AuthUser).filter(AuthUser.email == email)
                if tenant_id:
                    query = query.filter(AuthUser.tenant_id == tenant_id)
                else:
                    # Default to default tenant if not specified
                    default_tenant = (
                        session.query(Tenant).filter_by(slug="default").first()
                    )
                    if default_tenant:
                        query = query.filter(AuthUser.tenant_id == default_tenant.id)

                user = query.first()
                if not user:
                    raise UserNotFoundError(f"AuthUser {email} not found")

                return user

        except UserNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to get user by email {email}: {e}")
            raise UserServiceError(f"Failed to get user by email: {e}") from e

    async def update_user_preferences(
        self, user_id: Union[str, uuid.UUID], preferences: Dict[str, Any]
    ) -> AuthUser:
        """
        Update user preferences.

        Args:
            user_id: AuthUser ID
            preferences: New preferences dictionary

        Returns:
            Updated AuthUser instance

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)

            with self._get_session() as session:
                user = session.query(AuthUser).filter(AuthUser.id == user_id).first()
                if not user:
                    raise UserNotFoundError(f"AuthUser {user_id} not found")

                # Merge preferences
                current_preferences = user.preferences or {}
                current_preferences.update(preferences)
                user.preferences = current_preferences
                user.updated_at = datetime.now(timezone.utc)

                session.commit()

                self.logger.info(f"Updated preferences for user {user_id}")
                return user

        except UserNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to update preferences for user {user_id}: {e}")
            raise UserServiceError(f"Failed to update user preferences: {e}") from e

    async def update_last_login(self, user_id: Union[str, uuid.UUID]) -> None:
        """
        Update user's last login timestamp.

        Args:
            user_id: AuthUser ID
        """
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)

            with self._get_session() as session:
                user = session.query(AuthUser).filter(AuthUser.id == user_id).first()
                if user:
                    user.last_login = datetime.now(timezone.utc)
                    user.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    self.logger.debug(f"Updated last login for user {user_id}")

        except Exception as e:
            self.logger.error(f"Failed to update last login for user {user_id}: {e}")

    # Authentication Integration Methods

    async def authenticate_user(
        self,
        email: str,
        password: str,
        user_agent: str,
        ip: str,
        tenant_slug: str = "default",
    ) -> Dict[str, Any]:
        """
        Authenticate user and create session.

        Args:
            email: AuthUser email
            password: AuthUser password (for demo purposes)
            user_agent: AuthUser agent string
            ip: Client IP address
            tenant_slug: Tenant slug

        Returns:
            Authentication result with token and user info

        Raises:
            UserServiceError: If authentication fails
        """
        try:
            # For demo purposes, we'll use simple password validation
            # In production, this should use proper password hashing
            demo_users = {
                "admin@kari.ai": {
                    "password": "Admin@123!",
                    "roles": ["admin", "user"],
                },
                "user@kari.ai": {"password": "password123", "roles": ["user"]},
            }

            # Try database authentication first
            try:
                user = await self.get_user_by_email(email)
                
                # Verify password if user exists and has a hash
                if hasattr(user, 'password_hash') and user.password_hash:
                    from ai_karen_engine.server.security import pwd_context
                    if not pwd_context.verify(password, user.password_hash):
                        self.logger.warning(f"Password verification failed for user: {email}")
                        raise UserServiceError("Invalid credentials")
                    self.logger.info(f"Database authentication successful for user: {email}")
                else:
                    # Fallback to demo users if user has no password hash
                    if email not in demo_users or demo_users[email]["password"] != password:
                        raise UserServiceError("Invalid credentials")
            except UserNotFoundError:
                # Fallback to demo users if not in database
                if email not in demo_users or demo_users[email]["password"] != password:
                    raise UserServiceError("Invalid credentials")
                
                # Create user from demo config if it doesn't exist yet but has demo creds
                user = await self.create_user(
                    email=email, roles=demo_users[email]["roles"]
                )
                self.logger.info(f"Demo authentication successful for user: {email}")

            # Update last login
            await self.update_last_login(user.id)

            # Create session token
            token = create_session(
                user_id=str(user.id),
                roles=list(user.roles or []),  # type: ignore
                user_agent=user_agent,
                ip=ip,
                tenant_id=str(user.tenant_id),
            )

            return {
                "token": token,
                "user_id": str(user.id),
                "email": user.email,
                "roles": user.roles,
                "tenant_id": str(user.tenant_id),
                "preferences": user.preferences,
            }

        except UserServiceError:
            raise
        except Exception as e:
            self.logger.error(f"Authentication failed for {email}: {e}")
            raise UserServiceError(f"Authentication failed: {e}") from e

    async def validate_user_session(
        self, token: str, user_agent: str, ip: str
    ) -> Optional[Dict[str, Any]]:
        """
        Validate user session and return user context.

        Args:
            token: JWT session token
            user_agent: AuthUser agent string
            ip: Client IP address

        Returns:
            AuthUser context if valid, None otherwise
        """
        try:
            # Validate JWT token
            session_data = validate_session(token, user_agent, ip)
            if not session_data:
                return None

            # Get user from database
            user_id = session_data.get("sub")
            if not user_id:
                return None

            user = await self.get_user(user_id)
            if not user or not getattr(user, 'is_active', False):  # type: ignore
                return None

            return {
                "user_id": str(user.id),
                "email": user.email,
                "roles": user.roles,
                "tenant_id": str(user.tenant_id),
                "preferences": user.preferences,
                "session_data": session_data,
            }

        except Exception as e:
            self.logger.error(f"Session validation failed: {e}")
            return None

    # LLM Integration Methods

    async def get_user_llm_preferences(
        self, user_id: Union[str, uuid.UUID]
    ) -> Dict[str, Any]:
        """
        Get user's LLM preferences for conversation processing.

        Args:
            user_id: AuthUser ID

        Returns:
            LLM preferences dictionary
        """
        try:
            user = await self.get_user(user_id)
            preferences = user.preferences or {}

            # Extract LLM-specific preferences
            llm_preferences = {
                "personalityTone": preferences.get("personalityTone", "friendly"),
                "personalityVerbosity": preferences.get(
                    "personalityVerbosity", "balanced"
                ),
                "memoryDepth": preferences.get("memoryDepth", "medium"),
                "customPersonaInstructions": preferences.get(
                    "customPersonaInstructions", ""
                ),
                "preferredLLMProvider": preferences.get(
                    "preferredLLMProvider", "builtin_vllm"
                ),
                "preferredModel": preferences.get("preferredModel", "llama3.2:latest"),
                "temperature": preferences.get("temperature", 0.7),
                "maxTokens": preferences.get("maxTokens", 1000),
            }

            return llm_preferences

        except Exception as e:
            self.logger.error(f"Failed to get LLM preferences for user {user_id}: {e}")
            # Return default preferences on error
            return self._get_default_llm_preferences()

    async def save_user_conversation(
        self,
        user_id: Union[str, uuid.UUID],
        session_id: str,
        messages: List[Dict[str, Any]],
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save user conversation to database.

        Args:
            user_id: AuthUser ID
            session_id: Session ID
            messages: Conversation messages
            title: Optional conversation title
            metadata: Optional metadata

        Returns:
            Dictionary with conversation data
        """
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)

            user = await self.get_user(user_id)
            schema_name = self.db_client.get_tenant_schema_name(getattr(user, 'tenant_id', None))  # type: ignore

            with self._get_session() as session:
                import json

                from sqlalchemy import text

                # Check if conversation already exists using raw SQL
                check_sql = text(
                    f"""
                    SELECT id, title, messages, conversation_metadata, created_at, updated_at
                    FROM {schema_name}.conversations
                    WHERE user_id = :user_id AND session_id = :session_id
                    LIMIT 1
                """
                )

                result = session.execute(
                    check_sql, {"user_id": user_id, "session_id": session_id}
                )
                existing_row = result.fetchone()

                if existing_row:
                    # Update existing conversation
                    update_sql = text(
                        f"""
                        UPDATE {schema_name}.conversations
                        SET messages = :messages,
                            title = COALESCE(:title, title),
                            conversation_metadata = :metadata,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = :user_id AND session_id = :session_id
                        RETURNING id, title, messages, conversation_metadata, created_at, updated_at
                    """
                    )

                    result = session.execute(
                        update_sql,
                        {
                            "user_id": user_id,
                            "session_id": session_id,
                            "messages": json.dumps(messages),
                            "title": title,
                            "metadata": json.dumps(metadata or {}),
                        },
                    )
                    updated_row = result.fetchone()
                    session.commit()

                    self.logger.info(
                        f"Updated conversation for user {user_id}, session {session_id}"
                    )
                    return {
                        "id": str(updated_row[0]),
                        "title": updated_row[1],
                        "messages": updated_row[2],
                        "metadata": updated_row[3],
                        "created_at": updated_row[4],
                        "updated_at": updated_row[5],
                    }
                else:
                    # Create new conversation
                    insert_sql = text(
                        f"""
                        INSERT INTO {schema_name}.conversations
                        (user_id, session_id, title, messages, conversation_metadata, user_settings)
                        VALUES (:user_id, :session_id, :title, :messages, :metadata, :user_settings)
                        RETURNING id, title, messages, conversation_metadata, created_at, updated_at
                    """
                    )

                    result = session.execute(
                        insert_sql,
                        {
                            "user_id": user_id,
                            "session_id": session_id,
                            "title": title or f"Conversation {session_id[:8]}",
                            "messages": json.dumps(messages),
                            "metadata": json.dumps(metadata or {}),
                            "user_settings": json.dumps(user.preferences or {}),
                        },
                    )
                    new_row = result.fetchone()
                    session.commit()

                    self.logger.info(
                        f"Created conversation for user {user_id}, session {session_id}"
                    )
                    return {
                        "id": str(new_row[0]),
                        "title": new_row[1],
                        "messages": new_row[2],
                        "metadata": new_row[3],
                        "created_at": new_row[4],
                        "updated_at": new_row[5],
                    }

        except Exception as e:
            self.logger.error(f"Failed to save conversation for user {user_id}: {e}")
            raise UserServiceError(f"Failed to save conversation: {e}") from e

    async def get_user_conversations(
        self, user_id: Union[str, uuid.UUID], limit: int = 50, offset: int = 0
    ) -> List[TenantConversation]:
        """
        Get user's conversations.

        Args:
            user_id: AuthUser ID
            limit: Maximum number of conversations to return
            offset: Offset for pagination

        Returns:
            List of TenantConversation instances
        """
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)

            with self._get_session() as session:
                conversations = (
                    session.query(TenantConversation)
                    .filter(TenantConversation.user_id == user_id)
                    .order_by(desc(TenantConversation.updated_at))
                    .limit(limit)
                    .offset(offset)
                    .all()
                )

                return conversations

        except Exception as e:
            self.logger.error(f"Failed to get conversations for user {user_id}: {e}")
            return []

    # Utility Methods

    def _get_default_preferences(self) -> Dict[str, Any]:
        """Get default user preferences."""
        return {
            "personalityTone": "friendly",
            "personalityVerbosity": "balanced",
            "memoryDepth": "medium",
            "customPersonaInstructions": "",
            "preferredLLMProvider": "builtin_vllm",
            "preferredModel": "llama3.2:latest",
            "temperature": 0.7,
            "maxTokens": 1000,
            "notifications": {"email": True, "push": False},
            "ui": {"theme": "light", "language": "en"},
        }

    def _get_default_llm_preferences(self) -> Dict[str, Any]:
        """Get default LLM preferences."""
        return {
            "personalityTone": "friendly",
            "personalityVerbosity": "balanced",
            "memoryDepth": "medium",
            "customPersonaInstructions": "",
            "preferredLLMProvider": "builtin_vllm",
            "preferredModel": "llama3.2:latest",
            "temperature": 0.7,
            "maxTokens": 1000,
        }

    # Metrics and Analytics

    def get_metrics(self) -> Dict[str, Any]:
        """Get user service metrics."""
        try:
            with self._get_session() as session:
                total_users = session.query(AuthUser).count()
                active_users = (
                    session.query(AuthUser).filter(AuthUser.is_active == True).count()
                )
                total_tenants = session.query(Tenant).count()

                return {
                    "total_users": total_users,
                    "active_users": active_users,
                    "total_tenants": total_tenants,
                    "service_status": "healthy"
                    if self._initialized
                    else "initializing",
                }
        except Exception as e:
            self.logger.error(f"Failed to get user service metrics: {e}")
            return {
                "total_users": 0,
                "active_users": 0,
                "total_tenants": 0,
                "service_status": "error",
            }
