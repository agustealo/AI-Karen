"""Tenant-scoped Identity Vault runtime service.

The service owns vault data operations and audit emission. API DTOs live in
``database.models.identity_vault``; ORM mappings live in
``database.identity_vault_schema``; schema evolution is migration-owned.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.security.encryption_utils import decrypt_data, encrypt_data
from ai_karen_engine.core.services.base import BaseService, ServiceConfig, ServiceStatus
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.identity_vault_schema import (
    AccountSession,
    AuthGrant,
    Credential,
    CredentialAuditEvent,
    CredentialBinding,
    CredentialSecret,
    ExternalAccount,
    LoginAttempt,
    ProviderDefinition,
    TokenLease,
)
from ai_karen_engine.database.models.identity_vault import (
    AccountCapability,
    AccountCapabilityDiscovery,
    AccountSessionCreate,
    AuditEventType,
    AuthGrantCreate,
    CredentialBindingCreate,
    CredentialCreate,
    CredentialHealthStatus,
    CredentialSecretCreate,
    CredentialStatus,
    CredentialUpdate,
    ExternalAccountCreate,
    ExternalAccountUpdate,
    LoginAttemptCreate,
    LoginStatus,
    ProviderDefinitionCreate,
    ProviderDefinitionUpdate,
    ProviderType,
    TokenLeaseCreate,
    TokenRotationResult,
    calculate_health_score,
    is_token_expired,
)

logger = get_logger(__name__)


class IdentityVaultConfig(ServiceConfig):
    name: str = "identity_vault_service"
    version: str = "1.1.0"
    rate_limit_per_minute: int = 60
    audit_retention_days: int = 365


class CredentialVaultService(BaseService):
    """Canonical tenant-scoped runtime for credentials and external accounts."""

    _REQUIRED_TABLES = {
        "identity_providers",
        "credentials",
        "credential_secrets",
        "external_accounts",
        "credential_bindings",
        "account_sessions",
        "auth_grants",
        "token_leases",
        "login_attempts",
        "credential_audit_events",
    }
    _TENANT_TABLES = _REQUIRED_TABLES - {"credential_audit_events"}

    def __init__(self, config: Optional[IdentityVaultConfig] = None):
        super().__init__(config or IdentityVaultConfig())
        self._initialized = False
        self._db_session: Optional[AsyncSession] = None
        self._db_client: Optional[MultiTenantPostgresClient] = None
        self._rate_limits: Dict[str, List[datetime]] = {}

    def set_db_session(self, session: AsyncSession) -> None:
        """Inject a session for tests or an explicitly managed transaction."""
        self._db_session = session

    def _get_db_client(self) -> MultiTenantPostgresClient:
        if self._db_client is None:
            self._db_client = MultiTenantPostgresClient()
        return self._db_client

    @asynccontextmanager
    async def _session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        if self._db_session is not None:
            yield self._db_session
            return
        async with self._get_db_client().get_async_session() as session:
            yield session

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._verify_schema()
        self._initialized = True
        self._status = ServiceStatus.READY
        logger.info("Identity Vault migration-owned schema verified")

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        self._status = ServiceStatus.RUNNING

    async def stop(self) -> None:
        self._status = ServiceStatus.STOPPED

    async def health_check(self) -> bool:
        try:
            async with self._session_scope() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("Identity Vault health check failed: %s", exc)
            return False

    async def _verify_schema(self) -> None:
        async with self._session_scope() as session:
            tables_result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
                ),
                {"tables": sorted(self._REQUIRED_TABLES)},
            )
            present_tables = {str(row[0]) for row in tables_result.fetchall()}
            missing_tables = self._REQUIRED_TABLES - present_tables
            if missing_tables:
                raise RuntimeError(
                    "Missing migration-owned Identity Vault tables: "
                    + ", ".join(sorted(missing_tables))
                )

            columns_result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
                    "AND table_name = ANY(:tables)"
                ),
                {"tables": sorted(self._TENANT_TABLES)},
            )
            tenant_tables = {str(row[0]) for row in columns_result.fetchall()}
            missing_tenant_columns = self._TENANT_TABLES - tenant_tables
            if missing_tenant_columns:
                raise RuntimeError(
                    "Identity Vault tenant migration is incomplete for: "
                    + ", ".join(sorted(missing_tenant_columns))
                )

    @staticmethod
    def _tenant_query(model: Any, tenant_id: uuid.UUID):
        if tenant_id is None:
            raise ValueError("tenant_id is required")
        return select(model).where(model.tenant_id == tenant_id)

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    async def _check_rate_limit(self, tenant_id: uuid.UUID, user_id: str, operation: str) -> None:
        now = datetime.utcnow()
        key = f"{tenant_id}:{user_id}:{operation}"
        recent = [stamp for stamp in self._rate_limits.get(key, []) if now - stamp < timedelta(minutes=1)]
        if len(recent) >= self.config.rate_limit_per_minute:
            raise RuntimeError("Rate limit exceeded")
        recent.append(now)
        self._rate_limits[key] = recent

    async def _audit(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: str,
        event_type: AuditEventType,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        credential_id: Optional[uuid.UUID] = None,
        account_id: Optional[uuid.UUID] = None,
        provider_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        safe_metadata = self._redact_sensitive_data(metadata or {})
        session.add(
            CredentialAuditEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                credential_id=credential_id,
                account_id=account_id,
                provider_id=provider_id,
                event_type=event_type.value,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                correlation_id=correlation_id,
                audit_metadata=safe_metadata,
            )
        )

    @classmethod
    def _redact_sensitive_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        sensitive = {
            "password",
            "api_key",
            "access_token",
            "refresh_token",
            "authorization_code",
            "client_secret",
            "private_key",
            "secret",
            "token",
            "key",
        }
        redacted: Dict[str, Any] = {}
        for key, value in data.items():
            redacted[key] = "***REDACTED***" if any(part in key.lower() for part in sensitive) else value
        return redacted

    async def _tenant_entity(
        self,
        session: AsyncSession,
        model: Any,
        tenant_id: uuid.UUID,
        *clauses: Any,
    ) -> Any:
        query = self._tenant_query(model, tenant_id)
        if clauses:
            query = query.where(*clauses)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def create_provider(
        self, provider_data: ProviderDefinitionCreate, tenant_id: uuid.UUID, user_id: str
    ) -> ProviderDefinition:
        await self._check_rate_limit(tenant_id, user_id, "provider_create")
        async with self._session_scope() as session:
            provider = ProviderDefinition(
                tenant_id=tenant_id,
                provider_id=provider_data.provider_id,
                display_name=provider_data.display_name,
                description=provider_data.description,
                provider_type=self._enum_value(provider_data.provider_type),
                config=provider_data.config,
                icon_url=provider_data.icon_url,
                website_url=provider_data.website_url,
                supported_capabilities=provider_data.supported_capabilities,
                enabled=provider_data.enabled,
                is_system=provider_data.is_system,
            )
            session.add(provider)
            await session.flush()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.CREATED,
                action="provider_creation",
                resource_type="provider",
                resource_id=str(provider.id),
                provider_id=provider.id,
            )
            await session.commit()
            return provider

    async def get_provider(self, provider_id: str, tenant_id: uuid.UUID) -> Optional[ProviderDefinition]:
        async with self._session_scope() as session:
            return await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.provider_id == provider_id
            )

    async def list_providers(
        self, tenant_id: uuid.UUID, enabled_only: bool = False, limit: int = 100, offset: int = 0
    ) -> List[ProviderDefinition]:
        async with self._session_scope() as session:
            query = self._tenant_query(ProviderDefinition, tenant_id)
            if enabled_only:
                query = query.where(ProviderDefinition.enabled.is_(True))
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())

    async def update_provider(
        self,
        provider_id: str,
        update_data: ProviderDefinitionUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[ProviderDefinition]:
        async with self._session_scope() as session:
            provider = await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.provider_id == provider_id
            )
            if provider is None:
                return None
            patch = update_data.model_dump(exclude_unset=True)
            for field, value in patch.items():
                setattr(provider, field, self._enum_value(value))
            provider.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.UPDATED,
                action="provider_update",
                resource_type="provider",
                resource_id=str(provider.id),
                provider_id=provider.id,
                metadata={"updated_fields": sorted(patch)},
            )
            await session.commit()
            return provider

    async def delete_provider(
        self, provider_id: str, tenant_id: uuid.UUID, user_id: str
    ) -> bool:
        async with self._session_scope() as session:
            provider = await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.provider_id == provider_id
            )
            if provider is None or provider.is_system:
                return False
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.DELETED,
                action="provider_deletion",
                resource_type="provider",
                resource_id=str(provider.id),
                provider_id=provider.id,
            )
            await session.delete(provider)
            await session.commit()
            return True

    async def create_credential(
        self,
        credential_data: CredentialCreate,
        secrets: List[CredentialSecretCreate],
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Credential:
        await self._check_rate_limit(tenant_id, user_id, "credential_create")
        async with self._session_scope() as session:
            provider = await self._tenant_entity(
                session,
                ProviderDefinition,
                tenant_id,
                ProviderDefinition.id == credential_data.provider_id,
            )
            if provider is None:
                raise ValueError("Provider not found in tenant")
            credential = Credential(
                tenant_id=tenant_id,
                name=credential_data.name,
                description=credential_data.description,
                provider_id=credential_data.provider_id,
                credential_type=credential_data.credential_type,
                credential_metadata=credential_data.credential_metadata,
                masked_hint=credential_data.masked_hint,
                expires_at=credential_data.expires_at,
                rotation_interval_hours=credential_data.rotation_interval_hours,
                created_by=user_id,
            )
            session.add(credential)
            await session.flush()
            for secret_data in secrets:
                encrypted = encrypt_data(secret_data.encrypted_value).decode("ascii")
                session.add(
                    CredentialSecret(
                        tenant_id=tenant_id,
                        credential_id=credential.id,
                        secret_type=secret_data.secret_type,
                        encrypted_value=encrypted,
                        secret_metadata=secret_data.secret_metadata,
                    )
                )
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.CREATED,
                action="credential_creation",
                resource_type="credential",
                resource_id=str(credential.id),
                credential_id=credential.id,
                provider_id=provider.id,
            )
            await session.commit()
            return credential

    async def get_credential(self, credential_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Credential]:
        async with self._session_scope() as session:
            query = self._tenant_query(Credential, tenant_id).options(selectinload(Credential.secrets)).where(
                Credential.id == credential_id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def list_credentials(
        self,
        tenant_id: uuid.UUID,
        provider_id: Optional[str] = None,
        status: Optional[CredentialStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Credential]:
        async with self._session_scope() as session:
            query = self._tenant_query(Credential, tenant_id).options(selectinload(Credential.secrets))
            if provider_id:
                provider = await self._tenant_entity(
                    session, ProviderDefinition, tenant_id, ProviderDefinition.provider_id == provider_id
                )
                if provider is None:
                    return []
                query = query.where(Credential.provider_id == provider.id)
            if status:
                query = query.where(Credential.status == self._enum_value(status))
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())

    async def update_credential(
        self,
        credential_id: uuid.UUID,
        update_data: CredentialUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[Credential]:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == credential_id
            )
            if credential is None:
                return None
            patch = update_data.model_dump(exclude_unset=True)
            for field, value in patch.items():
                setattr(credential, field, self._enum_value(value))
            credential.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.UPDATED,
                action="credential_update",
                resource_type="credential",
                resource_id=str(credential.id),
                credential_id=credential.id,
                metadata={"updated_fields": sorted(patch)},
            )
            await session.commit()
            return credential

    async def delete_credential(
        self, credential_id: uuid.UUID, tenant_id: uuid.UUID, user_id: str
    ) -> bool:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == credential_id
            )
            if credential is None:
                return False
            bindings = await session.execute(
                self._tenant_query(CredentialBinding, tenant_id).where(
                    CredentialBinding.credential_id == credential_id,
                    CredentialBinding.is_active.is_(True),
                )
            )
            if bindings.scalars().first() is not None:
                return False
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.DELETED,
                action="credential_deletion",
                resource_type="credential",
                resource_id=str(credential.id),
                credential_id=credential.id,
            )
            await session.delete(credential)
            await session.commit()
            return True

    async def rotate_credential(
        self,
        credential_id: uuid.UUID,
        new_secrets: List[CredentialSecretCreate],
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[TokenRotationResult]:
        if not new_secrets:
            raise ValueError("At least one replacement secret is required")
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == credential_id
            )
            if credential is None:
                return None
            result = await session.execute(
                self._tenant_query(CredentialSecret, tenant_id).where(
                    CredentialSecret.credential_id == credential_id
                )
            )
            existing = list(result.scalars().all())
            old_hash = hashlib.sha256(existing[0].encrypted_value.encode()).hexdigest() if existing else None
            for secret in existing:
                await session.delete(secret)
            for secret_data in new_secrets:
                encrypted = encrypt_data(secret_data.encrypted_value).decode("ascii")
                session.add(
                    CredentialSecret(
                        tenant_id=tenant_id,
                        credential_id=credential.id,
                        secret_type=secret_data.secret_type,
                        encrypted_value=encrypted,
                        secret_metadata=secret_data.secret_metadata,
                    )
                )
            credential.status = CredentialStatus.ACTIVE.value
            credential.updated_at = datetime.utcnow()
            new_hash = hashlib.sha256(new_secrets[0].encrypted_value.encode()).hexdigest()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.ROTATED,
                action="credential_rotation",
                resource_type="credential",
                resource_id=str(credential.id),
                credential_id=credential.id,
                metadata={"old_token_hash": old_hash, "new_token_hash": new_hash},
            )
            await session.commit()
            return TokenRotationResult(
                credential_id=credential.id,
                old_token_hash=old_hash,
                new_token="",
                new_token_hash=new_hash,
                rotation_time=datetime.utcnow(),
                metadata={"secret_count": len(new_secrets)},
            )

    async def revoke_credential(
        self,
        credential_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == credential_id
            )
            if credential is None:
                return False
            credential.status = CredentialStatus.REVOKED.value
            credential.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.REVOKED,
                action="credential_revocation",
                resource_type="credential",
                resource_id=str(credential.id),
                credential_id=credential.id,
                metadata={"reason": reason} if reason else {},
            )
            await session.commit()
            return True

    async def create_external_account(
        self, account_data: ExternalAccountCreate, tenant_id: uuid.UUID, user_id: str
    ) -> ExternalAccount:
        async with self._session_scope() as session:
            provider = await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.id == account_data.provider_id
            )
            if provider is None:
                raise ValueError("Provider not found in tenant")
            account = ExternalAccount(
                tenant_id=tenant_id,
                provider_id=account_data.provider_id,
                account_identifier=account_data.account_identifier,
                display_name=account_data.display_name,
                account_metadata=account_data.account_metadata,
                capabilities=account_data.capabilities,
                is_active=account_data.is_active,
            )
            session.add(account)
            await session.flush()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.CREATED,
                action="account_creation",
                resource_type="account",
                resource_id=str(account.id),
                account_id=account.id,
                provider_id=provider.id,
            )
            await session.commit()
            return account

    async def get_external_account(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[ExternalAccount]:
        async with self._session_scope() as session:
            query = self._tenant_query(ExternalAccount, tenant_id).options(
                selectinload(ExternalAccount.bindings)
            ).where(ExternalAccount.id == account_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def list_external_accounts(
        self,
        tenant_id: uuid.UUID,
        provider_id: Optional[str] = None,
        account_identifier: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExternalAccount]:
        async with self._session_scope() as session:
            query = self._tenant_query(ExternalAccount, tenant_id).options(
                selectinload(ExternalAccount.bindings)
            )
            if provider_id:
                provider = await self._tenant_entity(
                    session, ProviderDefinition, tenant_id, ProviderDefinition.provider_id == provider_id
                )
                if provider is None:
                    return []
                query = query.where(ExternalAccount.provider_id == provider.id)
            if account_identifier:
                query = query.where(ExternalAccount.account_identifier == account_identifier)
            if active_only:
                query = query.where(ExternalAccount.is_active.is_(True))
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())

    async def update_external_account(
        self,
        account_id: uuid.UUID,
        update_data: ExternalAccountUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[ExternalAccount]:
        async with self._session_scope() as session:
            account = await self._tenant_entity(
                session, ExternalAccount, tenant_id, ExternalAccount.id == account_id
            )
            if account is None:
                return None
            patch = update_data.model_dump(exclude_unset=True)
            for field, value in patch.items():
                setattr(account, field, value)
            account.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.UPDATED,
                action="account_update",
                resource_type="account",
                resource_id=str(account.id),
                account_id=account.id,
                metadata={"updated_fields": sorted(patch)},
            )
            await session.commit()
            return account

    async def delete_external_account(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID, user_id: str
    ) -> bool:
        async with self._session_scope() as session:
            account = await self._tenant_entity(
                session, ExternalAccount, tenant_id, ExternalAccount.id == account_id
            )
            if account is None:
                return False
            bindings = await session.execute(
                self._tenant_query(CredentialBinding, tenant_id).where(
                    CredentialBinding.external_account_id == account_id,
                    CredentialBinding.is_active.is_(True),
                )
            )
            if bindings.scalars().first() is not None:
                return False
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.DELETED,
                action="account_deletion",
                resource_type="account",
                resource_id=str(account.id),
                account_id=account.id,
            )
            await session.delete(account)
            await session.commit()
            return True

    async def create_binding(
        self, binding_data: CredentialBindingCreate, tenant_id: uuid.UUID, user_id: str
    ) -> CredentialBinding:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == binding_data.credential_id
            )
            account = await self._tenant_entity(
                session, ExternalAccount, tenant_id, ExternalAccount.id == binding_data.external_account_id
            )
            if credential is None or account is None:
                raise ValueError("Credential and account must belong to the tenant")
            binding = CredentialBinding(
                tenant_id=tenant_id,
                credential_id=credential.id,
                external_account_id=account.id,
                is_active=binding_data.is_active,
                is_primary=binding_data.is_primary,
                binding_metadata=binding_data.binding_metadata,
            )
            session.add(binding)
            await session.flush()
            if binding.is_primary and binding.is_active:
                result = await session.execute(
                    self._tenant_query(CredentialBinding, tenant_id).where(
                        CredentialBinding.external_account_id == account.id,
                        CredentialBinding.id != binding.id,
                        CredentialBinding.is_primary.is_(True),
                        CredentialBinding.is_active.is_(True),
                    )
                )
                for other in result.scalars().all():
                    other.is_primary = False
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.BINDING_CREATED,
                action="binding_creation",
                resource_type="binding",
                resource_id=str(binding.id),
                credential_id=credential.id,
                account_id=account.id,
            )
            await session.commit()
            return binding

    async def get_binding(
        self, binding_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[CredentialBinding]:
        async with self._session_scope() as session:
            query = self._tenant_query(CredentialBinding, tenant_id).options(
                selectinload(CredentialBinding.credential),
                selectinload(CredentialBinding.external_account),
            ).where(CredentialBinding.id == binding_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def list_bindings(
        self,
        tenant_id: uuid.UUID,
        credential_id: Optional[uuid.UUID] = None,
        external_account_id: Optional[uuid.UUID] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CredentialBinding]:
        async with self._session_scope() as session:
            query = self._tenant_query(CredentialBinding, tenant_id)
            if credential_id:
                query = query.where(CredentialBinding.credential_id == credential_id)
            if external_account_id:
                query = query.where(CredentialBinding.external_account_id == external_account_id)
            if active_only:
                query = query.where(CredentialBinding.is_active.is_(True))
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())

    async def update_binding(
        self,
        binding_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        is_primary: Optional[bool] = None,
        binding_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CredentialBinding]:
        async with self._session_scope() as session:
            binding = await self._tenant_entity(
                session, CredentialBinding, tenant_id, CredentialBinding.id == binding_id
            )
            if binding is None:
                return None
            if is_primary is not None:
                binding.is_primary = is_primary
                if is_primary and binding.is_active:
                    result = await session.execute(
                        self._tenant_query(CredentialBinding, tenant_id).where(
                            CredentialBinding.external_account_id == binding.external_account_id,
                            CredentialBinding.id != binding.id,
                            CredentialBinding.is_primary.is_(True),
                            CredentialBinding.is_active.is_(True),
                        )
                    )
                    for other in result.scalars().all():
                        other.is_primary = False
            if binding_metadata is not None:
                binding.binding_metadata = binding_metadata
            binding.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.BINDING_UPDATED,
                action="binding_update",
                resource_type="binding",
                resource_id=str(binding.id),
                credential_id=binding.credential_id,
                account_id=binding.external_account_id,
            )
            await session.commit()
            return binding

    async def delete_binding(
        self, binding_id: uuid.UUID, tenant_id: uuid.UUID, user_id: str
    ) -> bool:
        async with self._session_scope() as session:
            binding = await self._tenant_entity(
                session, CredentialBinding, tenant_id, CredentialBinding.id == binding_id
            )
            if binding is None:
                return False
            binding.is_active = False
            binding.is_primary = False
            binding.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.BINDING_REVOKED,
                action="binding_revocation",
                resource_type="binding",
                resource_id=str(binding.id),
                credential_id=binding.credential_id,
                account_id=binding.external_account_id,
            )
            await session.commit()
            return True

    async def create_oauth_grant(
        self, grant_data: AuthGrantCreate, tenant_id: uuid.UUID, user_id: str
    ) -> AuthGrant:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == grant_data.credential_id
            )
            provider = await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.id == grant_data.provider_id
            )
            if credential is None or provider is None:
                raise ValueError("Credential and provider must belong to the tenant")
            grant = AuthGrant(
                tenant_id=tenant_id,
                credential_id=credential.id,
                provider_id=provider.id,
                grant_type=grant_data.grant_type,
                authorization_code=grant_data.authorization_code,
                access_token=grant_data.access_token,
                refresh_token=grant_data.refresh_token,
                scopes=grant_data.scopes,
                expires_at=grant_data.expires_at,
                redirect_uri=grant_data.redirect_uri,
                state=grant_data.state,
                code_challenge=grant_data.code_challenge,
                code_challenge_method=grant_data.code_challenge_method,
                is_completed=grant_data.is_completed,
            )
            session.add(grant)
            await session.flush()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.CREATED,
                action="oauth_grant_creation",
                resource_type="grant",
                resource_id=str(grant.id),
                credential_id=credential.id,
                provider_id=provider.id,
            )
            await session.commit()
            return grant

    async def complete_oauth_grant(
        self,
        grant_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> Optional[AuthGrant]:
        async with self._session_scope() as session:
            grant = await self._tenant_entity(session, AuthGrant, tenant_id, AuthGrant.id == grant_id)
            if grant is None:
                return None
            grant.access_token = encrypt_data(access_token).decode("ascii")
            grant.refresh_token = encrypt_data(refresh_token).decode("ascii") if refresh_token else None
            grant.scopes = scopes or grant.scopes
            grant.is_completed = True
            grant.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.AUTHENTICATED,
                action="oauth_completion",
                resource_type="grant",
                resource_id=str(grant.id),
                credential_id=grant.credential_id,
                provider_id=grant.provider_id,
            )
            await session.commit()
            return grant

    async def refresh_oauth_token(
        self,
        credential_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        refresh_token: str,
        new_scopes: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self._session_scope() as session:
            result = await session.execute(
                self._tenant_query(AuthGrant, tenant_id).where(
                    AuthGrant.credential_id == credential_id,
                    AuthGrant.is_completed.is_(True),
                )
            )
            grants = list(result.scalars().all())
            grant: Optional[AuthGrant] = None
            for candidate in grants:
                if candidate.refresh_token and decrypt_data(candidate.refresh_token.encode("ascii")) == refresh_token:
                    grant = candidate
                    break
            if grant is None or (grant.expires_at and grant.expires_at < datetime.utcnow()):
                return None
            new_access = secrets.token_urlsafe(48)
            new_refresh = secrets.token_urlsafe(48)
            grant.access_token = encrypt_data(new_access).decode("ascii")
            grant.refresh_token = encrypt_data(new_refresh).decode("ascii")
            grant.scopes = new_scopes or grant.scopes
            grant.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.REFRESHED,
                action="oauth_token_refresh",
                resource_type="grant",
                resource_id=str(grant.id),
                credential_id=grant.credential_id,
                provider_id=grant.provider_id,
            )
            await session.commit()
            return {
                "access_token": new_access,
                "refresh_token": new_refresh,
                "scopes": grant.scopes,
            }

    async def create_account_session(
        self, session_data: AccountSessionCreate, tenant_id: uuid.UUID, user_id: str
    ) -> AccountSession:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == session_data.credential_id
            )
            account = await self._tenant_entity(
                session, ExternalAccount, tenant_id, ExternalAccount.id == session_data.external_account_id
            )
            if credential is None or account is None:
                raise ValueError("Credential and account must belong to the tenant")
            record = AccountSession(
                tenant_id=tenant_id,
                credential_id=credential.id,
                external_account_id=account.id,
                session_token=session_data.session_token,
                access_token=encrypt_data(session_data.access_token).decode("ascii") if session_data.access_token else None,
                refresh_token=encrypt_data(session_data.refresh_token).decode("ascii") if session_data.refresh_token else None,
                token_type=self._enum_value(session_data.token_type),
                expires_at=session_data.expires_at,
                scopes=session_data.scopes,
                session_metadata=session_data.session_metadata,
                ip_address=session_data.ip_address,
                user_agent=session_data.user_agent,
            )
            session.add(record)
            await session.flush()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.AUTHENTICATED,
                action="account_session_creation",
                resource_type="session",
                resource_id=str(record.id),
                credential_id=credential.id,
                account_id=account.id,
            )
            await session.commit()
            return record

    async def get_account_session(
        self, session_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[AccountSession]:
        async with self._session_scope() as session:
            return await self._tenant_entity(
                session, AccountSession, tenant_id, AccountSession.id == session_id
            )

    async def list_account_sessions(
        self,
        tenant_id: uuid.UUID,
        credential_id: Optional[uuid.UUID] = None,
        external_account_id: Optional[uuid.UUID] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AccountSession]:
        async with self._session_scope() as session:
            query = self._tenant_query(AccountSession, tenant_id)
            if credential_id:
                query = query.where(AccountSession.credential_id == credential_id)
            if external_account_id:
                query = query.where(AccountSession.external_account_id == external_account_id)
            if active_only:
                query = query.where(AccountSession.is_active.is_(True))
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())

    async def invalidate_account_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        async with self._session_scope() as session:
            record = await self._tenant_entity(
                session, AccountSession, tenant_id, AccountSession.id == session_id
            )
            if record is None:
                return False
            record.is_active = False
            record.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.EXPIRED,
                action="session_invalidation",
                resource_type="session",
                resource_id=str(record.id),
                credential_id=record.credential_id,
                account_id=record.external_account_id,
                metadata={"reason": reason} if reason else {},
            )
            await session.commit()
            return True

    async def record_login_attempt(
        self, attempt_data: LoginAttemptCreate, tenant_id: uuid.UUID, user_id: str
    ) -> LoginAttempt:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == attempt_data.credential_id
            )
            if credential is None:
                raise ValueError("Credential not found in tenant")
            account = None
            if attempt_data.external_account_id:
                account = await self._tenant_entity(
                    session,
                    ExternalAccount,
                    tenant_id,
                    ExternalAccount.id == attempt_data.external_account_id,
                )
                if account is None:
                    raise ValueError("Account not found in tenant")
            attempt = LoginAttempt(
                tenant_id=tenant_id,
                credential_id=credential.id,
                external_account_id=account.id if account else None,
                attempt_type=attempt_data.attempt_type,
                status=self._enum_value(attempt_data.status),
                error_code=attempt_data.error_code,
                error_message=attempt_data.error_message,
                ip_address=attempt_data.ip_address,
                user_agent=attempt_data.user_agent,
                attempt_metadata=attempt_data.attempt_metadata,
            )
            session.add(attempt)
            await session.flush()
            event = AuditEventType.AUTHENTICATED if self._enum_value(attempt_data.status) == LoginStatus.SUCCESS.value else AuditEventType.UPDATED
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=event,
                action="authentication_attempt",
                resource_type="login_attempt",
                resource_id=str(attempt.id),
                credential_id=credential.id,
                account_id=account.id if account else None,
                metadata={"status": self._enum_value(attempt_data.status)},
            )
            await session.commit()
            return attempt

    async def create_token_lease(
        self, lease_data: TokenLeaseCreate, tenant_id: uuid.UUID, user_id: str
    ) -> TokenLease:
        async with self._session_scope() as session:
            credential = await self._tenant_entity(
                session, Credential, tenant_id, Credential.id == lease_data.credential_id
            )
            if credential is None:
                raise ValueError("Credential not found in tenant")
            lease = TokenLease(
                tenant_id=tenant_id,
                credential_id=credential.id,
                lease_token=lease_data.lease_token,
                access_token=encrypt_data(lease_data.access_token).decode("ascii") if lease_data.access_token else None,
                expires_at=lease_data.expires_at,
                scopes=lease_data.scopes,
                lease_metadata=lease_data.lease_metadata,
            )
            session.add(lease)
            await session.flush()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.CREATED,
                action="token_lease_creation",
                resource_type="token_lease",
                resource_id=str(lease.id),
                credential_id=credential.id,
            )
            await session.commit()
            return lease

    async def get_token_lease(self, lease_token: str, tenant_id: uuid.UUID) -> Optional[TokenLease]:
        async with self._session_scope() as session:
            return await self._tenant_entity(
                session,
                TokenLease,
                tenant_id,
                TokenLease.lease_token == lease_token,
                TokenLease.is_active.is_(True),
            )

    async def invalidate_token_lease(
        self,
        lease_token: str,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        async with self._session_scope() as session:
            lease = await self._tenant_entity(
                session, TokenLease, tenant_id, TokenLease.lease_token == lease_token
            )
            if lease is None:
                return False
            lease.is_active = False
            lease.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.EXPIRED,
                action="token_lease_invalidation",
                resource_type="token_lease",
                resource_id=str(lease.id),
                credential_id=lease.credential_id,
                metadata={"reason": reason} if reason else {},
            )
            await session.commit()
            return True

    async def discover_account_capabilities(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID, user_id: str
    ) -> Optional[AccountCapabilityDiscovery]:
        async with self._session_scope() as session:
            account = await self._tenant_entity(
                session, ExternalAccount, tenant_id, ExternalAccount.id == account_id
            )
            if account is None:
                return None
            provider = await self._tenant_entity(
                session, ProviderDefinition, tenant_id, ProviderDefinition.id == account.provider_id
            )
            if provider is None:
                return None
            capabilities: List[AccountCapability] = []
            provider_key = provider.provider_id.lower()
            if provider.provider_type == ProviderType.OAUTH2.value:
                if "gmail" in provider_key or "google" in provider_key:
                    capabilities = [
                        AccountCapability.GMAIL_READ,
                        AccountCapability.GMAIL_SEND,
                        AccountCapability.CALENDAR_READ,
                        AccountCapability.CALENDAR_WRITE,
                        AccountCapability.DRIVE_READ,
                        AccountCapability.DRIVE_WRITE,
                    ]
                elif "github" in provider_key:
                    capabilities = [AccountCapability.GITHUB_READ, AccountCapability.GITHUB_WRITE, AccountCapability.GITHUB_REPO]
                elif "openai" in provider_key:
                    capabilities = [AccountCapability.OPENAI_CHAT, AccountCapability.OPENAI_EMBEDDINGS]
            account.capabilities = [cap.value for cap in capabilities]
            account.last_verified_at = datetime.utcnow()
            account.updated_at = datetime.utcnow()
            await self._audit(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=AuditEventType.UPDATED,
                action="capability_discovery",
                resource_type="account",
                resource_id=str(account.id),
                account_id=account.id,
                provider_id=provider.id,
                metadata={"capabilities": account.capabilities},
            )
            await session.commit()
            return AccountCapabilityDiscovery(
                account_id=account.id,
                provider_id=provider.id,
                account_identifier=account.account_identifier,
                discovered_capabilities=capabilities,
                verified_at=account.last_verified_at,
                metadata={"provider_type": provider.provider_type},
            )

    async def get_credential_health(
        self, credential_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[CredentialHealthStatus]:
        credential = await self.get_credential(credential_id, tenant_id)
        if credential is None:
            return None
        issues: List[str] = []
        if credential.status in {
            CredentialStatus.EXPIRED.value,
            CredentialStatus.REFRESH_REQUIRED.value,
            CredentialStatus.INVALID.value,
            CredentialStatus.REVOKED.value,
        }:
            issues.append(f"Credential status is {credential.status}")
        if is_token_expired(credential.expires_at):
            issues.append("Token has expired")
        next_check = (
            datetime.utcnow() + timedelta(hours=credential.rotation_interval_hours)
            if credential.rotation_interval_hours
            else None
        )
        return CredentialHealthStatus(
            credential_id=credential.id,
            status=credential.status,
            health_score=calculate_health_score(credential),
            expires_at=credential.expires_at,
            needs_rotation=credential.status == CredentialStatus.REFRESH_REQUIRED.value,
            issues=issues,
            last_check=datetime.utcnow(),
            next_check=next_check,
        )

    async def list_credentials_needing_attention(
        self, tenant_id: uuid.UUID, limit: int = 100
    ) -> List[CredentialHealthStatus]:
        async with self._session_scope() as session:
            result = await session.execute(
                self._tenant_query(Credential, tenant_id).where(
                    or_(
                        Credential.status.in_(
                            [
                                CredentialStatus.EXPIRED.value,
                                CredentialStatus.REFRESH_REQUIRED.value,
                                CredentialStatus.INVALID.value,
                                CredentialStatus.REVOKED.value,
                            ]
                        ),
                        Credential.expires_at < datetime.utcnow(),
                    )
                ).limit(limit)
            )
            credentials = list(result.scalars().all())
        health: List[CredentialHealthStatus] = []
        for credential in credentials:
            item = await self.get_credential_health(credential.id, tenant_id)
            if item:
                health.append(item)
        return health

    async def get_credential_bindings(
        self, credential_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[CredentialBinding]:
        return await self.list_bindings(tenant_id=tenant_id, credential_id=credential_id)

    async def get_external_account_bindings(
        self, external_account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[CredentialBinding]:
        return await self.list_bindings(tenant_id=tenant_id, external_account_id=external_account_id)

    async def get_audit_events(
        self,
        tenant_id: uuid.UUID,
        user_id: Optional[str] = None,
        credential_id: Optional[uuid.UUID] = None,
        account_id: Optional[uuid.UUID] = None,
        event_type: Optional[AuditEventType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CredentialAuditEvent]:
        async with self._session_scope() as session:
            query = self._tenant_query(CredentialAuditEvent, tenant_id)
            if user_id:
                query = query.where(CredentialAuditEvent.user_id == user_id)
            if credential_id:
                query = query.where(CredentialAuditEvent.credential_id == credential_id)
            if account_id:
                query = query.where(CredentialAuditEvent.account_id == account_id)
            if event_type:
                query = query.where(CredentialAuditEvent.event_type == event_type.value)
            result = await session.execute(
                query.order_by(CredentialAuditEvent.timestamp.desc()).limit(limit).offset(offset)
            )
            return list(result.scalars().all())

    async def get_audit_events_by_correlation_id(
        self, correlation_id: str, tenant_id: uuid.UUID
    ) -> List[CredentialAuditEvent]:
        async with self._session_scope() as session:
            result = await session.execute(
                self._tenant_query(CredentialAuditEvent, tenant_id).where(
                    CredentialAuditEvent.correlation_id == correlation_id
                )
            )
            return list(result.scalars().all())


__all__ = ["CredentialVaultService", "IdentityVaultConfig"]
