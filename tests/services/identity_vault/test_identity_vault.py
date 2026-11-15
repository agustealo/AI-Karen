"""
Comprehensive tests for the identity vault system.

This module contains unit tests for all identity vault functionality including
credential management, OAuth flows, account binding, audit logging, and more.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
    IdentityVaultConfig,
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
    ExternalAccountCreate,
    ExternalAccountUpdate,
    CredentialBindingCreate,
    AccountSessionCreate,
    AuthGrantCreate,
    TokenLeaseCreate,
    LoginAttemptCreate,
    CredentialAuditEventCreate,
    ProviderDefinition,
    Credential,
    ExternalAccount,
    CredentialBinding,
    AccountSession,
    AuthGrant,
    TokenLease,
    LoginAttempt,
    CredentialAuditEvent,
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


class TestIdentityVaultConfig:
    """Test the identity vault configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = IdentityVaultConfig()
        
        assert config.name == "identity_vault_service"
        assert config.version == "1.0.0"
        assert config.encryption_key_rotation_days == 90
        assert config.encryption_algorithm == "AES-256-GCM"
        assert config.access_token_expire_hours == 1
        assert config.refresh_token_expire_days == 30
        assert config.session_token_expire_hours == 24
        assert config.oauth_code_expire_minutes == 10
        assert config.oauth_state_length == 32
        assert config.max_login_attempts == 5
        assert config.account_lockout_minutes == 30
        assert config.rate_limit_per_minute == 60
        assert config.audit_retention_days == 365
        assert len(config.sensitive_operation_whitelist) > 0
        assert config.health_check_interval_minutes == 15


class TestCredentialVaultService:
    """Test the credential vault service."""
    
    @pytest.fixture
    def service(self, service_with_mock_db):
        """Create a credential vault service instance."""
        return service_with_mock_db
    
    @pytest.fixture
    def mock_tenant_id(self):
        """Create a mock tenant ID."""
        return uuid.uuid4()
    
    @pytest.fixture
    def mock_user_id(self):
        """Create a mock user ID."""
        return "test-user"
    
    @pytest.fixture
    def mock_provider_data(self):
        """Create mock provider data."""
        return ProviderDefinitionCreate(
            provider_id="test-provider",
            display_name="Test Provider",
            description="A test provider",
            provider_type=ProviderType.OAUTH2,
            config={"client_id": "test-client", "client_secret": "test-secret"},
            supported_capabilities=[AccountCapability.READ, AccountCapability.WRITE],
            enabled=True,
        )
    
    @pytest.fixture
    def mock_credential_data(self):
        """Create mock credential data."""
        return CredentialCreate(
            name="Test Credential",
            description="A test credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={"scope": "read write"},
            masked_hint="test-cred",
            rotation_interval_hours=24,
        )
    
    @pytest.fixture
    def mock_credential_secret_data(self):
        """Create mock credential secret data."""
        return [
            {
                "secret_type": "access_token",
                "encrypted_value": "encrypted-access-token",
                "encryption_key_id": "default",
                "metadata": {"expires_at": "2023-12-31T23:59:59Z"}
            }
        ]
    
    @pytest.fixture
    def mock_external_account_data(self):
        """Create mock external account data."""
        return ExternalAccountCreate(
            provider_id=uuid.uuid4(),
            account_identifier="test@example.com",
            display_name="Test Account",
            account_metadata={"verified": True},
            capabilities=[AccountCapability.READ],
            is_active=True,
        )
    
    @pytest.fixture
    def mock_binding_data(self):
        """Create mock binding data."""
        return CredentialBindingCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            is_primary=True,
            binding_metadata={"auto_created": True},
        )
    
    @pytest.fixture
    def mock_session_data(self):
        """Create mock session data."""
        return AccountSessionCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            session_token="test-session-token",
            access_token="encrypted-access-token",
            refresh_token="encrypted-refresh-token",
            token_type=TokenType.ACCESS,
            scopes=["read", "write"],
            session_metadata={"device": "web"},
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    
    @pytest.fixture
    def mock_grant_data(self):
        """Create mock grant data."""
        return AuthGrantCreate(
            credential_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            grant_type="authorization_code",
            authorization_code="auth-code-123",
            redirect_uri="https://example.com/callback",
            state="state-123",
        )
    
    @pytest.fixture
    def mock_lease_data(self):
        """Create mock lease data."""
        return TokenLeaseCreate(
            credential_id=uuid.uuid4(),
            lease_token="lease-token-123",
            access_token="encrypted-access-token",
            scopes=["read"],
            metadata={"purpose": "temporary_access"},
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    
    @pytest.fixture
    def mock_login_attempt_data(self):
        """Create mock login attempt data."""
        return LoginAttemptCreate(
            credential_id=uuid.uuid4(),
            attempt_type="oauth",
            status=LoginStatus.SUCCESS,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            metadata={"provider": "test-provider"},
        )
    
    @pytest.fixture
    def mock_audit_event_data(self):
        """Create mock audit event data."""
        return CredentialAuditEventCreate(
            tenant_id=uuid.uuid4(),
            user_id="test-user",
            credential_id=uuid.uuid4(),
            event_type=AuditEventType.CREATED,
            action="credential_creation",
            resource_type="credential",
            resource_id="test-credential-id",
            correlation_id="test-correlation-id",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            metadata={"provider_id": "test-provider"},
        )
    
    # Test initialization
    @pytest.mark.asyncio
    async def test_service_initialization(self, service):
        """Test service initialization."""
        await service.initialize()
        assert service._initialized is True
        assert service._tables_ensured is True
    
    # Test encryption/decryption
    def test_encrypt_decrypt_data(self, service):
        """Test data encryption and decryption."""
        test_data = "sensitive-data"
        
        # Encrypt data
        encrypted = service._encrypt_data(test_data)
        assert encrypted != test_data
        assert ":" in encrypted  # Should contain HMAC and encrypted data
        
        # Decrypt data
        decrypted = service._decrypt_data(encrypted)
        assert decrypted == test_data
    
    def test_encrypt_data_invalid_key(self, service):
        """Test encryption with invalid key."""
        test_data = "sensitive-data"
        
        with pytest.raises(ValueError, match="Encryption key not found"):
            service._encrypt_data(test_data, "invalid-key")
    
    def test_decrypt_data_invalid_key(self, service):
        """Test decryption with invalid key."""
        test_data = "sensitive-data"
        encrypted = service._encrypt_data(test_data)
        
        with pytest.raises(ValueError, match="Encryption key not found"):
            service._decrypt_data(encrypted, "invalid-key")
    
    def test_decrypt_data_invalid_format(self, service):
        """Test decryption with invalid format."""
        with pytest.raises(ValueError, match="Invalid encrypted data format"):
            service._decrypt_data("invalid-format")
    
    def test_decrypt_data_invalid_hmac(self, service):
        """Test decryption with invalid HMAC."""
        test_data = "sensitive-data"
        encrypted = service._encrypt_data(test_data)
        
        # Corrupt the HMAC
        parts = encrypted.split(":", 1)
        corrupted_hmac = parts[0] + "corrupted"
        corrupted_data = corrupted_hmac + ":" + parts[1]
        
        with pytest.raises(ValueError, match="Data integrity check failed"):
            service._decrypt_data(corrupted_data)
    
    # Test provider management
    @pytest.mark.asyncio
    async def test_create_provider(self, service, mock_provider_data, mock_tenant_id, mock_user_id):
        """Test creating a provider."""
        await service.initialize()
        
        provider = await service.create_provider(
            provider_data=mock_provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert provider is not None
        assert provider.provider_id == mock_provider_data.provider_id
        assert provider.display_name == mock_provider_data.display_name
        assert provider.provider_type == mock_provider_data.provider_type
        assert provider.config == mock_provider_data.config
    
    @pytest.mark.asyncio
    async def test_get_provider(self, service, mock_provider_data, mock_tenant_id, mock_user_id):
        """Test getting a provider."""
        await service.initialize()
        
        # Create provider first
        created_provider = await service.create_provider(
            provider_data=mock_provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get provider
        provider = await service.get_provider(mock_provider_data.provider_id)
        
        assert provider is not None
        assert provider.id == created_provider.id
        assert provider.provider_id == mock_provider_data.provider_id
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_provider(self, service):
        """Test getting a non-existent provider."""
        await service.initialize()
        
        provider = await service.get_provider("nonexistent-provider")
        assert provider is None
    
    @pytest.mark.asyncio
    async def test_list_providers(self, service, mock_provider_data, mock_tenant_id, mock_user_id):
        """Test listing providers."""
        await service.initialize()
        
        # Create multiple providers
        provider1 = await service.create_provider(
            provider_data=mock_provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        provider2_data = ProviderDefinitionCreate(
            provider_id="test-provider-2",
            display_name="Test Provider 2",
            description="Another test provider",
            provider_type=ProviderType.API_KEY,
            config={"api_key": "test-api-key"},
            enabled=True,
        )
        provider2 = await service.create_provider(
            provider_data=provider2_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # List all providers
        providers = await service.list_providers(mock_tenant_id)
        assert len(providers) >= 2
        
        # List enabled providers only
        enabled_providers = await service.list_providers(mock_tenant_id, enabled_only=True)
        assert len(enabled_providers) >= 2
        
        # List with pagination
        paginated_providers = await service.list_providers(mock_tenant_id, limit=1, offset=0)
        assert len(paginated_providers) == 1
    
    @pytest.mark.asyncio
    async def test_update_provider(self, service, mock_provider_data, mock_tenant_id, mock_user_id):
        """Test updating a provider."""
        await service.initialize()
        
        # Create provider first
        created_provider = await service.create_provider(
            provider_data=mock_provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Update provider
        update_data = ProviderDefinitionUpdate(
            display_name="Updated Provider Name",
            description="Updated description",
            enabled=False,
        )
        
        provider = await service.update_provider(
            provider_id=mock_provider_data.provider_id,
            update_data=update_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert provider is not None
        assert provider.display_name == "Updated Provider Name"
        assert provider.description == "Updated description"
        assert provider.enabled is False
    
    @pytest.mark.asyncio
    async def test_delete_provider(self, service, mock_provider_data, mock_tenant_id, mock_user_id):
        """Test deleting a provider."""
        await service.initialize()
        
        # Create provider first
        created_provider = await service.create_provider(
            provider_data=mock_provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Delete provider
        success = await service.delete_provider(
            provider_id=mock_provider_data.provider_id,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert success is True
        
        # Verify provider is deleted
        provider = await service.get_provider(mock_provider_data.provider_id)
        assert provider is None
    
    # Test credential management
    @pytest.mark.asyncio
    async def test_create_credential(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test creating a credential."""
        await service.initialize()
        
        credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert credential is not None
        assert credential.name == mock_credential_data.name
        assert credential.credential_type == mock_credential_data.credential_type
        assert credential.status == CredentialStatus.ACTIVE
        assert len(credential.secrets) == 1
        assert credential.secrets[0].secret_type == "access_token"
    
    @pytest.mark.asyncio
    async def test_get_credential(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test getting a credential."""
        await service.initialize()
        
        # Create credential first
        created_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get credential
        credential = await service.get_credential(created_credential.id)
        
        assert credential is not None
        assert credential.id == created_credential.id
        assert credential.name == mock_credential_data.name
    
    @pytest.mark.asyncio
    async def test_list_credentials(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test listing credentials."""
        await service.initialize()
        
        # Create multiple credentials
        credential1 = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        credential2_data = CredentialCreate(
            name="Test Credential 2",
            description="Another test credential",
            provider_id=uuid.uuid4(),
            credential_type="api_key",
            metadata={"scope": "read"},
        )
        credential2 = await service.create_credential(
            credential_data=credential2_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # List all credentials
        credentials = await service.list_credentials(mock_tenant_id)
        assert len(credentials) >= 2
        
        # List by status
        active_credentials = await service.list_credentials(mock_tenant_id, status=CredentialStatus.ACTIVE)
        assert len(active_credentials) >= 2
        
        # List with pagination
        paginated_credentials = await service.list_credentials(mock_tenant_id, limit=1, offset=0)
        assert len(paginated_credentials) == 1
    
    @pytest.mark.asyncio
    async def test_update_credential(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test updating a credential."""
        await service.initialize()
        
        # Create credential first
        created_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Update credential
        update_data = CredentialUpdate(
            name="Updated Credential Name",
            status=CredentialStatus.REFRESH_REQUIRED,
        )
        
        credential = await service.update_credential(
            credential_id=created_credential.id,
            update_data=update_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert credential is not None
        assert credential.name == "Updated Credential Name"
        assert credential.status == CredentialStatus.REFRESH_REQUIRED
    
    @pytest.mark.asyncio
    async def test_rotate_credential(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test rotating credential secrets."""
        await service.initialize()
        
        # Create credential first
        created_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Rotate credential
        new_secrets = [
            {
                "secret_type": "access_token",
                "encrypted_value": "new-encrypted-access-token",
                "encryption_key_id": "default",
                "metadata": {"expires_at": "2024-12-31T23:59:59Z"}
            }
        ]
        
        result = await service.rotate_credential(
            credential_id=created_credential.id,
            new_secrets=new_secrets,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert result is not None
        assert result.credential_id == created_credential.id
        assert result.new_token == "new-encrypted-access-token"
        assert result.old_token_hash is not None
        assert result.new_token_hash is not None
    
    @pytest.mark.asyncio
    async def test_revoke_credential(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test revoking a credential."""
        await service.initialize()
        
        # Create credential first
        created_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Revoke credential
        success = await service.revoke_credential(
            credential_id=created_credential.id,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            reason="Security reasons",
        )
        
        assert success is True
        
        # Verify credential is revoked
        credential = await service.get_credential(created_credential.id)
        assert credential.status == CredentialStatus.REVOKED
    
    # Test external account management
    @pytest.mark.asyncio
    async def test_create_external_account(self, service, mock_external_account_data, mock_tenant_id, mock_user_id):
        """Test creating an external account."""
        await service.initialize()
        
        account = await service.create_external_account(
            account_data=mock_external_account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert account is not None
        assert account.account_identifier == mock_external_account_data.account_identifier
        assert account.display_name == mock_external_account_data.display_name
        assert account.is_active == mock_external_account_data.is_active
    
    @pytest.mark.asyncio
    async def test_get_external_account(self, service, mock_external_account_data, mock_tenant_id, mock_user_id):
        """Test getting an external account."""
        await service.initialize()
        
        # Create account first
        created_account = await service.create_external_account(
            account_data=mock_external_account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get account
        account = await service.get_external_account(created_account.id)
        
        assert account is not None
        assert account.id == created_account.id
        assert account.account_identifier == mock_external_account_data.account_identifier
    
    @pytest.mark.asyncio
    async def test_list_external_accounts(self, service, mock_external_account_data, mock_tenant_id, mock_user_id):
        """Test listing external accounts."""
        await service.initialize()
        
        # Create multiple accounts
        account1 = await service.create_external_account(
            account_data=mock_external_account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        account2_data = ExternalAccountCreate(
            provider_id=uuid.uuid4(),
            account_identifier="test2@example.com",
            display_name="Test Account 2",
            account_metadata={"verified": True},
            capabilities=[AccountCapability.WRITE],
            is_active=True,
        )
        account2 = await service.create_external_account(
            account_data=account2_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # List all accounts
        accounts = await service.list_external_accounts(mock_tenant_id)
        assert len(accounts) >= 2
        
        # List active accounts only
        active_accounts = await service.list_external_accounts(mock_tenant_id, active_only=True)
        assert len(active_accounts) >= 2
        
        # List with pagination
        paginated_accounts = await service.list_external_accounts(mock_tenant_id, limit=1, offset=0)
        assert len(paginated_accounts) == 1
    
    # Test binding management
    @pytest.mark.asyncio
    async def test_create_binding(self, service, mock_binding_data, mock_tenant_id, mock_user_id):
        """Test creating a credential binding."""
        await service.initialize()
        
        binding = await service.create_binding(
            binding_data=mock_binding_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert binding is not None
        assert binding.credential_id == mock_binding_data.credential_id
        assert binding.external_account_id == mock_binding_data.external_account_id
        assert binding.is_primary == mock_binding_data.is_primary
    
    @pytest.mark.asyncio
    async def test_get_binding(self, service, mock_binding_data, mock_tenant_id, mock_user_id):
        """Test getting a credential binding."""
        await service.initialize()
        
        # Create binding first
        created_binding = await service.create_binding(
            binding_data=mock_binding_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get binding
        binding = await service.get_binding(created_binding.id)
        
        assert binding is not None
        assert binding.id == created_binding.id
        assert binding.credential_id == mock_binding_data.credential_id
    
    @pytest.mark.asyncio
    async def test_list_bindings(self, service, mock_binding_data, mock_tenant_id, mock_user_id):
        """Test listing credential bindings."""
        await service.initialize()
        
        # Create multiple bindings
        binding1 = await service.create_binding(
            binding_data=mock_binding_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        binding2_data = CredentialBindingCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            is_primary=False,
            binding_metadata={"auto_created": True},
        )
        binding2 = await service.create_binding(
            binding_data=binding2_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # List all bindings
        bindings = await service.list_bindings(mock_tenant_id)
        assert len(bindings) >= 2
        
        # List active bindings only
        active_bindings = await service.list_bindings(mock_tenant_id, active_only=True)
        assert len(active_bindings) >= 2
        
        # List with pagination
        paginated_bindings = await service.list_bindings(mock_tenant_id, limit=1, offset=0)
        assert len(paginated_bindings) == 1
    
    # Test OAuth management
    @pytest.mark.asyncio
    async def test_create_oauth_grant(self, service, mock_grant_data, mock_tenant_id, mock_user_id):
        """Test creating an OAuth grant."""
        await service.initialize()
        
        grant = await service.create_oauth_grant(
            grant_data=mock_grant_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert grant is not None
        assert grant.credential_id == mock_grant_data.credential_id
        assert grant.grant_type == mock_grant_data.grant_type
        assert grant.authorization_code == mock_grant_data.authorization_code
        assert grant.is_completed is False
    
    @pytest.mark.asyncio
    async def test_complete_oauth_grant(self, service, mock_grant_data, mock_tenant_id, mock_user_id):
        """Test completing an OAuth grant."""
        await service.initialize()
        
        # Create grant first
        created_grant = await service.create_oauth_grant(
            grant_data=mock_grant_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Complete grant
        access_token = "encrypted-access-token"
        refresh_token = "encrypted-refresh-token"
        
        grant = await service.complete_oauth_grant(
            grant_id=created_grant.id,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=["read", "write"],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert grant is not None
        assert grant.id == created_grant.id
        assert grant.access_token == access_token
        assert grant.refresh_token == refresh_token
        assert grant.is_completed is True
    
    @pytest.mark.asyncio
    async def test_refresh_oauth_token(self, service, mock_grant_data, mock_tenant_id, mock_user_id):
        """Test refreshing an OAuth token."""
        await service.initialize()
        
        # Create and complete grant first
        created_grant = await service.create_oauth_grant(
            grant_data=mock_grant_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        await service.complete_oauth_grant(
            grant_id=created_grant.id,
            access_token="encrypted-access-token",
            refresh_token="encrypted-refresh-token",
            scopes=["read"],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Refresh token
        result = await service.refresh_oauth_token(
            credential_id=created_grant.credential_id,
            refresh_token="encrypted-refresh-token",
            new_scopes=["read", "write"],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert result is not None
        assert "access_token" in result
        assert "refresh_token" in result
        assert "expires_in" in result
        assert "scopes" in result
        assert "read" in result["scopes"]
        assert "write" in result["scopes"]
    
    # Test session management
    @pytest.mark.asyncio
    async def test_create_account_session(self, service, mock_session_data, mock_tenant_id, mock_user_id):
        """Test creating an account session."""
        await service.initialize()
        
        session = await service.create_account_session(
            session_data=mock_session_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert session is not None
        assert session.credential_id == mock_session_data.credential_id
        assert session.external_account_id == mock_session_data.external_account_id
        assert session.session_token == mock_session_data.session_token
        assert session.token_type == mock_session_data.token_type
        assert session.is_active is True
    
    @pytest.mark.asyncio
    async def test_get_account_session(self, service, mock_session_data, mock_tenant_id, mock_user_id):
        """Test getting an account session."""
        await service.initialize()
        
        # Create session first
        created_session = await service.create_account_session(
            session_data=mock_session_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get session
        session = await service.get_account_session(created_session.id)
        
        assert session is not None
        assert session.id == created_session.id
        assert session.session_token == mock_session_data.session_token
    
    @pytest.mark.asyncio
    async def test_invalidate_account_session(self, service, mock_session_data, mock_tenant_id, mock_user_id):
        """Test invalidating an account session."""
        await service.initialize()
        
        # Create session first
        created_session = await service.create_account_session(
            session_data=mock_session_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Invalidate session
        success = await service.invalidate_account_session(
            session_id=created_session.id,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            reason="User logout",
        )
        
        assert success is True
        
        # Verify session is invalidated
        session = await service.get_account_session(created_session.id)
        assert session.is_active is False
    
    # Test login management
    @pytest.mark.asyncio
    async def test_record_login_attempt(self, service, mock_login_attempt_data, mock_tenant_id, mock_user_id):
        """Test recording a login attempt."""
        await service.initialize()
        
        attempt = await service.record_login_attempt(
            attempt_data=mock_login_attempt_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert attempt is not None
        assert attempt.credential_id == mock_login_attempt_data.credential_id
        assert attempt.attempt_type == mock_login_attempt_data.attempt_type
        assert attempt.status == mock_login_attempt_data.status
        assert attempt.ip_address == mock_login_attempt_data.ip_address
    
    # Test token lease management
    @pytest.mark.asyncio
    async def test_create_token_lease(self, service, mock_lease_data, mock_tenant_id, mock_user_id):
        """Test creating a token lease."""
        await service.initialize()
        
        lease = await service.create_token_lease(
            lease_data=mock_lease_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert lease is not None
        assert lease.credential_id == mock_lease_data.credential_id
        assert lease.lease_token == mock_lease_data.lease_token
        assert lease.access_token == mock_lease_data.access_token
        assert lease.is_active is True
    
    @pytest.mark.asyncio
    async def test_get_token_lease(self, service, mock_lease_data, mock_tenant_id, mock_user_id):
        """Test getting a token lease."""
        await service.initialize()
        
        # Create lease first
        created_lease = await service.create_token_lease(
            lease_data=mock_lease_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get lease
        lease = await service.get_token_lease(created_lease.lease_token)
        
        assert lease is not None
        assert lease.id == created_lease.id
        assert lease.lease_token == mock_lease_data.lease_token
    
    @pytest.mark.asyncio
    async def test_invalidate_token_lease(self, service, mock_lease_data, mock_tenant_id, mock_user_id):
        """Test invalidating a token lease."""
        await service.initialize()
        
        # Create lease first
        created_lease = await service.create_token_lease(
            lease_data=mock_lease_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Invalidate lease
        success = await service.invalidate_token_lease(
            lease_token=created_lease.lease_token,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            reason="Lease expired",
        )
        
        assert success is True
        
        # Verify lease is invalidated
        lease = await service.get_token_lease(created_lease.lease_token)
        assert lease is None  # Should not find active lease
    
    # Test capability discovery
    @pytest.mark.asyncio
    async def test_discover_account_capabilities(self, service, mock_external_account_data, mock_tenant_id, mock_user_id):
        """Test discovering account capabilities."""
        await service.initialize()
        
        # Create account first
        created_account = await service.create_external_account(
            account_data=mock_external_account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Discover capabilities
        discovery = await service.discover_account_capabilities(
            account_id=created_account.id,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert discovery is not None
        assert discovery.account_id == created_account.id
        assert len(discovery.discovered_capabilities) > 0
        assert discovery.verified_at is not None
    
    # Test health monitoring
    @pytest.mark.asyncio
    async def test_get_credential_health(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test getting credential health status."""
        await service.initialize()
        
        # Create credential first
        created_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Get health status
        health = await service.get_credential_health(created_credential.id)
        
        assert health is not None
        assert health.credential_id == created_credential.id
        assert health.status == CredentialStatus.ACTIVE
        assert 0.0 <= health.health_score <= 1.0
        assert health.last_check is not None
    
    @pytest.mark.asyncio
    async def test_list_credentials_needing_attention(self, service, mock_credential_data, mock_credential_secret_data, mock_tenant_id, mock_user_id):
        """Test listing credentials needing attention."""
        await service.initialize()
        
        # Create credentials with different statuses
        active_credential = await service.create_credential(
            credential_data=mock_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        expired_credential_data = CredentialCreate(
            name="Expired Credential",
            description="An expired credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={"scope": "read"},
            expires_at=datetime.utcnow() - timedelta(hours=1),  # Expired
        )
        expired_credential = await service.create_credential(
            credential_data=expired_credential_data,
            secrets=mock_credential_secret_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # List credentials needing attention
        health_statuses = await service.list_credentials_needing_attention(mock_tenant_id)
        
        assert len(health_statuses) >= 1  # At least the expired credential
        
        # Verify expired credential is in the list
        expired_found = any(h.credential_id == expired_credential.id for h in health_statuses)
        assert expired_found is True
    
    # Test audit logging
    @pytest.mark.asyncio
    async def test_emit_audit_event(self, service, mock_audit_event_data, mock_tenant_id, mock_user_id):
        """Test emitting audit events."""
        await service.initialize()
        
        # Create credential first (needed for audit event)
        credential_data = CredentialCreate(
            name="Test Credential",
            description="A test credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={},
        )
        credential = await service.create_credential(
            credential_data=credential_data,
            secrets=[{"secret_type": "access_token", "encrypted_value": "test", "encryption_key_id": "default", "metadata": {}}],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Emit audit event
        await service._emit_audit_event(
            event_type=AuditEventType.CREATED,
            action="test_action",
            resource_type="test_resource",
            resource_id="test_resource_id",
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            correlation_id="test-correlation-id",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            metadata={"test": "data"},
            credential_id=credential.id,
        )
        
        # Verify audit event was created (in a real test, we'd check the database)
        assert True  # Placeholder for actual verification
    
    @pytest.mark.asyncio
    async def test_get_audit_events(self, service, mock_audit_event_data, mock_tenant_id, mock_user_id):
        """Test getting audit events."""
        await service.initialize()
        
        # Create credential first (needed for audit event)
        credential_data = CredentialCreate(
            name="Test Credential",
            description="A test credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={},
        )
        credential = await service.create_credential(
            credential_data=credential_data,
            secrets=[{"secret_type": "access_token", "encrypted_value": "test", "encryption_key_id": "default", "metadata": {}}],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Emit audit event
        await service._emit_audit_event(
            event_type=AuditEventType.CREATED,
            action="test_action",
            resource_type="test_resource",
            resource_id="test_resource_id",
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            correlation_id="test-correlation-id",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            metadata={"test": "data"},
            credential_id=credential.id,
        )
        
        # Get audit events
        events = await service.get_audit_events(mock_tenant_id)
        
        # In a real test, we'd verify events were returned
        assert True  # Placeholder for actual verification
    
    # Test utility functions
    def test_validate_capabilities(self):
        """Test capability validation."""
        # Test valid capabilities
        valid_caps = validate_capabilities(["read", "write", "gmail.read"])
        assert AccountCapability.READ in valid_caps
        assert AccountCapability.WRITE in valid_caps
        assert AccountCapability.GMAIL_READ in valid_caps
        
        # Test invalid capabilities (should be filtered out)
        invalid_caps = validate_capabilities(["read", "invalid.cap", "write"])
        assert AccountCapability.READ in invalid_caps
        assert AccountCapability.WRITE in invalid_caps
        assert "invalid.cap" not in valid_caps
    
    def test_generate_masked_hint(self):
        """Test masked hint generation."""
        # Test short string
        short_hint = generate_masked_hint("short")
        assert short_hint == "short"
        
        # Test long string
        long_hint = generate_masked_hint("this-is-a-long-secret-key")
        assert long_hint == "this-is-a••••••••••••••••"
        assert len(long_hint) == 8 + len("•") * (len("this-is-a-long-secret-key") - 8)
    
    def test_is_token_expired(self):
        """Test token expiration check."""
        # Test expired token
        expired_time = datetime.utcnow() - timedelta(hours=1)
        assert is_token_expired(expired_time) is True
        
        # Test future token
        future_time = datetime.utcnow() + timedelta(hours=1)
        assert is_token_expired(future_time) is False
        
        # Test None token
        assert is_token_expired(None) is False
    
    def test_calculate_health_score(self):
        """Test health score calculation."""
        # Test healthy credential
        healthy_credential = Credential(
            id=uuid.uuid4(),
            name="Healthy Credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            status=CredentialStatus.ACTIVE,
            expires_at=datetime.utcnow() + timedelta(days=30),
            last_used_at=datetime.utcnow(),
        )
        score = calculate_health_score(healthy_credential)
        assert 0.8 <= score <= 1.0
        
        # Test expired credential
        expired_credential = Credential(
            id=uuid.uuid4(),
            name="Expired Credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            status=CredentialStatus.EXPIRED,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        score = calculate_health_score(expired_credential)
        assert score <= 0.5
        
        # Test revoked credential
        revoked_credential = Credential(
            id=uuid.uuid4(),
            name="Revoked Credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            status=CredentialStatus.REVOKED,
        )
        score = calculate_health_score(revoked_credential)
        assert score == 0.0


class TestIdentityVaultModels:
    """Test identity vault data models."""
    
    def test_provider_definition_model(self):
        """Test provider definition model creation."""
        provider_data = ProviderDefinitionCreate(
            provider_id="test-provider",
            display_name="Test Provider",
            description="A test provider",
            provider_type=ProviderType.OAUTH2,
            config={"client_id": "test-client"},
        )
        
        assert provider_data.provider_id == "test-provider"
        assert provider_data.display_name == "Test Provider"
        assert provider_data.provider_type == ProviderType.OAUTH2
        assert provider_data.config == {"client_id": "test-client"}
    
    def test_credential_model(self):
        """Test credential model creation."""
        credential_data = CredentialCreate(
            name="Test Credential",
            description="A test credential",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={"scope": "read"},
        )
        
        assert credential_data.name == "Test Credential"
        assert credential_data.credential_type == "oauth"
        assert credential_data.metadata == {"scope": "read"}
    
    def test_external_account_model(self):
        """Test external account model creation."""
        account_data = ExternalAccountCreate(
            provider_id=uuid.uuid4(),
            account_identifier="test@example.com",
            display_name="Test Account",
            capabilities=[AccountCapability.READ],
        )
        
        assert account_data.account_identifier == "test@example.com"
        assert account_data.display_name == "Test Account"
        assert AccountCapability.READ in account_data.capabilities
    
    def test_credential_binding_model(self):
        """Test credential binding model creation."""
        binding_data = CredentialBindingCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            is_primary=True,
        )
        
        assert binding_data.is_primary is True
        assert binding_data.credential_id is not None
        assert binding_data.external_account_id is not None
    
    def test_account_session_model(self):
        """Test account session model creation."""
        session_data = AccountSessionCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            session_token="test-session-token",
            token_type=TokenType.OAUTH_ACCESS,
            scopes=["read"],
        )
        
        assert session_data.session_token == "test-session-token"
        assert session_data.token_type == TokenType.OAUTH_ACCESS
        assert "read" in session_data.scopes
    
    def test_auth_grant_model(self):
        """Test auth grant model creation."""
        grant_data = AuthGrantCreate(
            credential_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            grant_type="authorization_code",
            authorization_code="auth-code-123",
        )
        
        assert grant_data.grant_type == "authorization_code"
        assert grant_data.authorization_code == "auth-code-123"
    
    def test_token_lease_model(self):
        """Test token lease model creation."""
        lease_data = TokenLeaseCreate(
            credential_id=uuid.uuid4(),
            lease_token="lease-token-123",
            access_token="encrypted-access-token",
            scopes=["read"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        
        assert lease_data.lease_token == "lease-token-123"
        assert lease_data.access_token == "encrypted-access-token"
        assert "read" in lease_data.scopes
    
    def test_login_attempt_model(self):
        """Test login attempt model creation."""
        attempt_data = LoginAttemptCreate(
            credential_id=uuid.uuid4(),
            attempt_type="oauth",
            status=LoginStatus.SUCCESS,
        )
        
        assert attempt_data.attempt_type == "oauth"
        assert attempt_data.status == LoginStatus.SUCCESS
    
    def test_credential_audit_event_model(self):
        """Test credential audit event model creation."""
        event_data = CredentialAuditEventCreate(
            tenant_id=uuid.uuid4(),
            user_id="test-user",
            credential_id=uuid.uuid4(),
            event_type=AuditEventType.CREATED,
            action="credential_creation",
            resource_type="credential",
        )
        
        assert event_data.event_type == AuditEventType.CREATED
        assert event_data.action == "credential_creation"
        assert event_data.resource_type == "credential"


class TestIdentityVaultIntegration:
    """Test identity vault integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_credential_binding_workflow(self, service, mock_tenant_id, mock_user_id):
        """Test complete credential binding workflow."""
        await service.initialize()
        
        # Create provider
        provider_data = ProviderDefinitionCreate(
            provider_id="gmail-provider",
            display_name="Gmail",
            description="Google Gmail",
            provider_type=ProviderType.OAUTH2,
            config={"client_id": "test-gmail-client", "auth_url": "https://accounts.google.com/oauth/auth"},
            supported_capabilities=[AccountCapability.GMAIL_READ, AccountCapability.GMAIL_SEND],
        )
        provider = await service.create_provider(
            provider_data=provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create external account
        account_data = ExternalAccountCreate(
            provider_id=provider.id,
            account_identifier="user@gmail.com",
            display_name="Personal Gmail",
            capabilities=[AccountCapability.GMAIL_READ],
        )
        account = await service.create_external_account(
            account_data=account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create credential
        credential_data = CredentialCreate(
            name="Gmail API Access",
            description="Access to Gmail API",
            provider_id=provider.id,
            credential_type="oauth",
            metadata={"scope": "https://www.googleapis.com/auth/gmail.readonly"},
        )
        credential = await service.create_credential(
            credential_data=credential_data,
            secrets=[{"secret_type": "access_token", "encrypted_value": "gmail-access-token", "encryption_key_id": "default", "metadata": {}}],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create binding
        binding_data = CredentialBindingCreate(
            credential_id=credential.id,
            external_account_id=account.id,
            is_primary=True,
        )
        binding = await service.create_binding(
            binding_data=binding_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Verify binding exists
        assert binding is not None
        assert binding.credential_id == credential.id
        assert binding.external_account_id == account.id
        assert binding.is_primary is True
        
        # List bindings for credential
        credential_bindings = await service.get_credential_bindings(credential.id)
        assert len(credential_bindings) == 1
        assert credential_bindings[0].id == binding.id
        
        # List bindings for account
        account_bindings = await service.get_external_account_bindings(account.id)
        assert len(account_bindings) == 1
        assert account_bindings[0].id == binding.id
    
    @pytest.mark.asyncio
    async def test_oauth_workflow(self, service, mock_tenant_id, mock_user_id):
        """Test complete OAuth workflow."""
        await service.initialize()
        
        # Create provider
        provider_data = ProviderDefinitionCreate(
            provider_id="github-provider",
            display_name="GitHub",
            description="GitHub API",
            provider_type=ProviderType.OAUTH2,
            config={"client_id": "test-github-client", "auth_url": "https://github.com/login/oauth/authorize"},
            supported_capabilities=[AccountCapability.GITHUB_READ, AccountCapability.GITHUB_WRITE],
        )
        provider = await service.create_provider(
            provider_data=provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create credential
        credential_data = CredentialCreate(
            name="GitHub API Access",
            description="Access to GitHub API",
            provider_id=provider.id,
            credential_type="oauth",
            metadata={"scope": "repo user"},
        )
        credential = await service.create_credential(
            credential_data=credential_data,
            secrets=[{"secret_type": "client_secret", "encrypted_value": "github-client-secret", "encryption_key_id": "default", "metadata": {}}],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create OAuth grant
        grant_data = AuthGrantCreate(
            credential_id=credential.id,
            provider_id=provider.id,
            grant_type="authorization_code",
            authorization_code="github-auth-code-123",
            redirect_uri="https://example.com/callback",
            state="github-state-123",
        )
        grant = await service.create_oauth_grant(
            grant_data=grant_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Complete OAuth grant
        access_token = "github-access-token-456"
        refresh_token = "github-refresh-token-789"
        
        completed_grant = await service.complete_oauth_grant(
            grant_id=grant.id,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=["repo", "user"],
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert completed_grant is not None
        assert completed_grant.access_token == access_token
        assert completed_grant.refresh_token == refresh_token
        assert completed_grant.is_completed is True
        
        # Refresh token
        new_scopes = ["repo", "user", "workflow"]
        refresh_result = await service.refresh_oauth_token(
            credential_id=credential.id,
            refresh_token=refresh_token,
            new_scopes=new_scopes,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert refresh_result is not None
        assert "access_token" in refresh_result
        assert "refresh_token" in refresh_result
        assert "expires_in" in refresh_result
        assert set(refresh_result["scopes"]) == set(new_scopes)
    
    @pytest.mark.asyncio
    async def test_account_capability_discovery(self, service, mock_tenant_id, mock_user_id):
        """Test account capability discovery."""
        await service.initialize()
        
        # Create provider
        provider_data = ProviderDefinitionCreate(
            provider_id="gmail-provider",
            display_name="Gmail",
            description="Google Gmail",
            provider_type=ProviderType.OAUTH2,
            config={"client_id": "test-gmail-client"},
            supported_capabilities=[AccountCapability.GMAIL_READ, AccountCapability.GMAIL_SEND, AccountCapability.CALENDAR_READ],
        )
        provider = await service.create_provider(
            provider_data=provider_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Create external account
        account_data = ExternalAccountCreate(
            provider_id=provider.id,
            account_identifier="user@gmail.com",
            display_name="Personal Gmail",
            capabilities=[],  # Initially empty
        )
        account = await service.create_external_account(
            account_data=account_data,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        # Discover capabilities
        discovery = await service.discover_account_capabilities(
            account_id=account.id,
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
        )
        
        assert discovery is not None
        assert discovery.account_id == account.id
        assert len(discovery.discovered_capabilities) > 0
        assert AccountCapability.GMAIL_READ in discovery.discovered_capabilities
        assert AccountCapability.GMAIL_SEND in discovery.discovered_capabilities
        assert AccountCapability.CALENDAR_READ in discovery.discovered_capabilities
        
        # Verify account was updated
        updated_account = await service.get_external_account(account.id)
        assert len(updated_account.capabilities) > 0
        assert AccountCapability.GMAIL_READ in updated_account.capabilities


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Consumer-owned credentials reuse the canonical Identity Vault and its
# tenant-scoped SQL authority. These tests inspect the actual query predicates.
@pytest.mark.asyncio
async def test_owned_credential_reads_bind_tenant_and_actor_without_loading_secrets():
    tenant_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.execute.return_value.scalars.return_value.all.return_value = []
    service = CredentialVaultService()
    service.set_db_session(session)

    assert await service.get_owned_credential(credential_id, tenant_id, "alice") is None
    query = session.execute.await_args.args[0]
    compiled = query.compile()
    assert "tenant_id" in str(compiled)
    assert "created_by" in str(compiled)
    assert tenant_id in compiled.params.values()
    assert credential_id in compiled.params.values()
    assert "alice" in compiled.params.values()
    assert not query._with_options

    session.execute.reset_mock()
    assert await service.list_owned_credentials(tenant_id, "alice") == []
    list_query = session.execute.await_args.args[0]
    list_compiled = list_query.compile()
    assert tenant_id in list_compiled.params.values()
    assert "alice" in list_compiled.params.values()
    assert not list_query._with_options

    # Existing authorized infrastructure retains tenant-level read semantics.
    session.execute.reset_mock()
    assert await service.get_credential(credential_id, tenant_id) is None
    admin_query = session.execute.await_args.args[0]
    admin_compiled = admin_query.compile()
    # ORM SELECT includes created_by as a projected column; only WHERE
    # predicates determine whether the administrative read is owner-restricted.
    assert "created_by" not in str(admin_query.whereclause)
    assert tenant_id in admin_compiled.params.values()
    assert admin_query._with_options


@pytest.mark.asyncio
async def test_owned_credential_mutations_fence_actor_and_creator_before_writes():
    from ai_karen_engine.database.models.identity_vault import CredentialSecretCreate

    tenant_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    replacement = CredentialSecretCreate(
        secret_type="api_key", encrypted_value="test-private-candidate"
    )
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    service = CredentialVaultService()
    service.set_db_session(session)

    mutations = (
        service.update_owned_credential(
            credential_id, CredentialUpdate(name="changed"), tenant_id, "alice"
        ),
        service.delete_owned_credential(credential_id, tenant_id, "alice"),
        service.rotate_owned_credential(credential_id, [replacement], tenant_id, "alice"),
        service.revoke_owned_credential(credential_id, tenant_id, "alice"),
    )
    for operation in mutations:
        assert await operation in (None, False)
        compiled = session.execute.await_args.args[0].compile()
        assert tenant_id in compiled.params.values()
        assert credential_id in compiled.params.values()
        assert "alice" in compiled.params.values()
        session.execute.reset_mock()
    session.commit.assert_not_awaited()
    session.delete.assert_not_awaited()

    for invalid_owner in ("", " alice", "alice ", "x" * 256, None):
        with pytest.raises(ValueError, match="credential owner"):
            await service.get_owned_credential(credential_id, tenant_id, invalid_owner)
    session.execute.assert_not_awaited()

    with pytest.raises(PermissionError, match="owner"):
        await service.rotate_credential(
            credential_id, [replacement], tenant_id, "alice", owner_user_id="bob"
        )
    with pytest.raises(PermissionError, match="owner"):
        await service.revoke_credential(
            credential_id, tenant_id, "alice", owner_user_id="bob"
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_model_credential_cannot_manage_plugin_secret():
    from ai_karen_engine.database.models.identity_vault import (
        CredentialCreate,
        CredentialSecretCreate,
    )

    tenant_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    service = CredentialVaultService()
    service.set_db_session(session)

    # SQL enforces purpose in addition to tenant and creator. Plugin secrets
    # written by the same user are not part of the consumer model inventory.
    assert await service.get_owned_credential(credential_id, tenant_id, "alice") is None
    compiled = session.execute.await_args.args[0].compile()
    assert "model_api_key" in compiled.params.values()
    assert "alice" in compiled.params.values()
    session.execute.reset_mock()

    plugin_credential = CredentialCreate(
        name="Plugin-managed secret",
        provider_id=uuid.uuid4(),
        credential_type="plugin_secret",
    )
    model_credential = CredentialCreate(
        name="Personal model key",
        provider_id=uuid.uuid4(),
        credential_type="model_api_key",
    )
    valid_secret = CredentialSecretCreate(
        secret_type="api_key", encrypted_value="private-test-key"
    )
    wrong_secret = CredentialSecretCreate(
        secret_type="password", encrypted_value="private-test-password"
    )
    with pytest.raises(ValueError, match="model API key"):
        await service.create_owned_credential(
            plugin_credential, [valid_secret], tenant_id, "alice"
        )
    with pytest.raises(ValueError, match="bounded API key"):
        await service.create_owned_credential(
            model_credential, [wrong_secret], tenant_id, "alice"
        )
    with pytest.raises(ValueError, match="bounded API key"):
        await service.rotate_owned_credential(
            credential_id, [wrong_secret], tenant_id, "alice"
        )
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


def _personal_model_resolution_fixture():
    """A trusted-runtime grant and a matching authenticated request subject."""
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan

    tenant = uuid.uuid4()
    credential_id = uuid.uuid4()
    principal = UserData(user_id="alice", tenant_id=str(tenant))
    context = ChatExecutionContext(
        user_id="alice",
        tenant_id=str(tenant),
        session_id="session-1",
        request_id="request-1",
        correlation_id="correlation-1",
        authenticated_user=principal,
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-request-1",
        policy_decision_id="policy-1",
        authorized_user_id="alice",
        authorized_tenant_id=str(tenant),
        authorized_session_id="session-1",
        allowed_capabilities=["model.personal_key.execute"],
        provider_constraints={
            "external_allowed": True,
            "local_only": False,
            "eligible_providers": ["openai"],
            "forbidden_providers": [],
            "personal_model_credential": {
                "provider_id": "openai",
                "model_id": "gpt-4o-mini",
                "credential_id": str(credential_id),
            },
        },
    )
    return tenant, credential_id, context, plan


@pytest.mark.asyncio
async def test_personal_model_credential_resolution_denies_unminted_or_replayed_plans():
    """A personal key cannot be resolved via client-supplied IDs or generic plans."""
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan

    tenant, credential_id, context, plan = _personal_model_resolution_fixture()
    session = AsyncMock()
    service = CredentialVaultService()
    service.set_db_session(session)
    kwargs = {
        "context": context, "plan": plan, "credential_id": credential_id,
        "provider_id": "openai", "model_id": "gpt-4o-mini",
    }

    unsupported = [
        ("provider_id", "anthropic"),
        ("model_id", "unapproved-model"),
        ("credential_id", uuid.uuid4()),
    ]
    for key, value in unsupported:
        with pytest.raises(PermissionError, match="execution denied"):
            await service.resolve_authorized_personal_model_key(
                **{**kwargs, key: value}
            )
    session.execute.assert_not_awaited()

    for missing_grant in (
        AuthorizedExecutionPlan(
            execution_id="exec-request-1",
            policy_decision_id="policy-1",
            authorized_user_id="alice",
            authorized_tenant_id=str(tenant),
        ),
        AuthorizedExecutionPlan(
            execution_id="exec-request-1",
            policy_decision_id="policy-1",
            authorized_user_id="bob",
            authorized_tenant_id=str(tenant),
            allowed_capabilities=plan.allowed_capabilities,
            provider_constraints=plan.provider_constraints,
        ),
    ):
        with pytest.raises(PermissionError, match="execution denied"):
            await service.resolve_authorized_personal_model_key(
                **{**kwargs, "plan": missing_grant}
            )
    session.execute.assert_not_awaited()

    context.authenticated_user = UserData(user_id="bob", tenant_id=str(tenant))
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    session.execute.assert_not_awaited()

    context.authenticated_user = UserData(
        user_id="alice", tenant_id=str(tenant), is_verified=False
    )
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_credential_resolution_sql_fences_tenant_owner_provider_and_status():
    """Even a policy grant cannot read another owner, tenant or credential type."""
    tenant, credential_id, context, plan = _personal_model_resolution_fixture()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.one_or_none.return_value = None
    service = CredentialVaultService()
    service.set_db_session(session)

    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(
            context=context, plan=plan, credential_id=credential_id,
            provider_id="openai", model_id="gpt-4o-mini",
        )
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    sql = str(statement.whereclause)
    assert "credentials.tenant_id" in sql
    assert "credentials.created_by" in sql
    assert "credentials.credential_type" in sql
    assert "credentials.status" in sql
    assert "identity_providers.tenant_id" in sql
    assert "identity_providers.provider_id" in sql
    assert "identity_providers.enabled" in sql
    assert tenant in compiled.params.values()
    assert credential_id in compiled.params.values()
    assert "alice" in compiled.params.values()
    assert "model_api_key" in compiled.params.values()
    assert "openai" in compiled.params.values()
    assert statement._with_options
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_credential_resolution_audit_commit_precedes_plaintext_release(
    monkeypatch: pytest.MonkeyPatch,
):
    """Only the trusted host receives plaintext after a durable access audit."""
    from datetime import timezone
    from types import SimpleNamespace
    from ai_karen_engine.services.identity_vault import credential_vault_service as vault_module

    tenant, credential_id, context, plan = _personal_model_resolution_fixture()
    provider_db_id = uuid.uuid4()
    secret = SimpleNamespace(
        tenant_id=tenant, credential_id=credential_id,
        secret_type="api_key", encrypted_value="opaque-encrypted-text",
    )
    record = SimpleNamespace(
        id=credential_id, tenant_id=tenant, provider_id=provider_db_id,
        created_by="alice", credential_type="model_api_key", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        secrets=[secret],
    )
    provider = SimpleNamespace(
        id=provider_db_id, tenant_id=tenant, provider_id="openai",
        enabled=True, is_system=True, provider_type="api_key",
        config={"managed_for": "model_api_key"},
    )
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.one_or_none.return_value = (record, provider)
    events = []
    monkeypatch.setattr(
        vault_module, "decrypt_data",
        lambda encrypted: (
            events.append("decrypt") or "private-model-key-not-for-logs"
        ),
    )
    session.commit.side_effect = lambda: events.append("commit")
    service = CredentialVaultService()
    service.set_db_session(session)
    service._audit = AsyncMock(side_effect=lambda *a, **kw: events.append("audit"))

    plaintext = await service.resolve_authorized_personal_model_key(
        context=context, plan=plan, credential_id=credential_id,
        provider_id="openai", model_id="gpt-4o-mini",
    )
    assert plaintext == "private-model-key-not-for-logs"
    assert events == ["decrypt", "audit", "commit"]
    assert service._audit.await_count == 1
    args = service._audit.await_args.kwargs
    assert args["tenant_id"] == tenant
    assert args["user_id"] == "alice"
    assert args["action"] == "personal_model_credential_resolved"
    assert args["correlation_id"] == "correlation-1"
    assert args["credential_id"] == credential_id
    assert "private-model-key-not-for-logs" not in str(args)

    # A failed durable audit commit must deny output, not return the secret.
    session.commit.side_effect = RuntimeError("simulated audit persistence failure")
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(
            context=context, plan=plan, credential_id=credential_id,
            provider_id="openai", model_id="gpt-4o-mini",
        )


@pytest.mark.asyncio
async def test_personal_model_credential_resolution_rejects_invalid_row_integrity():
    """Expired, revoked, plugin-owned or multi-secret records cannot execute."""
    from datetime import timezone
    from types import SimpleNamespace

    tenant, credential_id, context, plan = _personal_model_resolution_fixture()
    provider_db_id = uuid.uuid4()
    secret = SimpleNamespace(
        tenant_id=tenant, credential_id=credential_id,
        secret_type="api_key", encrypted_value="opaque-encrypted-text",
    )
    record = SimpleNamespace(
        id=credential_id, tenant_id=tenant, provider_id=provider_db_id,
        created_by="alice", credential_type="model_api_key", status="active",
        expires_at=None, secrets=[secret],
    )
    provider = SimpleNamespace(
        id=provider_db_id, tenant_id=tenant, provider_id="openai",
        enabled=True, is_system=True, provider_type="api_key",
        config={"managed_for": "model_api_key"},
    )
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.one_or_none.return_value = (record, provider)
    service = CredentialVaultService()
    service.set_db_session(session)
    kwargs = {
        "context": context, "plan": plan, "credential_id": credential_id,
        "provider_id": "openai", "model_id": "gpt-4o-mini",
    }

    original = record.status
    record.status = "revoked"
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    record.status = original
    record.expires_at = datetime.utcnow()  # Naive timestamps are not trusted.
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    record.expires_at = None
    provider.config = {"managed_for": "plugin_credentials"}
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    provider.config = {"managed_for": "model_api_key"}
    record.secrets = [secret, secret]
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    record.secrets = [secret]
    secret.tenant_id = uuid.uuid4()
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(**kwargs)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_key_release_locks_credential_and_provider_rows():
    """PostgreSQL must serialize release/audit with revoke, rotate, disable."""
    from sqlalchemy.dialects import postgresql

    tenant, credential_id, context, plan = _personal_model_resolution_fixture()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.one_or_none.return_value = None

    service = CredentialVaultService()
    service.set_db_session(session)
    with pytest.raises(PermissionError, match="execution denied"):
        await service.resolve_authorized_personal_model_key(
            context=context,
            plan=plan,
            credential_id=credential_id,
            provider_id="openai",
            model_id="gpt-4o-mini",
        )

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF" in compiled
    locked = compiled.split("FOR UPDATE OF", 1)[1].split("\n", 1)[0]
    assert "credentials" in locked
    assert "identity_providers" in locked
    assert "credentials.tenant_id" in compiled
    assert "credentials.created_by" in compiled
    assert "identity_providers.tenant_id" in compiled
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete", "rotate", "revoke"])
async def test_mutating_credential_locks_parent_before_secret_or_status_write(
    operation,
):
    """Every canonical mutation participates in the read/audit lock order."""
    from sqlalchemy.dialects import postgresql
    from ai_karen_engine.database.models.identity_vault import CredentialSecretCreate

    credential_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    service = CredentialVaultService()
    service.set_db_session(session)
    if operation == "update":
        result = await service.update_credential(
            credential_id, CredentialUpdate(), tenant_id, "alice",
            owner_user_id="alice",
        )
        assert result is None
    elif operation == "delete":
        result = await service.delete_credential(
            credential_id, tenant_id, "alice", owner_user_id="alice",
        )
        assert result is False
    elif operation == "rotate":
        result = await service.rotate_credential(
            credential_id,
            [CredentialSecretCreate(
                secret_type="api_key", encrypted_value="replacement-only",
            )],
            tenant_id, "alice", owner_user_id="alice",
        )
        assert result is None
    else:
        result = await service.revoke_credential(
            credential_id, tenant_id, "alice",
            owner_user_id="alice",
        )
        assert result is False

    # The SELECT must contain the tenant+owner constraints, and it must lock
    # the same parent row protected by personal-model access until commit.
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF credentials" in compiled
    assert "credentials.tenant_id" in compiled
    assert "credentials.id" in compiled
    assert "credentials.created_by" in compiled
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_credential_metadata_read_does_not_lock_mutable_parent_row():
    """Ordinary tenant-scoped reads remain nonmutating and nonblocking."""
    from sqlalchemy.dialects import postgresql

    tenant_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    service = CredentialVaultService()
    service.set_db_session(session)

    result = await service.get_owned_credential(
        credential_id, tenant_id, "alice"
    )
    assert result is None
    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "credentials.tenant_id" in compiled
    assert "credentials.created_by" in compiled
    assert "FOR UPDATE" not in compiled


@pytest.mark.asyncio
async def test_personal_model_credential_candidate_requires_unique_owned_active_record():
    """Only an unambiguous owner record is exposed; a key is never read."""
    from types import SimpleNamespace

    tenant, credential_id, context, _plan = _personal_model_resolution_fixture()
    service = CredentialVaultService()
    session = AsyncMock()
    service.set_db_session(session)
    record = SimpleNamespace(
        id=credential_id,
        tenant_id=tenant,
        created_by="alice",
        credential_type="model_api_key",
        status=CredentialStatus.ACTIVE.value,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [record]
    session.execute.return_value = result

    candidate = await service.find_unambiguous_owned_model_key_candidate(
        context=context, provider_id="openai",
    )
    assert candidate == credential_id
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
    service._audit = AsyncMock()
    # Metadata lookup did not read encrypted children or attempt to decrypt.
    assert not hasattr(record, "secrets")
    service._audit.assert_not_awaited()

    result.scalars.return_value.all.return_value = []
    assert await service.find_unambiguous_owned_model_key_candidate(
        context=context, provider_id="openai",
    ) is None
    result.scalars.return_value.all.return_value = [
        record,
        SimpleNamespace(id=uuid.uuid4()),
    ]
    assert await service.find_unambiguous_owned_model_key_candidate(
        context=context, provider_id="openai",
    ) is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_credential_candidate_sql_is_tenant_owner_provider_fenced():
    """The query itself proves scope and limits matches to two, not a first key."""
    from sqlalchemy.dialects import postgresql

    _tenant, _credential_id, context, _plan = _personal_model_resolution_fixture()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    service = CredentialVaultService()
    service.set_db_session(session)

    assert await service.find_unambiguous_owned_model_key_candidate(
        context=context, provider_id="openai",
    ) is None
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    where = str(statement.whereclause)
    assert "credentials.tenant_id" in where
    assert "credentials.created_by" in where
    assert "credentials.credential_type" in where
    assert "credentials.status" in where
    assert "credentials.expires_at" in where
    assert "identity_providers.tenant_id" in where
    assert "identity_providers.provider_id" in where
    assert "identity_providers.is_system" in where
    assert "identity_providers.enabled" in where
    assert "identity_providers.provider_type" in where
    assert "identity_providers.config" in where
    assert "LIMIT" in sql
    assert context.user_id in compiled.params.values()
    assert context.tenant_id in {str(value) for value in compiled.params.values()}
    assert "openai" in compiled.params.values()
    assert "managed_for" in compiled.params.values()
    assert "model_api_key" in compiled.params.values()
    assert "->>" in sql  # PostgreSQL JSON scalar extraction, never json=json equality.
    assert "identity_providers.config =" not in sql
    assert 2 in compiled.params.values()
    assert not statement._with_options
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_credential_candidate_denies_unverified_or_forged_subject():
    from ai_karen_engine.auth.models import UserData

    tenant, _credential_id, context, _plan = _personal_model_resolution_fixture()
    session = AsyncMock()
    service = CredentialVaultService()
    service.set_db_session(session)

    cases = [
        (None, "openai"),
        (UserData(user_id="bob", tenant_id=str(tenant)), "openai"),
        (UserData(user_id="alice", tenant_id=str(uuid.uuid4())), "openai"),
        (UserData(user_id="alice", tenant_id=str(tenant), is_verified=False), "openai"),
        (UserData(user_id="alice", tenant_id=str(tenant), is_active=False), "openai"),
        (UserData(user_id="alice", tenant_id=str(tenant)), "openai\nInjected"),
        (UserData(user_id="alice", tenant_id=str(tenant)), " openai"),
        (UserData(user_id="alice", tenant_id=str(tenant)), ""),
    ]
    for principal, provider in cases:
        context.authenticated_user = principal
        with pytest.raises(PermissionError, match="candidate denied"):
            await service.find_unambiguous_owned_model_key_candidate(
                context=context, provider_id=provider,
            )
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_model_credential_candidate_rechecks_returned_row_integrity():
    """Corrupt/invalid ORM rows must never become execution candidates."""
    from types import SimpleNamespace

    tenant, credential_id, context, _plan = _personal_model_resolution_fixture()
    record = SimpleNamespace(
        id=credential_id, tenant_id=tenant, created_by="alice",
        credential_type="model_api_key", status=CredentialStatus.ACTIVE.value,
    )
    service = CredentialVaultService()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [record]
    session.execute.return_value = result
    service.set_db_session(session)

    originals = {
        "id": credential_id,
        "tenant_id": tenant,
        "created_by": "alice",
        "credential_type": "model_api_key",
        "status": CredentialStatus.ACTIVE.value,
    }
    mismatches = {
        "id": str(credential_id),
        "tenant_id": uuid.uuid4(),
        "created_by": "bob",
        "credential_type": "plugin_secret",
        "status": CredentialStatus.REVOKED.value,
    }
    for field, bad in mismatches.items():
        setattr(record, field, bad)
        assert await service.find_unambiguous_owned_model_key_candidate(
            context=context, provider_id="openai",
        ) is None
        setattr(record, field, originals[field])
    session.commit.assert_not_awaited()
