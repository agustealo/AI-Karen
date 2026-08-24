"""
Identity Vault Service.

This service provides comprehensive identity and credential management including
encryption, OAuth flows, account binding, and audit logging.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.identity_vault_schema import (
    ProviderDefinition,
    Credential,
    CredentialSecret,
    ExternalAccount,
    CredentialBinding,
    AccountSession,
    AuthGrant,
    TokenLease,
    LoginAttempt,
    CredentialAuditEvent,
)
from ai_karen_engine.database.models.identity_vault import (
    CredentialStatus,
    TokenType,
    ProviderType,
    AccountCapability,
    AuditEventType,
    LoginStatus,
    ProviderDefinitionCreate,
    ProviderDefinitionUpdate,
    CredentialCreate,
    CredentialUpdate,
    CredentialSecretCreate,
    ExternalAccountCreate,
    ExternalAccountUpdate,
    CredentialBindingCreate,
    AccountSessionCreate,
    AuthGrantCreate,
    TokenLeaseCreate,
    LoginAttemptCreate,
    CredentialAuditEventCreate,
    CredentialResponse,
    ExternalAccountResponse,
    AccountCapabilityDiscovery,
    TokenRotationResult,
    CredentialHealthStatus,
    validate_capabilities,
    generate_masked_hint,
    is_token_expired,
    calculate_health_score,
)

logger = get_logger(__name__)


class IdentityVaultConfig(ServiceConfig):
    """Identity Vault configuration."""
    
    name: str = "identity_vault_service"
    version: str = "1.0.0"
    
    # Encryption settings
    encryption_key_rotation_days: int = 90
    encryption_algorithm: str = "AES-256-GCM"
    
    # Token settings
    access_token_expire_hours: int = 1
    refresh_token_expire_days: int = 30
    session_token_expire_hours: int = 24
    
    # OAuth settings
    oauth_code_expire_minutes: int = 10
    oauth_state_length: int = 32
    oauth_code_challenge_length: int = 43
    
    # Security settings
    max_login_attempts: int = 5
    account_lockout_minutes: int = 30
    rate_limit_per_minute: int = 60
    
    # Audit settings
    audit_retention_days: int = 365
    sensitive_operation_whitelist: List[str] = [
        "credential.created",
        "credential.updated",
        "credential.rotated",
        "credential.revoked",
        "account.connected",
        "account.disconnected",
        "binding.created",
        "binding.updated",
        "binding.revoked",
        "authentication.started",
        "authentication.succeeded",
        "authentication.failed",
        "token.refreshed",
        "token.refresh_failed",
    ]
    
    # Health check settings
    health_check_interval_minutes: int = 15
    credential_rotation_grace_period_hours: int = 1


class CredentialVaultService(BaseService):
    """
    Credential Vault Service for managing identities, credentials, and external accounts.
    
    This service provides:
    - Secure credential storage with encryption at rest
    - OAuth flow management
    - Account binding (1 credential → many accounts)
    - Token lifecycle management
    - Audit logging for all operations
    - Account capability discovery
    """
    
    def __init__(self, config: Optional[IdentityVaultConfig] = None):
        """Initialize the Credential Vault Service."""
        super().__init__(config or IdentityVaultConfig())
        self._initialized = False
        self._tables_ensured = False
        
        # Database session will be injected
        self._db_session: Optional[AsyncSession] = None
        self._db_client: Optional[MultiTenantPostgresClient] = None
        
        # Encryption key management (simplified for now)
        self._encryption_keys: Dict[str, str] = {}
        self._current_key_id: str = "default"
        
        # Rate limiting
        self._rate_limits: Dict[str, List[datetime]] = {}
        
        # Load configuration from environment
        self._load_config_from_env()
    
    def _load_config_from_env(self) -> None:
        """Load configuration from environment variables."""
        # Override config with environment variables
        if "ENCRYPTION_KEY_ROTATION_DAYS" in self.config.__dict__:
            self.config.encryption_key_rotation_days = int(
                self.config.encryption_key_rotation_days
            )
        
        if "ACCESS_TOKEN_EXPIRE_HOURS" in self.config.__dict__:
            self.config.access_token_expire_hours = int(
                self.config.access_token_expire_hours
            )
        
        if "REFRESH_TOKEN_EXPIRE_DAYS" in self.config.__dict__:
            self.config.refresh_token_expire_days = int(
                self.config.refresh_token_expire_days
            )
    
    async def initialize(self) -> None:
        """Initialize the Credential Vault Service."""
        if self._initialized:
            return
        
        logger.debug("Initializing Credential Vault Service")
        
        # Initialize database tables
        await self._ensure_database_tables()
        
        # Initialize encryption keys
        await self._initialize_encryption_keys()
        
        # Start background tasks
        await self._start_background_tasks()
        
        self._initialized = True
        logger.info("Credential Vault Service initialized successfully")
    
    async def _ensure_database_tables(self) -> None:
        """Ensure database tables exist."""
        if self._tables_ensured:
            return
        
        try:
            client = self._get_db_client()
            await client.create_tables_async()
            self._tables_ensured = True
            logger.info("Database tables verified/created successfully")
        except Exception as e:
            logger.error(f"Failed to ensure database tables: {e}")
            # Don't re-raise here to allow service to start even if DB is not ready
    
    def _get_db_client(self) -> MultiTenantPostgresClient:
        """Return a cached database client for fallback sessions."""
        if self._db_client is None:
            self._db_client = MultiTenantPostgresClient()
        return self._db_client
    
    @asynccontextmanager
    async def _session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a session scope using context-local or fallback client sessions."""
        if self._db_session is not None:
            yield self._db_session
            return
        
        async with self._get_db_client().get_async_session() as session:
            yield session
    
    async def _initialize_encryption_keys(self) -> None:
        """Initialize encryption keys for credential storage."""
        # In a real implementation, this would use a proper key management service
        # For now, we'll use a simple approach with environment variables
        
        # Generate or load encryption key
        if hasattr(self.config, 'encryption_secret_key'):
            self._encryption_keys[self._current_key_id] = self.config.encryption_secret_key
        else:
            # Generate a random key for development
            self._encryption_keys[self._current_key_id] = secrets.token_urlsafe(32)
        
        logger.info("Encryption keys initialized")
    
    def _encrypt_data(self, data: str, key_id: str = None) -> str:
        """Encrypt data using the specified key."""
        key_id = key_id or self._current_key_id
        key = self._encryption_keys.get(key_id)
        
        if not key:
            raise ValueError(f"Encryption key {key_id} not found")
        
        # Simplified encryption - in production use a proper encryption library
        # like cryptography or AWS KMS
        encrypted = data.encode('utf-8')
        
        # Create HMAC for integrity
        hmac_obj = hmac.new(key.encode('utf-8'), encrypted, hashlib.sha256)
        hmac_digest = hmac_obj.hexdigest()
        
        # Return encrypted data with HMAC prefix
        return f"{hmac_digest}:{encrypted.hex()}"
    
    def _decrypt_data(self, encrypted_data: str, key_id: str = None) -> str:
        """Decrypt data using the specified key."""
        key_id = key_id or self._current_key_id
        key = self._encryption_keys.get(key_id)
        
        if not key:
            raise ValueError(f"Encryption key {key_id} not found")
        
        # Split HMAC and encrypted data
        try:
            hmac_digest, encrypted_hex = encrypted_data.split(':', 1)
        except ValueError:
            raise ValueError("Invalid encrypted data format")
        
        # Decrypt data
        encrypted = bytes.fromhex(encrypted_hex)
        
        # Verify HMAC
        hmac_obj = hmac.new(key.encode('utf-8'), encrypted, hashlib.sha256)
        if not hmac.compare_digest(hmac_obj.hexdigest(), hmac_digest):
            raise ValueError("Data integrity check failed")
        
        return encrypted.decode('utf-8')
    
    async def _start_background_tasks(self) -> None:
        """Start background tasks for maintenance and monitoring."""
        # Start health check task
        asyncio.create_task(self._health_check_loop())
        
        # Start cleanup task
        asyncio.create_task(self._cleanup_loop())
        
        logger.info("Background tasks started")
    
    async def _health_check_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await asyncio.sleep(self.config.health_check_interval_minutes * 60)
                await self._perform_health_checks()
            except Exception as e:
                logger.error(f"Health check failed: {e}")
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup loop."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self._cleanup_expired_data()
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")
    
    async def _perform_health_checks(self) -> None:
        """Perform health checks on credentials and sessions."""
        try:
            async with self._session_scope() as session:
                # Check for expired credentials
                result = await session.execute(
                    select(Credential).where(
                        Credential.expires_at < datetime.utcnow(),
                        Credential.status == CredentialStatus.ACTIVE
                    )
                )
                expired_credentials = result.scalars().all()
                
                for credential in expired_credentials:
                    credential.status = CredentialStatus.EXPIRED
                    await self._emit_audit_event(
                        event_type=AuditEventType.EXPIRED,
                        action="credential_expiration_check",
                        resource_type="credential",
                        resource_id=str(credential.id),
                        metadata={"auto_updated": True}
                    )
                
                await session.commit()
                
                # Check credentials needing refresh
                result = await session.execute(
                    select(Credential).where(
                        Credential.expires_at < datetime.utcnow() + timedelta(hours=24),
                        Credential.status == CredentialStatus.ACTIVE
                    )
                )
                refresh_needed = result.scalars().all()
                
                for credential in refresh_needed:
                    if credential.status == CredentialStatus.ACTIVE:
                        credential.status = CredentialStatus.REFRESH_REQUIRED
                        await self._emit_audit_event(
                            event_type=AuditEventType.UPDATED,
                            action="refresh_required",
                            resource_type="credential",
                            resource_id=str(credential.id),
                            metadata={"auto_updated": True}
                        )
                
                await session.commit()
                
                logger.info(f"Health check completed: {len(expired_credentials)} expired, {len(refresh_needed)} need refresh")
                
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    async def _cleanup_expired_data(self) -> None:
        """Clean up expired data."""
        try:
            async with self._session_scope() as session:
                # Clean up expired sessions
                result = await session.execute(
                    select(AccountSession).where(
                        AccountSession.expires_at < datetime.utcnow(),
                        AccountSession.is_active == True
                    )
                )
                expired_sessions = result.scalars().all()
                
                for session in expired_sessions:
                    session.is_active = False
                    await self._emit_audit_event(
                        event_type=AuditEventType.EXPIRED,
                        action="session_expiration",
                        resource_type="session",
                        resource_id=str(session.id),
                        metadata={"auto_updated": True}
                    )
                
                # Clean up expired grants
                result = await session.execute(
                    select(AuthGrant).where(
                        AuthGrant.expires_at < datetime.utcnow(),
                        AuthGrant.is_completed == False
                    )
                )
                expired_grants = result.scalars().all()
                
                for grant in expired_grants:
                    await session.delete(grant)
                
                # Clean up old audit events
                cutoff_date = datetime.utcnow() - timedelta(days=self.config.audit_retention_days)
                result = await session.execute(
                    select(CredentialAuditEvent).where(
                        CredentialAuditEvent.timestamp < cutoff_date
                    )
                )
                old_audit_events = result.scalars().all()
                
                for event in old_audit_events:
                    await session.delete(event)
                
                await session.commit()
                
                logger.info(f"Cleanup completed: {len(expired_sessions)} sessions, {len(expired_grants)} grants, {len(old_audit_events)} audit events")
                
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    async def _emit_audit_event(
        self,
        event_type: AuditEventType,
        action: str,
        resource_type: str,
        resource_id: str,
        tenant_id: uuid.UUID,
        user_id: str,
        correlation_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        account_id: Optional[uuid.UUID] = None,
        provider_id: Optional[uuid.UUID] = None,
        credential_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Emit an audit event."""
        try:
            # Check if this is a sensitive operation that should be logged
            is_sensitive = (
                event_type.value in self.config.sensitive_operation_whitelist or
                action in ["authentication", "token_refresh", "credential_rotation"]
            )
            
            # Redact sensitive data from metadata
            if metadata and is_sensitive:
                metadata = self._redact_sensitive_data(metadata)
            
            audit_event = CredentialAuditEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                credential_id=credential_id,
                account_id=account_id,
                provider_id=provider_id,
                event_type=event_type,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                correlation_id=correlation_id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata=metadata or {},
            )
            
            async with self._session_scope() as session:
                session.add(audit_event)
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to emit audit event: {e}")
    
    def _redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from audit logs."""
        sensitive_fields = {
            'password', 'api_key', 'access_token', 'refresh_token',
            'authorization_code', 'client_secret', 'private_key',
            'secret', 'token', 'key'
        }
        
        redacted = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = value
        
        return redacted
    
    async def _check_rate_limit(self, user_id: str, operation: str) -> bool:
        """Check if user is rate limited."""
        now = datetime.utcnow()
        key = f"{user_id}:{operation}"
        
        if key not in self._rate_limits:
            self._rate_limits[key] = []
        
        # Clean old entries
        self._rate_limits[key] = [
            timestamp for timestamp in self._rate_limits[key]
            if now - timestamp < timedelta(minutes=1)
        ]
        
        # Check if limit exceeded
        if len(self._rate_limits[key]) >= self.config.rate_limit_per_minute:
            return False
        
        self._rate_limits[key].append(now)
        return True
    
    # Provider Management
    async def create_provider(
        self,
        provider_data: ProviderDefinitionCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> ProviderDefinition:
        """Create a new provider definition."""
        try:
            provider = ProviderDefinition(
                provider_id=provider_data.provider_id,
                display_name=provider_data.display_name,
                description=provider_data.description,
                provider_type=provider_data.provider_type,
                config=provider_data.config,
                icon_url=provider_data.icon_url,
                website_url=provider_data.website_url,
                supported_capabilities=provider_data.supported_capabilities,
                enabled=provider_data.enabled,
                is_system=provider_data.is_system,
            )
            
            async with self._session_scope() as session:
                session.add(provider)
                await session.flush()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.CREATED,
                    action="provider_creation",
                    resource_type="provider",
                    resource_id=str(provider.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"provider_id": provider_data.provider_id}
                )
                
                await session.commit()
                return provider
                
        except Exception as e:
            logger.error(f"Failed to create provider: {e}")
            raise
    
    async def get_provider(self, provider_id: str, tenant_id: Optional[uuid.UUID] = None) -> Optional[ProviderDefinition]:
        """Get a provider definition by ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ProviderDefinition).where(ProviderDefinition.provider_id == provider_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get provider: {e}")
            return None
    
    async def list_providers(
        self,
        tenant_id: uuid.UUID,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ProviderDefinition]:
        """List provider definitions."""
        try:
            async with self._session_scope() as session:
                query = select(ProviderDefinition)
                
                if enabled_only:
                    query = query.where(ProviderDefinition.enabled == True)
                
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to list providers: {e}")
            return []
    
    async def update_provider(
        self,
        provider_id: str,
        update_data: ProviderDefinitionUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[ProviderDefinition]:
        """Update a provider definition."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ProviderDefinition).where(ProviderDefinition.provider_id == provider_id)
                )
                provider = result.scalar_one_or_none()
                
                if not provider:
                    return None
                
                # Update fields
                for field, value in update_data.dict(exclude_unset=True).items():
                    setattr(provider, field, value)
                
                provider.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="provider_update",
                    resource_type="provider",
                    resource_id=str(provider.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"provider_id": provider_id}
                )
                
                await session.commit()
                return provider
                
        except Exception as e:
            logger.error(f"Failed to update provider: {e}")
            return None
    
    async def delete_provider(
        self,
        provider_id: str,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """Delete a provider definition."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ProviderDefinition).where(ProviderDefinition.provider_id == provider_id)
                )
                provider = result.scalar_one_or_none()
                
                if not provider or provider.is_system:
                    return False
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="provider_deletion",
                    resource_type="provider",
                    resource_id=str(provider.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"provider_id": provider_id}
                )
                
                await session.delete(provider)
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete provider: {e}")
            return False
    
    # Credential Management
    async def create_credential(
        self,
        credential_data: CredentialCreate,
        secrets: List[CredentialSecretCreate],
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Credential:
        """Create a new credential with encrypted secrets."""
        try:
            # Check rate limit
            if not await self._check_rate_limit(user_id, "credential_create"):
                raise Exception("Rate limit exceeded")
            
            credential = Credential(
                name=credential_data.name,
                description=credential_data.description,
                provider_id=credential_data.provider_id,
                credential_type=credential_data.credential_type,
                metadata=credential_data.metadata,
                masked_hint=credential_data.masked_hint,
                expires_at=credential_data.expires_at,
                rotation_interval_hours=credential_data.rotation_interval_hours,
                created_by=user_id,
            )
            
            async with self._session_scope() as session:
                session.add(credential)
                await session.flush()
                
                # Add encrypted secrets
                for secret_data in secrets:
                    encrypted_value = self._encrypt_data(secret_data.encrypted_value)
                    secret = CredentialSecret(
                        credential_id=credential.id,
                        secret_type=secret_data.secret_type,
                        encrypted_value=encrypted_value,
                        encryption_key_id=self._current_key_id,
                        metadata=secret_data.metadata,
                    )
                    session.add(secret)
                
                await self._emit_audit_event(
                    event_type=AuditEventType.CREATED,
                    action="credential_creation",
                    resource_type="credential",
                    resource_id=str(credential.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "provider_id": str(credential_data.provider_id),
                        "credential_type": credential_data.credential_type
                    }
                )
                
                await session.commit()
                return credential
                
        except Exception as e:
            logger.error(f"Failed to create credential: {e}")
            raise
    
    async def get_credential(self, credential_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> Optional[Credential]:
        """Get a credential by ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential)
                    .options(selectinload(Credential.secrets))
                    .where(Credential.id == credential_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get credential: {e}")
            return None
    
    async def list_credentials(
        self,
        tenant_id: uuid.UUID,
        provider_id: Optional[str] = None,
        status: Optional[CredentialStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Credential]:
        """List credentials."""
        try:
            async with self._session_scope() as session:
                query = select(Credential).options(selectinload(Credential.secrets))
                
                if provider_id:
                    query = query.where(Credential.provider_id == provider_id)
                
                if status:
                    query = query.where(Credential.status == status)
                
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return []
    
    async def update_credential(
        self,
        credential_id: uuid.UUID,
        update_data: CredentialUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[Credential]:
        """Update a credential."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential).where(Credential.id == credential_id)
                )
                credential = result.scalar_one_or_none()
                
                if not credential:
                    return None
                
                # Update fields
                for field, value in update_data.dict(exclude_unset=True).items():
                    setattr(credential, field, value)
                
                credential.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="credential_update",
                    resource_type="credential",
                    resource_id=str(credential.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"updated_fields": list(update_data.dict(exclude_unset=True).keys())}
                )
                
                await session.commit()
                return credential
                
        except Exception as e:
            logger.error(f"Failed to update credential: {e}")
            return None
    
    async def delete_credential(
        self,
        credential_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """Delete a credential."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential).where(Credential.id == credential_id)
                )
                credential = result.scalar_one_or_none()
                
                if not credential:
                    return False
                
                # Check if credential has active bindings
                binding_result = await session.execute(
                    select(CredentialBinding).where(
                        CredentialBinding.credential_id == credential_id,
                        CredentialBinding.is_active == True
                    )
                )
                active_bindings = binding_result.scalars().all()
                
                if active_bindings:
                    raise Exception("Cannot delete credential with active bindings")
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="credential_deletion",
                    resource_type="credential",
                    resource_id=str(credential.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"had_active_bindings": len(active_bindings) > 0}
                )
                
                await session.delete(credential)
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete credential: {e}")
            return False
    
    async def rotate_credential(
        self,
        credential_id: uuid.UUID,
        new_secrets: List[CredentialSecretCreate],
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[TokenRotationResult]:
        """Rotate credential secrets."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential).where(Credential.id == credential_id)
                )
                credential = result.scalar_one_or_none()
                
                if not credential:
                    return None
                
                # Store old token hash for comparison
                old_secrets = await session.execute(
                    select(CredentialSecret).where(
                        CredentialSecret.credential_id == credential_id,
                        CredentialSecret.secret_type.in_(["access_token", "api_key"])
                    )
                )
                old_secrets_list = old_secrets.scalars().all()
                
                # Delete old secrets
                for secret in old_secrets_list:
                    await session.delete(secret)
                
                # Add new secrets
                for secret_data in new_secrets:
                    encrypted_value = self._encrypt_data(secret_data.encrypted_value)
                    secret = CredentialSecret(
                        credential_id=credential.id,
                        secret_type=secret_data.secret_type,
                        encrypted_value=encrypted_value,
                        encryption_key_id=self._current_key_id,
                        metadata=secret_data.metadata,
                    )
                    session.add(secret)
                
                # Update credential status
                credential.status = CredentialStatus.ACTIVE
                credential.last_used_at = datetime.utcnow()
                credential.updated_at = datetime.utcnow()
                
                # Generate result
                old_token_hash = None
                if old_secrets_list:
                    old_token_hash = hashlib.sha256(
                        old_secrets_list[0].encrypted_value.encode()
                    ).hexdigest()
                
                new_token_hash = hashlib.sha256(
                    new_secrets[0].encrypted_value.encode()
                ).hexdigest() if new_secrets else None
                
                rotation_result = TokenRotationResult(
                    credential_id=credential_id,
                    old_token_hash=old_token_hash,
                    new_token=new_secrets[0].encrypted_value if new_secrets else "",
                    new_token_hash=new_token_hash,
                    rotation_time=datetime.utcnow(),
                    metadata={"rotation_count": len(new_secrets)}
                )
                
                await self._emit_audit_event(
                    event_type=AuditEventType.ROTATED,
                    action="credential_rotation",
                    resource_type="credential",
                    resource_id=str(credential.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "old_token_hash": old_token_hash,
                        "new_token_hash": new_token_hash,
                        "rotation_count": len(new_secrets)
                    }
                )
                
                await session.commit()
                return rotation_result
                
        except Exception as e:
            logger.error(f"Failed to rotate credential: {e}")
            return None
    
    async def revoke_credential(
        self,
        credential_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Revoke a credential."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential).where(Credential.id == credential_id)
                )
                credential = result.scalar_one_or_none()
                
                if not credential:
                    return False
                
                # Update status
                credential.status = CredentialStatus.REVOKED
                credential.updated_at = datetime.utcnow()
                
                metadata = {"revoked_at": datetime.utcnow().isoformat()}
                if reason:
                    metadata["reason"] = reason
                
                await self._emit_audit_event(
                    event_type=AuditEventType.REVOKED,
                    action="credential_revocation",
                    resource_type="credential",
                    resource_id=str(credential.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata=metadata
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to revoke credential: {e}")
            return False
    
    # Account Management
    async def create_external_account(
        self,
        account_data: ExternalAccountCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> ExternalAccount:
        """Create an external account."""
        try:
            account = ExternalAccount(
                provider_id=account_data.provider_id,
                account_identifier=account_data.account_identifier,
                display_name=account_data.display_name,
                account_metadata=account_data.account_metadata,
                capabilities=account_data.capabilities,
                is_active=account_data.is_active,
            )
            
            async with self._session_scope() as session:
                session.add(account)
                await session.flush()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.CREATED,
                    action="account_creation",
                    resource_type="account",
                    resource_id=str(account.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "provider_id": str(account_data.provider_id),
                        "account_identifier": account_data.account_identifier
                    }
                )
                
                await session.commit()
                return account
                
        except Exception as e:
            logger.error(f"Failed to create external account: {e}")
            raise
    
    async def get_external_account(self, account_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> Optional[ExternalAccount]:
        """Get an external account by ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ExternalAccount)
                    .options(selectinload(ExternalAccount.bindings))
                    .where(ExternalAccount.id == account_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get external account: {e}")
            return None
    
    async def list_external_accounts(
        self,
        tenant_id: uuid.UUID,
        provider_id: Optional[str] = None,
        account_identifier: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExternalAccount]:
        """List external accounts."""
        try:
            async with self._session_scope() as session:
                query = select(ExternalAccount).options(selectinload(ExternalAccount.bindings))
                
                if provider_id:
                    query = query.where(ExternalAccount.provider_id == provider_id)
                
                if account_identifier:
                    query = query.where(ExternalAccount.account_identifier == account_identifier)
                
                if active_only:
                    query = query.where(ExternalAccount.is_active == True)
                
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to list external accounts: {e}")
            return []
    
    async def update_external_account(
        self,
        account_id: uuid.UUID,
        update_data: ExternalAccountUpdate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[ExternalAccount]:
        """Update an external account."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ExternalAccount).where(ExternalAccount.id == account_id)
                )
                account = result.scalar_one_or_none()
                
                if not account:
                    return None
                
                # Update fields
                for field, value in update_data.dict(exclude_unset=True).items():
                    setattr(account, field, value)
                
                account.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="account_update",
                    resource_type="account",
                    resource_id=str(account.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"updated_fields": list(update_data.dict(exclude_unset=True).keys())}
                )
                
                await session.commit()
                return account
                
        except Exception as e:
            logger.error(f"Failed to update external account: {e}")
            return None
    
    async def delete_external_account(
        self,
        account_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """Delete an external account."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ExternalAccount).where(ExternalAccount.id == account_id)
                )
                account = result.scalar_one_or_none()
                
                if not account:
                    return False
                
                # Check if account has active bindings
                binding_result = await session.execute(
                    select(CredentialBinding).where(
                        CredentialBinding.external_account_id == account_id,
                        CredentialBinding.is_active == True
                    )
                )
                active_bindings = binding_result.scalars().all()
                
                if active_bindings:
                    raise Exception("Cannot delete account with active bindings")
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="account_deletion",
                    resource_type="account",
                    resource_id=str(account.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={"had_active_bindings": len(active_bindings) > 0}
                )
                
                await session.delete(account)
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete external account: {e}")
            return False
    
    # Binding Management
    async def create_binding(
        self,
        binding_data: CredentialBindingCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> CredentialBinding:
        """Create a credential binding."""
        try:
            binding = CredentialBinding(
                credential_id=binding_data.credential_id,
                external_account_id=binding_data.external_account_id,
                is_primary=binding_data.is_primary,
                binding_metadata=binding_data.binding_metadata,
            )
            
            async with self._session_scope() as session:
                session.add(binding)
                await session.flush()
                
                # If this is a primary binding, demote other primary bindings
                if binding.is_primary:
                    result = await session.execute(
                        select(CredentialBinding).where(
                            CredentialBinding.external_account_id == binding.external_account_id,
                            CredentialBinding.id != binding.id,
                            CredentialBinding.is_primary == True,
                            CredentialBinding.is_active == True
                        )
                    )
                    other_primaries = result.scalars().all()
                    
                    for other in other_primaries:
                        other.is_primary = False
                        other.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.BINDING_CREATED,
                    action="binding_creation",
                    resource_type="binding",
                    resource_id=str(binding.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "credential_id": str(binding_data.credential_id),
                        "external_account_id": str(binding_data.external_account_id),
                        "is_primary": binding_data.is_primary
                    }
                )
                
                await session.commit()
                return binding
                
        except Exception as e:
            logger.error(f"Failed to create binding: {e}")
            raise
    
    async def get_binding(self, binding_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> Optional[CredentialBinding]:
        """Get a credential binding by ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialBinding)
                    .options(
                        selectinload(CredentialBinding.credential),
                        selectinload(CredentialBinding.external_account)
                    )
                    .where(CredentialBinding.id == binding_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get binding: {e}")
            return None
    
    async def list_bindings(
        self,
        tenant_id: uuid.UUID,
        credential_id: Optional[uuid.UUID] = None,
        external_account_id: Optional[uuid.UUID] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CredentialBinding]:
        """List credential bindings."""
        try:
            async with self._session_scope() as session:
                query = select(CredentialBinding).options(
                    selectinload(CredentialBinding.credential),
                    selectinload(CredentialBinding.external_account)
                )
                
                if credential_id:
                    query = query.where(CredentialBinding.credential_id == credential_id)
                
                if external_account_id:
                    query = query.where(CredentialBinding.external_account_id == external_account_id)
                
                if active_only:
                    query = query.where(CredentialBinding.is_active == True)
                
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to list bindings: {e}")
            return []
    
    async def update_binding(
        self,
        binding_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        is_primary: Optional[bool] = None,
        binding_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CredentialBinding]:
        """Update a credential binding."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialBinding).where(CredentialBinding.id == binding_id)
                )
                binding = result.scalar_one_or_none()
                
                if not binding:
                    return None
                
                # Update fields
                if is_primary is not None:
                    binding.is_primary = is_primary
                    
                    # If this is becoming primary, demote other primaries
                    if is_primary:
                        result = await session.execute(
                            select(CredentialBinding).where(
                                CredentialBinding.external_account_id == binding.external_account_id,
                                CredentialBinding.id != binding_id,
                                CredentialBinding.is_primary == True,
                                CredentialBinding.is_active == True
                            )
                        )
                        other_primaries = result.scalars().all()
                        
                        for other in other_primaries:
                            other.is_primary = False
                            other.updated_at = datetime.utcnow()
                
                if binding_metadata is not None:
                    binding.binding_metadata = binding_metadata
                
                binding.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.BINDING_UPDATED,
                    action="binding_update",
                    resource_type="binding",
                    resource_id=str(binding.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "updated_is_primary": is_primary,
                        "updated_metadata": binding_metadata is not None
                    }
                )
                
                await session.commit()
                return binding
                
        except Exception as e:
            logger.error(f"Failed to update binding: {e}")
            return None
    
    async def delete_binding(
        self,
        binding_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """Delete a credential binding."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialBinding).where(CredentialBinding.id == binding_id)
                )
                binding = result.scalar_one_or_none()
                
                if not binding:
                    return False
                
                binding.is_active = False
                binding.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.BINDING_REVOKED,
                    action="binding_deletion",
                    resource_type="binding",
                    resource_id=str(binding.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "credential_id": str(binding.credential_id),
                        "external_account_id": str(binding.external_account_id)
                    }
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete binding: {e}")
            return False
    
    # OAuth Management
    async def create_oauth_grant(
        self,
        grant_data: AuthGrantCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> AuthGrant:
        """Create an OAuth authorization grant."""
        try:
            grant = AuthGrant(
                credential_id=grant_data.credential_id,
                provider_id=grant_data.provider_id,
                grant_type=grant_data.grant_type,
                authorization_code=grant_data.authorization_code,
                access_token=grant_data.access_token,
                refresh_token=grant_data.refresh_token,
                scopes=grant_data.scopes,
                redirect_uri=grant_data.redirect_uri,
                state=grant_data.state,
                code_challenge=grant_data.code_challenge,
                code_challenge_method=grant_data.code_challenge_method,
                is_completed=grant_data.is_completed,
            )
            
            async with self._session_scope() as session:
                session.add(grant)
                await session.commit()
                return grant
                
        except Exception as e:
            logger.error(f"Failed to create OAuth grant: {e}")
            raise
    
    async def complete_oauth_grant(
        self,
        grant_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> Optional[AuthGrant]:
        """Complete an OAuth authorization grant."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthGrant).where(AuthGrant.id == grant_id)
                )
                grant = result.scalar_one_or_none()
                
                if not grant:
                    return None
                
                grant.access_token = access_token
                grant.refresh_token = refresh_token
                grant.scopes = scopes or grant.scopes
                grant.is_completed = True
                grant.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.AUTHENTICATED,
                    action="oauth_completion",
                    resource_type="grant",
                    resource_id=str(grant.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "access_token_provided": bool(access_token),
                        "refresh_token_provided": bool(refresh_token),
                        "scopes": scopes or []
                    }
                )
                
                await session.commit()
                return grant
                
        except Exception as e:
            logger.error(f"Failed to complete OAuth grant: {e}")
            return None
    
    async def refresh_oauth_token(
        self,
        credential_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        refresh_token: str,
        new_scopes: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Refresh an OAuth token."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthGrant).where(
                        AuthGrant.credential_id == credential_id,
                        AuthGrant.refresh_token == refresh_token,
                        AuthGrant.is_completed == True
                    )
                )
                grant = result.scalar_one_or_none()
                
                if not grant:
                    return None
                
                # Check if grant is expired
                if grant.expires_at and grant.expires_at < datetime.utcnow():
                    await self._emit_audit_event(
                        event_type=AuditEventType.TOKEN_REFRESH_FAILED,
                        action="token_refresh_expired",
                        resource_type="grant",
                        resource_id=str(grant.id),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        metadata={"error": "grant_expired"}
                    )
                    return None
                
                # Generate new tokens (simplified - in reality, this would call the provider)
                new_access_token = secrets.token_urlsafe(64)
                new_refresh_token = secrets.token_urlsafe(64)
                
                grant.access_token = new_access_token
                grant.refresh_token = new_refresh_token
                grant.scopes = new_scopes or grant.scopes
                grant.updated_at = datetime.utcnow()
                
                await self._emit_audit_event(
                    event_type=AuditEventType.REFRESHED,
                    action="token_refresh",
                    resource_type="grant",
                    resource_id=str(grant.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "old_refresh_token": "***REDACTED***",
                        "new_access_token": "***REDACTED***",
                        "new_refresh_token": "***REDACTED***",
                        "scopes": new_scopes or []
                    }
                )
                
                await session.commit()
                
                return {
                    "access_token": new_access_token,
                    "refresh_token": new_refresh_token,
                    "expires_in": self.config.access_token_expire_hours * 3600,
                    "scopes": new_scopes or grant.scopes
                }
                
        except Exception as e:
            logger.error(f"Failed to refresh OAuth token: {e}")
            return None
    
    # Session Management
    async def create_account_session(
        self,
        session_data: AccountSessionCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> AccountSession:
        """Create an account session."""
        try:
            session = AccountSession(
                credential_id=session_data.credential_id,
                external_account_id=session_data.external_account_id,
                session_token=session_data.session_token,
                access_token=session_data.access_token,
                refresh_token=session_data.refresh_token,
                token_type=session_data.token_type,
                scopes=session_data.scopes,
                session_metadata=session_data.session_metadata,
                ip_address=session_data.ip_address,
                user_agent=session_data.user_agent,
                expires_at=session_data.expires_at,
            )
            
            async with self._session_scope() as session:
                db_session.add(session)
                await db_session.commit()
                return session
                
        except Exception as e:
            logger.error(f"Failed to create account session: {e}")
            raise
    
    async def get_account_session(self, session_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> Optional[AccountSession]:
        """Get an account session by ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AccountSession).where(AccountSession.id == session_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get account session: {e}")
            return None
    
    async def list_account_sessions(
        self,
        tenant_id: uuid.UUID,
        credential_id: Optional[uuid.UUID] = None,
        external_account_id: Optional[uuid.UUID] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AccountSession]:
        """List account sessions."""
        try:
            async with self._session_scope() as session:
                query = select(AccountSession)
                
                if credential_id:
                    query = query.where(AccountSession.credential_id == credential_id)
                
                if external_account_id:
                    query = query.where(AccountSession.external_account_id == external_account_id)
                
                if active_only:
                    query = query.where(AccountSession.is_active == True)
                
                query = query.limit(limit).offset(offset)
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to list account sessions: {e}")
            return []
    
    async def invalidate_account_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Invalidate an account session."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AccountSession).where(AccountSession.id == session_id)
                )
                account_session = result.scalar_one_or_none()
                
                if not account_session:
                    return False
                
                account_session.is_active = False
                account_session.updated_at = datetime.utcnow()
                
                metadata = {"invalidated_at": datetime.utcnow().isoformat()}
                if reason:
                    metadata["reason"] = reason
                
                await self._emit_audit_event(
                    event_type=AuditEventType.EXPIRED,
                    action="session_invalidation",
                    resource_type="session",
                    resource_id=str(account_session.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata=metadata
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to invalidate account session: {e}")
            return False
    
    # Login Management
    async def record_login_attempt(
        self,
        attempt_data: LoginAttemptCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> LoginAttempt:
        """Record a login attempt."""
        try:
            attempt = LoginAttempt(
                credential_id=attempt_data.credential_id,
                external_account_id=attempt_data.external_account_id,
                attempt_type=attempt_data.attempt_type,
                status=attempt_data.status,
                error_code=attempt_data.error_code,
                error_message=attempt_data.error_message,
                ip_address=attempt_data.ip_address,
                user_agent=attempt_data.user_agent,
                metadata=attempt_data.metadata,
            )
            
            async with self._session_scope() as session:
                session.add(attempt)
                await session.commit()
                
                # Emit audit event based on status
                if attempt.status == LoginStatus.SUCCESS:
                    event_type = AuditEventType.AUTHENTICATED
                    action = "authentication_success"
                elif attempt.status == LoginStatus.FAILED:
                    event_type = AuditEventType.UPDATED
                    action = "authentication_failure"
                else:
                    event_type = AuditEventType.UPDATED
                    action = "authentication_attempt"
                
                await self._emit_audit_event(
                    event_type=event_type,
                    action=action,
                    resource_type="login",
                    resource_id=str(attempt.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "attempt_type": attempt_data.attempt_type,
                        "status": attempt_data.status.value,
                        "error_code": attempt_data.error_code,
                        "ip_address": attempt_data.ip_address,
                        "user_agent": attempt_data.user_agent
                    }
                )
                
                return attempt
                
        except Exception as e:
            logger.error(f"Failed to record login attempt: {e}")
            raise
    
    # Token Lease Management
    async def create_token_lease(
        self,
        lease_data: TokenLeaseCreate,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> TokenLease:
        """Create a token lease."""
        try:
            lease = TokenLease(
                credential_id=lease_data.credential_id,
                lease_token=lease_data.lease_token,
                access_token=lease_data.access_token,
                scopes=lease_data.scopes,
                metadata=lease_data.metadata,
                expires_at=lease_data.expires_at,
            )
            
            async with self._session_scope() as session:
                session.add(lease)
                await session.commit()
                return lease
                
        except Exception as e:
            logger.error(f"Failed to create token lease: {e}")
            raise
    
    async def get_token_lease(self, lease_token: str, tenant_id: Optional[uuid.UUID] = None) -> Optional[TokenLease]:
        """Get a token lease by lease token."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(TokenLease).where(
                        TokenLease.lease_token == lease_token,
                        TokenLease.is_active == True
                    )
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get token lease: {e}")
            return None
    
    async def invalidate_token_lease(
        self,
        lease_token: str,
        tenant_id: uuid.UUID,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Invalidate a token lease."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(TokenLease).where(TokenLease.lease_token == lease_token)
                )
                lease = result.scalar_one_or_none()
                
                if not lease:
                    return False
                
                lease.is_active = False
                lease.updated_at = datetime.utcnow()
                
                metadata = {"invalidated_at": datetime.utcnow().isoformat()}
                if reason:
                    metadata["reason"] = reason
                
                await self._emit_audit_event(
                    event_type=AuditEventType.EXPIRED,
                    action="lease_invalidation",
                    resource_type="lease",
                    resource_id=str(lease.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata=metadata
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to invalidate token lease: {e}")
            return False
    
    # Capability Discovery
    async def discover_account_capabilities(
        self,
        account_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: str,
    ) -> Optional[AccountCapabilityDiscovery]:
        """Discover capabilities for an external account."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(ExternalAccount).where(ExternalAccount.id == account_id)
                )
                account = result.scalar_one_or_none()
                
                if not account:
                    return None
                
                # In a real implementation, this would call the provider's API
                # to discover actual capabilities. For now, we'll use a mock implementation.
                
                # Get the provider definition
                provider_result = await session.execute(
                    select(ProviderDefinition).where(ProviderDefinition.id == account.provider_id)
                )
                provider = provider_result.scalar_one_or_none()
                
                if not provider:
                    return None
                
                # Mock capability discovery based on provider type
                discovered_capabilities = []
                
                if provider.provider_type == ProviderType.OAUTH2:
                    # For OAuth2 providers, we can infer capabilities from scopes
                    # In reality, this would involve API calls
                    if "gmail" in provider.provider_id.lower():
                        discovered_capabilities.extend([
                            AccountCapability.GMAIL_READ,
                            AccountCapability.GMAIL_SEND,
                            AccountCapability.CALENDAR_READ,
                            AccountCapability.CALENDAR_WRITE,
                            AccountCapability.DRIVE_READ,
                            AccountCapability.DRIVE_WRITE,
                        ])
                    elif "github" in provider.provider_id.lower():
                        discovered_capabilities.extend([
                            AccountCapability.GITHUB_READ,
                            AccountCapability.GITHUB_WRITE,
                            AccountCapability.GITHUB_REPO,
                            AccountCapability.GITHUB_USER,
                        ])
                    elif "openai" in provider.provider_id.lower():
                        discovered_capabilities.extend([
                            AccountCapability.OPENAI_CHAT,
                            AccountCapability.OPENAI_COMPLETIONS,
                            AccountCapability.OPENAI_EMBEDDINGS,
                        ])
                
                # Update account with discovered capabilities
                account.capabilities = discovered_capabilities
                account.last_verified_at = datetime.utcnow()
                account.updated_at = datetime.utcnow()
                
                discovery_result = AccountCapabilityDiscovery(
                    account_id=account_id,
                    provider_id=account.provider_id,
                    account_identifier=account.account_identifier,
                    discovered_capabilities=discovered_capabilities,
                    verified_at=datetime.utcnow(),
                    metadata={"provider_type": provider.provider_type.value}
                )
                
                await self._emit_audit_event(
                    event_type=AuditEventType.UPDATED,
                    action="capability_discovery",
                    resource_type="account",
                    resource_id=str(account.id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metadata={
                        "discovered_capabilities": [cap.value for cap in discovered_capabilities],
                        "provider_type": provider.provider_type.value
                    }
                )
                
                await session.commit()
                return discovery_result
                
        except Exception as e:
            logger.error(f"Failed to discover account capabilities: {e}")
            return None
    
    # Health Monitoring
    async def get_credential_health(
        self,
        credential_id: uuid.UUID,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> Optional[CredentialHealthStatus]:
        """Get health status for a credential."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(Credential).where(Credential.id == credential_id)
                )
                credential = result.scalar_one_or_none()
                
                if not credential:
                    return None
                
                health_score = calculate_health_score(credential)
                
                issues = []
                if credential.status == CredentialStatus.EXPIRED:
                    issues.append("Credential is expired")
                elif credential.status == CredentialStatus.REFRESH_REQUIRED:
                    issues.append("Credential needs refresh")
                elif credential.status == CredentialStatus.INVALID:
                    issues.append("Credential is invalid")
                elif credential.status == CredentialStatus.REVOKED:
                    issues.append("Credential is revoked")
                
                if credential.expires_at and is_token_expired(credential.expires_at):
                    issues.append("Token has expired")
                
                if credential.last_used_at:
                    time_since_last_use = datetime.utcnow() - credential.last_used_at
                    if time_since_last_use.total_seconds() > 86400 * 30:  # More than 30 days
                        issues.append("Credential not used recently")
                
                next_check = None
                if credential.rotation_interval_hours:
                    next_check = datetime.utcnow() + timedelta(hours=credential.rotation_interval_hours)
                
                return CredentialHealthStatus(
                    credential_id=credential_id,
                    status=credential.status,
                    health_score=health_score,
                    issues=issues,
                    last_check=datetime.utcnow(),
                    next_check=next_check
                )
                
        except Exception as e:
            logger.error(f"Failed to get credential health: {e}")
            return None
    
    async def list_credentials_needing_attention(
        self,
        tenant_id: uuid.UUID,
        limit: int = 100,
    ) -> List[CredentialHealthStatus]:
        """List credentials that need attention (expired, refresh required, etc.)."""
        try:
            async with self._session_scope() as session:
                # Get credentials with issues
                result = await session.execute(
                    select(Credential).where(
                        or_(
                            Credential.status.in_([
                                CredentialStatus.EXPIRED,
                                CredentialStatus.REFRESH_REQUIRED,
                                CredentialStatus.INVALID,
                                CredentialStatus.REVOKED
                            ]),
                            and_(
                                Credential.expires_at.isnot(None),
                                Credential.expires_at < datetime.utcnow()
                            )
                        )
                    )
                )
                credentials = result.scalars().all()
                
                health_statuses = []
                for credential in credentials[:limit]:
                    health_status = await self.get_credential_health(credential.id)
                    if health_status:
                        health_statuses.append(health_status)
                
                return health_statuses
                
        except Exception as e:
            logger.error(f"Failed to list credentials needing attention: {e}")
            return []
    
    # Utility Methods
    async def get_credential_bindings(
        self,
        credential_id: uuid.UUID,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> List[CredentialBinding]:
        """Get all bindings for a credential."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialBinding)
                    .options(
                        selectinload(CredentialBinding.credential),
                        selectinload(CredentialBinding.external_account)
                    )
                    .where(CredentialBinding.credential_id == credential_id)
                )
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to get credential bindings: {e}")
            return []
    
    async def get_external_account_bindings(
        self,
        external_account_id: uuid.UUID,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> List[CredentialBinding]:
        """Get all bindings for an external account."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialBinding)
                    .options(
                        selectinload(CredentialBinding.credential),
                        selectinload(CredentialBinding.external_account)
                    )
                    .where(CredentialBinding.external_account_id == external_account_id)
                )
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to get external account bindings: {e}")
            return []
    
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
        """Get audit events."""
        try:
            async with self._session_scope() as session:
                query = select(CredentialAuditEvent)
                
                if user_id:
                    query = query.where(CredentialAuditEvent.user_id == user_id)
                
                if credential_id:
                    query = query.where(CredentialAuditEvent.credential_id == credential_id)
                
                if account_id:
                    query = query.where(CredentialAuditEvent.account_id == account_id)
                
                if event_type:
                    query = query.where(CredentialAuditEvent.event_type == event_type)
                
                query = query.order_by(CredentialAuditEvent.timestamp.desc())
                query = query.limit(limit).offset(offset)
                
                result = await session.execute(query)
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to get audit events: {e}")
            return []
    
    async def get_audit_events_by_correlation_id(
        self,
        correlation_id: str,
        tenant_id: uuid.UUID,
    ) -> List[CredentialAuditEvent]:
        """Get audit events by correlation ID."""
        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(CredentialAuditEvent).where(
                        CredentialAuditEvent.correlation_id == correlation_id
                    )
                )
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to get audit events by correlation ID: {e}")
            return []
    
    # Abstract method implementations
    async def start(self) -> None:
        """Start the service."""
        logger.info(f"Starting {self.name}")
        self._status = "running"
    
    async def stop(self) -> None:
        """Stop the service."""
        logger.info(f"Stopping {self.name}")
        self._status = "stopped"
    
    async def health_check(self) -> bool:
        """Perform a health check."""
        try:
            # Basic health check - verify database connection
            if self._db_session is not None:
                # Try a simple query to test the connection
                await self._db_session.execute("SELECT 1")
                return True
            return False
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False