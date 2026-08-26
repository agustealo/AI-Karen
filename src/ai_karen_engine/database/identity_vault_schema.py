"""Persistence mappings for the Identity Vault.

The ORM owns persistence shape only. Request/response contracts live in
``ai_karen_engine.database.models.identity_vault`` and schema evolution is owned
exclusively by ``supabase/migrations``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ai_karen_engine.database.models import Base
from ai_karen_engine.database.models.identity_vault import AccountCapability, CredentialStatus, ProviderType, TokenType


class ProviderDefinition(Base):
    __tablename__ = "identity_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    provider_id = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    provider_type = Column(String(50), nullable=False)
    config = Column(JSON, nullable=False)
    icon_url = Column(String(500))
    website_url = Column(String(500))
    supported_capabilities = Column(JSON, default=list)
    enabled = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    credentials = relationship("Credential", back_populates="provider", cascade="all, delete-orphan")
    external_accounts = relationship("ExternalAccount", back_populates="provider", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_identity_providers_enabled", "enabled"),
        Index("idx_identity_providers_type", "provider_type"),
        Index("idx_identity_providers_tenant", "tenant_id"),
    )


class CredentialSecret(Base):
    __tablename__ = "credential_secrets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    secret_type = Column(String(50), nullable=False)
    encrypted_value = Column(Text, nullable=False)
    encryption_key_id = Column(String(255))
    secret_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    credential = relationship("Credential", back_populates="secrets")

    __table_args__ = (
        Index("idx_credential_secrets_credential", "credential_id"),
        Index("idx_credential_secrets_type", "secret_type"),
        Index("idx_credential_secrets_tenant", "tenant_id"),
    )


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default=CredentialStatus.ACTIVE.value)
    credential_type = Column(String(50), nullable=False)
    credential_metadata = Column(JSON, default=dict)
    masked_hint = Column(String(255))
    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    rotation_interval_hours = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    created_by = Column(String(255))

    provider = relationship("ProviderDefinition", back_populates="credentials")
    secrets = relationship("CredentialSecret", back_populates="credential", cascade="all, delete-orphan")
    bindings = relationship("CredentialBinding", back_populates="credential", cascade="all, delete-orphan")
    audit_events = relationship("CredentialAuditEvent", back_populates="credential", cascade="all, delete-orphan")
    sessions = relationship("AccountSession", back_populates="credential", cascade="all, delete-orphan")
    auth_grants = relationship("AuthGrant", back_populates="credential", cascade="all, delete-orphan")
    token_leases = relationship("TokenLease", back_populates="credential", cascade="all, delete-orphan")
    login_attempts = relationship("LoginAttempt", back_populates="credential", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_credentials_provider", "provider_id"),
        Index("idx_credentials_status", "status"),
        Index("idx_credentials_type", "credential_type"),
        Index("idx_credentials_expires", "expires_at"),
        Index("idx_credentials_last_used", "last_used_at"),
        Index("idx_credentials_tenant", "tenant_id"),
    )


class ExternalAccount(Base):
    __tablename__ = "external_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    account_identifier = Column(String(255), nullable=False)
    display_name = Column(String(255))
    account_metadata = Column(JSON, default=dict)
    capabilities = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    provider = relationship("ProviderDefinition", back_populates="external_accounts")
    bindings = relationship("CredentialBinding", back_populates="external_account", cascade="all, delete-orphan")
    sessions = relationship("AccountSession", back_populates="external_account", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_external_accounts_provider", "provider_id"),
        Index("idx_external_accounts_identifier", "account_identifier"),
        Index("idx_external_accounts_active", "is_active"),
        Index("idx_external_accounts_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "provider_id", "account_identifier", name="uq_external_accounts_tenant_provider_identifier"),
    )


class CredentialBinding(Base):
    __tablename__ = "credential_bindings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    binding_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    credential = relationship("Credential", back_populates="bindings")
    external_account = relationship("ExternalAccount", back_populates="bindings")

    __table_args__ = (
        Index("idx_credential_bindings_credential", "credential_id"),
        Index("idx_credential_bindings_account", "external_account_id"),
        Index("idx_credential_bindings_active", "is_active"),
        Index("idx_credential_bindings_tenant", "tenant_id"),
    )


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_type = Column(String(50), nullable=False)
    expires_at = Column(DateTime(timezone=True))
    scopes = Column(JSON, default=list)
    session_metadata = Column(JSON, default=dict)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    credential = relationship("Credential", back_populates="sessions")
    external_account = relationship("ExternalAccount", back_populates="sessions")

    __table_args__ = (
        Index("idx_account_sessions_credential", "credential_id"),
        Index("idx_account_sessions_account", "external_account_id"),
        Index("idx_account_sessions_active", "is_active"),
        Index("idx_account_sessions_expires", "expires_at"),
        Index("idx_account_sessions_token", "session_token"),
        Index("idx_account_sessions_tenant", "tenant_id"),
    )


class AuthGrant(Base):
    __tablename__ = "auth_grants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    grant_type = Column(String(50), nullable=False)
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

    credential = relationship("Credential", back_populates="auth_grants")
    provider = relationship("ProviderDefinition")

    __table_args__ = (
        Index("idx_auth_grants_credential", "credential_id"),
        Index("idx_auth_grants_provider", "provider_id"),
        Index("idx_auth_grants_completed", "is_completed"),
        Index("idx_auth_grants_expires", "expires_at"),
        Index("idx_auth_grants_tenant", "tenant_id"),
    )


class TokenLease(Base):
    __tablename__ = "token_leases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_token = Column(String(255), unique=True, nullable=False, index=True)
    access_token = Column(Text)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    scopes = Column(JSON, default=list)
    lease_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    credential = relationship("Credential", back_populates="token_leases")

    __table_args__ = (
        Index("idx_token_leases_credential", "credential_id"),
        Index("idx_token_leases_active", "is_active"),
        Index("idx_token_leases_expires", "expires_at"),
        Index("idx_token_leases_token", "lease_token"),
        Index("idx_token_leases_tenant", "tenant_id"),
    )


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    external_account_id = Column(UUID(as_uuid=True), ForeignKey("external_accounts.id", ondelete="CASCADE"))
    attempt_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    error_code = Column(String(100))
    error_message = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    timestamp = Column(DateTime(timezone=True), default=func.now())
    attempt_metadata = Column(JSON, default=dict)

    credential = relationship("Credential", back_populates="login_attempts")
    external_account = relationship("ExternalAccount")

    __table_args__ = (
        Index("idx_login_attempts_credential", "credential_id"),
        Index("idx_login_attempts_account", "external_account_id"),
        Index("idx_login_attempts_status", "status"),
        Index("idx_login_attempts_timestamp", "timestamp"),
        Index("idx_login_attempts_tenant", "tenant_id"),
    )


class CredentialAuditEvent(Base):
    __tablename__ = "credential_audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=True, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255))
    correlation_id = Column(String(255), index=True)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    audit_metadata = Column(JSON, default=dict)
    timestamp = Column(DateTime(timezone=True), default=func.now(), index=True)

    credential = relationship("Credential", back_populates="audit_events")
    account = relationship("ExternalAccount")
    provider = relationship("ProviderDefinition")

    __table_args__ = (
        Index("idx_credential_audit_events_tenant", "tenant_id"),
        Index("idx_credential_audit_events_user", "user_id"),
        Index("idx_credential_audit_events_credential", "credential_id"),
        Index("idx_credential_audit_events_event", "event_type"),
        Index("idx_credential_audit_events_timestamp", "timestamp"),
        Index("idx_credential_audit_events_correlation", "correlation_id"),
    )


class IdentityVaultSchema:
    """Read-only validator for migration-owned Identity Vault tables."""

    REQUIRED_TABLES = (
        "identity_providers", "credentials", "credential_secrets", "external_accounts",
        "credential_bindings", "account_sessions", "auth_grants", "token_leases",
        "login_attempts", "credential_audit_events",
    )

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.logger = logging.getLogger(__name__)

    def validate_schema(self, engine) -> bool:
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


__all__ = [
    "AccountCapability", "AccountSession", "AuthGrant", "Credential", "CredentialAuditEvent",
    "CredentialBinding", "CredentialSecret", "CredentialStatus", "ExternalAccount",
    "IdentityVaultSchema", "LoginAttempt", "ProviderDefinition", "ProviderType", "TokenLease",
    "TokenType",
]
