"""Typed API contracts for the Identity Vault.

This module owns request/response DTOs and enums only. Persistence models live in
``ai_karen_engine.database.identity_vault_schema`` and schema evolution lives in
``supabase/migrations``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CredentialStatus(str, Enum):
    ACTIVE = "active"
    REFRESH_REQUIRED = "refresh_required"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    ROTATING = "rotating"


class TokenType(str, Enum):
    API_KEY = "api_key"
    OAUTH_ACCESS = "oauth_access"
    OAUTH_REFRESH = "oauth_refresh"
    SESSION = "session"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM = "custom"


class ProviderType(str, Enum):
    OAUTH2 = "oauth2"
    OAUTH1 = "oauth1"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM = "custom"


class AccountCapability(str, Enum):
    GMAIL_READ = "gmail.read"
    GMAIL_SEND = "gmail.send"
    GMAIL_MODIFY = "gmail.modify"
    CALENDAR_READ = "calendar.read"
    CALENDAR_WRITE = "calendar.write"
    CALENDAR_DELETE = "calendar.delete"
    DRIVE_READ = "drive.read"
    DRIVE_WRITE = "drive.write"
    DRIVE_DELETE = "drive.delete"
    GITHUB_READ = "github.read"
    GITHUB_WRITE = "github.write"
    GITHUB_REPO = "github.repo"
    GITHUB_USER = "github.user"
    OPENAI_CHAT = "openai.chat"
    OPENAI_COMPLETIONS = "openai.completions"
    OPENAI_EMBEDDINGS = "openai.embeddings"
    OPENAI_IMAGES = "openai.images"
    MICROSOFT_GRAPH = "microsoft.graph"
    MICROSOFT_OUTLOOK = "microsoft.outlook"
    MICROSOFT_ONEDRIVE = "microsoft.onedrive"
    SLACK_READ = "slack.read"
    SLACK_WRITE = "slack.write"
    SLACK_APP = "slack.app"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


class AuditEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    ROTATED = "rotated"
    REVOKED = "revoked"
    EXPIRED = "expired"
    AUTHENTICATED = "authenticated"
    REFRESHED = "refreshed"
    TOKEN_REFRESH_FAILED = "token_refresh_failed"
    BINDING_CREATED = "binding_created"
    BINDING_UPDATED = "binding_updated"
    BINDING_REVOKED = "binding_revoked"
    LOGIN = "login"
    LOGOUT = "logout"
    AUTHENTICATION = "authentication"
    ACCESS = "access"


class LoginStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


class VaultModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")


class ProviderDefinitionCreate(VaultModel):
    provider_id: str
    display_name: str
    description: Optional[str] = None
    provider_type: ProviderType | str
    config: Dict[str, Any] = Field(default_factory=dict)
    icon_url: Optional[str] = None
    website_url: Optional[str] = None
    supported_capabilities: List[str] = Field(default_factory=list)
    enabled: bool = True
    is_system: bool = False


class ProviderDefinitionUpdate(VaultModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    provider_type: Optional[ProviderType | str] = None
    config: Optional[Dict[str, Any]] = None
    icon_url: Optional[str] = None
    website_url: Optional[str] = None
    supported_capabilities: Optional[List[str]] = None
    enabled: Optional[bool] = None


class ProviderDefinition(ProviderDefinitionCreate):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CredentialSecretCreate(VaultModel):
    secret_type: str
    encrypted_value: str
    secret_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class CredentialCreate(VaultModel):
    name: str
    description: Optional[str] = None
    provider_id: uuid.UUID
    credential_type: str
    credential_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")
    masked_hint: Optional[str] = None
    expires_at: Optional[datetime] = None
    rotation_interval_hours: Optional[int] = None


class CredentialUpdate(VaultModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[CredentialStatus] = None
    credential_metadata: Optional[Dict[str, Any]] = Field(default=None, alias="metadata")
    masked_hint: Optional[str] = None
    expires_at: Optional[datetime] = None
    rotation_interval_hours: Optional[int] = None


class Credential(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str] = None
    provider_id: uuid.UUID
    status: CredentialStatus | str
    credential_type: str
    credential_metadata: Dict[str, Any] = Field(default_factory=dict)
    masked_hint: Optional[str] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    rotation_interval_hours: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None


CredentialResponse = Credential


class ExternalAccountCreate(VaultModel):
    provider_id: uuid.UUID
    account_identifier: str
    display_name: Optional[str] = None
    account_metadata: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    is_active: bool = True


class ExternalAccountUpdate(VaultModel):
    display_name: Optional[str] = None
    account_metadata: Optional[Dict[str, Any]] = None
    capabilities: Optional[List[str]] = None
    is_active: Optional[bool] = None


class ExternalAccount(ExternalAccountCreate):
    id: uuid.UUID
    tenant_id: uuid.UUID
    last_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


ExternalAccountResponse = ExternalAccount


class CredentialBindingCreate(VaultModel):
    credential_id: uuid.UUID
    external_account_id: uuid.UUID
    is_active: bool = True
    is_primary: bool = False
    binding_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class CredentialBinding(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    credential_id: uuid.UUID
    external_account_id: uuid.UUID
    is_active: bool
    is_primary: bool
    binding_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AccountSessionCreate(VaultModel):
    credential_id: uuid.UUID
    external_account_id: uuid.UUID
    session_token: str
    token_type: TokenType | str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: List[str] = Field(default_factory=list)
    session_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AccountSession(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    credential_id: uuid.UUID
    external_account_id: uuid.UUID
    session_token: str
    token_type: str
    expires_at: Optional[datetime] = None
    scopes: List[str] = Field(default_factory=list)
    session_metadata: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AuthGrantCreate(VaultModel):
    credential_id: uuid.UUID
    provider_id: uuid.UUID
    grant_type: str
    authorization_code: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    redirect_uri: Optional[str] = None
    state: Optional[str] = None
    code_challenge: Optional[str] = None
    code_challenge_method: Optional[str] = None
    is_completed: bool = False


class AuthGrant(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    credential_id: uuid.UUID
    provider_id: uuid.UUID
    grant_type: str
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    is_completed: bool
    created_at: datetime
    updated_at: datetime


class TokenLeaseCreate(VaultModel):
    credential_id: uuid.UUID
    lease_token: str
    access_token: Optional[str] = None
    expires_at: datetime
    scopes: List[str] = Field(default_factory=list)
    lease_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class TokenLease(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    credential_id: uuid.UUID
    lease_token: str
    expires_at: datetime
    scopes: List[str] = Field(default_factory=list)
    lease_metadata: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginAttemptCreate(VaultModel):
    credential_id: uuid.UUID
    external_account_id: Optional[uuid.UUID] = None
    attempt_type: str
    status: LoginStatus | str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    attempt_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class LoginAttempt(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    credential_id: uuid.UUID
    external_account_id: Optional[uuid.UUID] = None
    attempt_type: str
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime
    attempt_metadata: Dict[str, Any] = Field(default_factory=dict)


class CredentialAuditEventCreate(VaultModel):
    credential_id: Optional[uuid.UUID] = None
    account_id: Optional[uuid.UUID] = None
    provider_id: Optional[uuid.UUID] = None
    event_type: AuditEventType | str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    correlation_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    audit_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class CredentialAuditEvent(VaultModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: str
    credential_id: Optional[uuid.UUID] = None
    account_id: Optional[uuid.UUID] = None
    provider_id: Optional[uuid.UUID] = None
    event_type: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: datetime


class AccountCapabilityDiscovery(VaultModel):
    account_id: uuid.UUID
    provider_id: uuid.UUID
    account_identifier: str
    discovered_capabilities: List[AccountCapability | str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TokenRotationResult(VaultModel):
    credential_id: uuid.UUID
    old_token_hash: Optional[str] = None
    new_token: str = ""
    new_token_hash: Optional[str] = None
    rotation_time: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CredentialHealthStatus(VaultModel):
    credential_id: uuid.UUID
    status: CredentialStatus | str
    health_score: float = Field(ge=0.0, le=1.0)
    expires_at: Optional[datetime] = None
    needs_rotation: bool = False
    issues: List[str] = Field(default_factory=list)
    last_check: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    next_check: Optional[datetime] = None


def validate_capabilities(capabilities: List[str | AccountCapability]) -> List[str]:
    values = [cap.value if isinstance(cap, AccountCapability) else str(cap) for cap in capabilities]
    return list(dict.fromkeys(values))


def generate_masked_hint(value: str, visible_suffix: int = 4) -> str:
    if not value:
        return ""
    suffix = value[-visible_suffix:] if visible_suffix > 0 else ""
    return f"{'•' * max(4, min(len(value), 12))}{suffix}"


def is_token_expired(expires_at: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    if expires_at is None:
        return False
    reference = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        reference = reference.replace(tzinfo=None)
    return expires_at <= reference


def calculate_health_score(
    credential: Any = None,
    *,
    status: CredentialStatus | str | None = None,
    expires_at: Optional[datetime] = None,
    last_used_at: Optional[datetime] = None,
) -> float:
    if credential is not None:
        status = getattr(credential, "status", status)
        expires_at = getattr(credential, "expires_at", expires_at)
        last_used_at = getattr(credential, "last_used_at", last_used_at)
    status = status or CredentialStatus.INVALID
    status_value = status.value if isinstance(status, CredentialStatus) else str(status)
    if status_value in {CredentialStatus.REVOKED.value, CredentialStatus.INVALID.value}:
        return 0.0
    if is_token_expired(expires_at):
        return 0.1
    if status_value == CredentialStatus.REFRESH_REQUIRED.value:
        return 0.5
    return 1.0


__all__ = [
    "AccountCapability", "AccountCapabilityDiscovery", "AccountSession", "AccountSessionCreate",
    "AuditEventType", "AuthGrant", "AuthGrantCreate", "Credential", "CredentialAuditEvent",
    "CredentialAuditEventCreate", "CredentialBinding", "CredentialBindingCreate", "CredentialCreate",
    "CredentialHealthStatus", "CredentialResponse", "CredentialSecretCreate", "CredentialStatus",
    "CredentialUpdate", "ExternalAccount", "ExternalAccountCreate", "ExternalAccountResponse",
    "ExternalAccountUpdate", "LoginAttempt", "LoginAttemptCreate", "LoginStatus", "ProviderDefinition",
    "ProviderDefinitionCreate", "ProviderDefinitionUpdate", "ProviderType", "TokenLease", "TokenLeaseCreate",
    "TokenRotationResult", "TokenType", "calculate_health_score", "generate_masked_hint", "is_token_expired",
    "validate_capabilities",
]
