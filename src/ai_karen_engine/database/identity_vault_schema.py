"""
Identity vault database schema definition and creation utilities.

This module defines the PostgreSQL schema for identity vault data including
credentials, external accounts, provider definitions, and related entities.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ai_karen_engine.database.models import Base


class CredentialStatus(str, Enum):
    """Credential status enumeration."""
    ACTIVE = "active"
    REFRESH_REQUIRED = "refresh_required"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    ROTATING = "rotating"


class TokenType(str, Enum):
    """Token type enumeration."""
    API_KEY = "api_key"
    OAUTH_ACCESS = "oauth_access"
    OAUTH_REFRESH = "oauth_refresh"
    SESSION = "session"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM = "custom"


class ProviderType(str, Enum):
    """Provider type enumeration."""
    OAUTH2 = "oauth2"
    OAUTH1 = "oauth1"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM = "custom"


class AccountCapability(str, Enum):
    """Account capability enumeration."""
    # Google
    GMAIL_READ = "gmail.read"
    GMAIL_SEND = "gmail.send"
    GMAIL_MODIFY = "gmail.modify"
    CALENDAR_READ = "calendar.read"
    CALENDAR_WRITE = "calendar.write"
    CALENDAR_DELETE = "calendar.delete"
    DRIVE_READ = "drive.read"
    DRIVE_WRITE = "drive.write"
    DRIVE_DELETE = "drive.delete"
    
    # GitHub
    GITHUB_READ = "github.read"
    GITHUB_WRITE = "github.write"
    GITHUB_REPO = "github.repo"
    GITHUB_USER = "github.user"
    
    # OpenAI
    OPENAI_CHAT = "openai.chat"
    OPENAI_COMPLETIONS = "openai.completions"
    OPENAI_EMBEDDINGS = "openai.embeddings"
    OPENAI_IMAGES = "openai.images"
    
    # Microsoft
    MICROSOFT_GRAPH = "microsoft.graph"
    MICROSOFT_OUTLOOK = "microsoft.outlook"
    MICROSOFT_ONEDRIVE = "microsoft.onedrive"
    
    # Slack
    SLACK_READ = "slack.read"
    SLACK_WRITE = "slack.write"
    SLACK_APP = "slack.app"
    
    # Generic
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


class ProviderDefinition(Base):
    """Provider definition table for external service configurations."""
    
    __tablename__ = 'identity_providers'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    provider_type = Column(String(50), nullable=False)  # Using String instead of Enum for compatibility
    config = Column(JSON, nullable=False)  # OAuth config, API endpoints, etc.
    icon_url = Column(String(500))
    website_url = Column(String(500))
    supported_capabilities = Column(JSON, default=list)  # List of AccountCapability
    enabled = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # System providers can't be deleted
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credentials = relationship("Credential", back_populates="provider", cascade="all, delete-orphan")
    external_accounts = relationship("ExternalAccount", back_populates="provider", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_identity_providers_enabled', 'enabled'),
        Index('idx_identity_providers_type', 'provider_type'),
    )


class CredentialSecret(Base):
    """Encrypted credential secret storage."""
    
    __tablename__ = 'credential_secrets'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    secret_type = Column(String(50), nullable=False)  # api_key, refresh_token, access_token, etc.
    encrypted_value = Column(Text, nullable=False)  # Encrypted secret data
    encryption_key_id = Column(String(255))  # Key used for encryption
    secret_metadata = Column(JSON, default=dict)  # Additional secret metadata
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="secrets")
    
    __table_args__ = (
        Index('idx_credential_secrets_credential', 'credential_id'),
        Index('idx_credential_secrets_type', 'secret_type'),
    )


class Credential(Base):
    """Main credential entity with metadata and status."""
    
    __tablename__ = 'credentials'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    provider_id = Column(UUID(as_uuid=True), ForeignKey('identity_providers.id', ondelete='CASCADE'), nullable=False, index=True)
    status = Column(String(50), default="active")
    credential_type = Column(String(50), nullable=False)  # oauth, api_key, basic_auth, etc.
    credential_metadata = Column(JSON, default=dict)  # Additional credential metadata
    masked_hint = Column(String(255))  # UI hint (e.g., "••••••••••••••••")
    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))  # Optional expiration for tokens
    rotation_interval_hours = Column(Integer)  # For automatic rotation
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    created_by = Column(String(255))  # User ID or system identifier
    
    # Relationships
    provider = relationship("ProviderDefinition", back_populates="credentials")
    secrets = relationship("CredentialSecret", back_populates="credential", cascade="all, delete-orphan")
    bindings = relationship("CredentialBinding", back_populates="credential", cascade="all, delete-orphan")
    audit_events = relationship("CredentialAuditEvent", back_populates="credential", cascade="all, delete-orphan")
    sessions = relationship("AccountSession", back_populates="credential", cascade="all, delete-orphan")
    auth_grants = relationship("AuthGrant", back_populates="credential", cascade="all, delete-orphan")
    token_leases = relationship("TokenLease", back_populates="credential", cascade="all, delete-orphan")
    login_attempts = relationship("LoginAttempt", back_populates="credential", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_credentials_provider', 'provider_id'),
        Index('idx_credentials_status', 'status'),
        Index('idx_credentials_type', 'credential_type'),
        Index('idx_credentials_expires', 'expires_at'),
        Index('idx_credentials_last_used', 'last_used_at'),
    )


class ExternalAccount(Base):
    """External account entity representing a user's account on a provider."""
    
    __tablename__ = 'external_accounts'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(UUID(as_uuid=True), ForeignKey('identity_providers.id', ondelete='CASCADE'), nullable=False, index=True)
    account_identifier = Column(String(255), nullable=False)  # Email, username, etc.
    display_name = Column(String(255))
    account_metadata = Column(JSON, default=dict)  # Account-specific metadata
    capabilities = Column(JSON, default=list)  # Discovered capabilities
    is_active = Column(Boolean, default=True)
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    provider = relationship("ProviderDefinition", back_populates="external_accounts")
    bindings = relationship("CredentialBinding", back_populates="external_account", cascade="all, delete-orphan")
    sessions = relationship("AccountSession", back_populates="external_account", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_external_accounts_provider', 'provider_id'),
        Index('idx_external_accounts_identifier', 'account_identifier'),
        Index('idx_external_accounts_active', 'is_active'),
        UniqueConstraint('provider_id', 'account_identifier', name='uq_external_accounts_provider_identifier'),
    )


class CredentialBinding(Base):
    """Binding between a credential and an external account."""
    
    __tablename__ = 'credential_bindings'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey('external_accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)  # Primary binding for this account
    binding_metadata = Column(JSON, default=dict)  # Additional binding metadata
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="bindings")
    external_account = relationship("ExternalAccount", back_populates="bindings")
    
    __table_args__ = (
        Index('idx_credential_bindings_credential', 'credential_id'),
        Index('idx_credential_bindings_account', 'external_account_id'),
        Index('idx_credential_bindings_active', 'is_active'),
        UniqueConstraint('external_account_id', 'is_primary', name='uq_external_account_primary'),
    )


class AccountSession(Base):
    """Session for an authenticated external account."""
    
    __tablename__ = 'account_sessions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey('external_accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_type = Column(String(50), nullable=False)
    expires_at = Column(DateTime(timezone=True))
    scopes = Column(JSON, default=list)  # OAuth scopes or permissions
    session_metadata = Column(JSON, default=dict)  # Session-specific metadata
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="sessions")
    external_account = relationship("ExternalAccount", back_populates="sessions")
    
    __table_args__ = (
        Index('idx_account_sessions_credential', 'credential_id'),
        Index('idx_account_sessions_account', 'external_account_id'),
        Index('idx_account_sessions_active', 'is_active'),
        Index('idx_account_sessions_expires', 'expires_at'),
        Index('idx_account_sessions_token', 'session_token'),
    )


class AuthGrant(Base):
    """OAuth authorization grant storage."""
    
    __tablename__ = 'auth_grants'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey('identity_providers.id', ondelete='CASCADE'), nullable=False, index=True)
    grant_type = Column(String(50), nullable=False)  # authorization_code, client_credentials, etc.
    authorization_code = Column(String(255))
    access_token = Column(Text)
    refresh_token = Column(Text)
    scopes = Column(JSON, default=list)
    expires_at = Column(DateTime(timezone=True))
    redirect_uri = Column(String(500))
    state = Column(String(255))
    code_challenge = Column(String(255))
    code_challenge_method = Column(String(50))
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="auth_grants")
    provider = relationship("ProviderDefinition")
    
    __table_args__ = (
        Index('idx_auth_grants_credential', 'credential_id'),
        Index('idx_auth_grants_provider', 'provider_id'),
        Index('idx_auth_grants_completed', 'is_completed'),
        Index('idx_auth_grants_expires', 'expires_at'),
    )


class TokenLease(Base):
    """Token lease management for temporary access."""
    
    __tablename__ = 'token_leases'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    lease_token = Column(String(255), unique=True, nullable=False, index=True)
    access_token = Column(Text)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    scopes = Column(JSON, default=list)
    lease_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="token_leases")
    
    __table_args__ = (
        Index('idx_token_leases_credential', 'credential_id'),
        Index('idx_token_leases_active', 'is_active'),
        Index('idx_token_leases_expires', 'expires_at'),
        Index('idx_token_leases_token', 'lease_token'),
    )


class LoginAttempt(Base):
    """Login attempt tracking and analysis."""
    
    __tablename__ = 'login_attempts'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey('external_accounts.id', ondelete='CASCADE'))
    attempt_type = Column(String(50), nullable=False)  # oauth, api_key, basic_auth
    status = Column(String(50), nullable=False)  # success, failed, pending
    error_code = Column(String(100))
    error_message = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    timestamp = Column(DateTime(timezone=True), default=func.now())
    attempt_metadata = Column(JSON, default=dict)
    
    # Relationships
    credential = relationship("Credential", back_populates="login_attempts")
    external_account = relationship("ExternalAccount")
    
    __table_args__ = (
        Index('idx_login_attempts_credential', 'credential_id'),
        Index('idx_login_attempts_account', 'external_account_id'),
        Index('idx_login_attempts_status', 'status'),
        Index('idx_login_attempts_timestamp', 'timestamp'),
    )


class CredentialAuditEvent(Base):
    """Audit trail for credential operations."""
    
    __tablename__ = 'credential_audit_events'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey('credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey('external_accounts.id', ondelete='CASCADE'))
    provider_id = Column(UUID(as_uuid=True), ForeignKey('identity_providers.id', ondelete='CASCADE'))
    event_type = Column(String(50), nullable=False, index=True)  # created, updated, rotated, revoked, etc.
    action = Column(String(100), nullable=False)  # authenticate, refresh, rotate, etc.
    resource_type = Column(String(50), nullable=False)  # credential, account, binding, etc.
    resource_id = Column(String(255))
    correlation_id = Column(String(255), index=True)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    audit_metadata = Column(JSON, default=dict)
    timestamp = Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    credential = relationship("Credential", back_populates="audit_events")
    external_account = relationship("ExternalAccount")
    provider = relationship("ProviderDefinition")
    
    __table_args__ = (
        Index('idx_credential_audit_events_tenant', 'tenant_id'),
        Index('idx_credential_audit_events_user', 'user_id'),
        Index('idx_credential_audit_events_credential', 'credential_id'),
        Index('idx_credential_audit_events_event', 'event_type'),
        Index('idx_credential_audit_events_timestamp', 'timestamp'),
        Index('idx_credential_audit_events_correlation', 'correlation_id'),
    )


class IdentityVaultSchema:
    """Read-only validator for migration-owned Identity Vault tables."""

    REQUIRED_TABLES = (
        "identity_providers", "credentials", "credential_secrets",
        "external_accounts", "credential_bindings", "account_sessions",
        "auth_grants", "token_leases", "login_attempts",
        "credential_audit_events",
    )

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.logger = logging.getLogger(__name__)

    def validate_schema(self, engine) -> bool:
        """Return whether all migration-owned Identity Vault tables exist."""
        from sqlalchemy import inspect
        try:
            existing = set(inspect(engine).get_table_names())
            missing = set(self.REQUIRED_TABLES) - existing
            if missing:
                self.logger.error("Missing Identity Vault tables: %s", sorted(missing))
                return False
            return True
        except Exception as exc:
            self.logger.error("Identity Vault schema validation failed: %s", exc)
            return False


# Schema creation is intentionally absent. Supabase migrations own DDL.
