"""
Test configuration and fixtures for the identity vault system.

This module provides shared test configuration and fixtures for all identity vault tests.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from ai_karen_engine.services.identity_vault.credential_vault_service import CredentialVaultService, IdentityVaultConfig
from ai_karen_engine.database.models.identity_vault import (
    CredentialStatus,
    TokenType,
    ProviderType,
    AccountCapability,
    AuditEventType,
    LoginStatus,
    ProviderDefinitionCreate,
    CredentialCreate,
    ExternalAccountCreate,
    CredentialBindingCreate,
    AccountSessionCreate,
    AuthGrantCreate,
    TokenLeaseCreate,
    LoginAttemptCreate,
    CredentialAuditEventCreate,
)


@pytest.fixture(scope="session")
def test_db_url():
    """Test database URL."""
    return "postgresql+asyncpg://test:test@localhost:5432/test_identity_vault"


@pytest.fixture(scope="session")
def test_encryption_secret():
    """Test encryption secret."""
    return "test-encryption-secret-key-32-characters-long"


@pytest.fixture
def test_config(test_encryption_secret):
    """Test configuration for identity vault service."""
    config = IdentityVaultConfig()
    config.encryption_secret_key = test_encryption_secret
    config.access_token_expire_hours = 1
    config.refresh_token_expire_days = 7
    config.session_token_expire_hours = 24
    config.oauth_code_expire_minutes = 10
    config.max_login_attempts = 5
    config.account_lockout_minutes = 30
    config.rate_limit_per_minute = 60
    config.audit_retention_days = 30
    config.health_check_interval_minutes = 5
    return config


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_tenant_id():
    """Mock tenant ID."""
    return uuid.uuid4()


@pytest.fixture
def mock_user_id():
    """Mock user ID."""
    return "test-user"


@pytest.fixture
def mock_correlation_id():
    """Mock correlation ID."""
    return "test-correlation-id"


@pytest.fixture
def mock_ip_address():
    """Mock IP address."""
    return "192.168.1.100"


@pytest.fixture
def mock_user_agent():
    """Mock user agent."""
    return "Mozilla/5.0 (Test Browser)"


@pytest.fixture
def test_providers():
    """Test provider definitions."""
    return [
        ProviderDefinitionCreate(
            provider_id="gmail-provider",
            display_name="Gmail",
            description="Google Gmail",
            provider_type=ProviderType.OAUTH2,
            config={
                "client_id": "test-gmail-client",
                "client_secret": "test-gmail-secret",
                "auth_url": "https://accounts.google.com/oauth/auth",
                "token_url": "https://oauth2.googleapis.com/token",
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            },
            supported_capabilities=[
                AccountCapability.GMAIL_READ,
                AccountCapability.GMAIL_SEND,
                AccountCapability.CALENDAR_READ,
                AccountCapability.CALENDAR_WRITE,
            ],
            enabled=True,
        ),
        ProviderDefinitionCreate(
            provider_id="github-provider",
            display_name="GitHub",
            description="GitHub API",
            provider_type=ProviderType.OAUTH2,
            config={
                "client_id": "test-github-client",
                "client_secret": "test-github-secret",
                "auth_url": "https://github.com/login/oauth/authorize",
                "token_url": "https://github.com/login/oauth/access_token",
                "scope": "repo user",
            },
            supported_capabilities=[
                AccountCapability.GITHUB_READ,
                AccountCapability.GITHUB_WRITE,
                AccountCapability.GITHUB_REPO,
                AccountCapability.GITHUB_USER,
            ],
            enabled=True,
        ),
        ProviderDefinitionCreate(
            provider_id="openai-provider",
            display_name="OpenAI",
            description="OpenAI API",
            provider_type=ProviderType.API_KEY,
            config={
                "api_url": "https://api.openai.com/v1",
                "api_version": "2023-12-01",
            },
            supported_capabilities=[
                AccountCapability.OPENAI_CHAT,
                AccountCapability.OPENAI_COMPLETIONS,
                AccountCapability.OPENAI_EMBEDDINGS,
            ],
            enabled=True,
        ),
    ]


@pytest.fixture
def test_credentials(test_providers):
    """Test credential data."""
    return [
        CredentialCreate(
            name="Gmail API Access",
            description="Access to Gmail API",
            provider_id=test_providers[0].id,
            credential_type="oauth",
            metadata={
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
                "email": "user@gmail.com",
            },
            masked_hint="gmail-acc",
            rotation_interval_hours=24,
        ),
        CredentialCreate(
            name="GitHub API Access",
            description="Access to GitHub API",
            provider_id=test_providers[1].id,
            credential_type="oauth",
            metadata={
                "scope": "repo user",
                "username": "testuser",
            },
            masked_hint="github-acc",
            rotation_interval_hours=12,
        ),
        CredentialCreate(
            name="OpenAI API Key",
            description="Access to OpenAI API",
            provider_id=test_providers[2].id,
            credential_type="api_key",
            metadata={
                "model": "gpt-3.5-turbo",
                "organization": "test-org",
            },
            masked_hint="openai-key",
            rotation_interval_hours=168,  # 1 week
        ),
    ]


@pytest.fixture
def test_credential_secrets():
    """Test credential secret data."""
    return [
        {
            "secret_type": "access_token",
            "encrypted_value": "encrypted-gmail-access-token",
            "encryption_key_id": "default",
            "metadata": {
                "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                "issued_at": datetime.utcnow().isoformat(),
            },
        },
        {
            "secret_type": "refresh_token",
            "encrypted_value": "encrypted-gmail-refresh-token",
            "encryption_key_id": "default",
            "metadata": {
                "expires_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
            },
        },
    ]


@pytest.fixture
def test_external_accounts(test_providers):
    """Test external account data."""
    return [
        ExternalAccountCreate(
            provider_id=test_providers[0].id,
            account_identifier="user@gmail.com",
            display_name="Personal Gmail",
            account_metadata={
                "verified": True,
                "primary": True,
                "created_at": datetime.utcnow().isoformat(),
            },
            capabilities=[AccountCapability.GMAIL_READ],
            is_active=True,
        ),
        ExternalAccountCreate(
            provider_id=test_providers[1].id,
            account_identifier="testuser",
            display_name="Test GitHub",
            account_metadata={
                "verified": True,
                "type": "personal",
                "created_at": datetime.utcnow().isoformat(),
            },
            capabilities=[AccountCapability.GITHUB_READ, AccountCapability.GITHUB_WRITE],
            is_active=True,
        ),
        ExternalAccountCreate(
            provider_id=test_providers[2].id,
            account_identifier="test-org",
            display_name="Test Organization",
            account_metadata={
                "type": "organization",
                "created_at": datetime.utcnow().isoformat(),
            },
            capabilities=[AccountCapability.OPENAI_CHAT],
            is_active=True,
        ),
    ]


@pytest.fixture
def test_bindings(test_credentials, test_external_accounts):
    """Test credential binding data."""
    return [
        CredentialBindingCreate(
            credential_id=test_credentials[0].id,
            external_account_id=test_external_accounts[0].id,
            is_primary=True,
            binding_metadata={
                "auto_created": True,
                "created_at": datetime.utcnow().isoformat(),
            },
        ),
        CredentialBindingCreate(
            credential_id=test_credentials[1].id,
            external_account_id=test_external_accounts[1].id,
            is_primary=True,
            binding_metadata={
                "auto_created": True,
                "created_at": datetime.utcnow().isoformat(),
            },
        ),
        CredentialBindingCreate(
            credential_id=test_credentials[2].id,
            external_account_id=test_external_accounts[2].id,
            is_primary=True,
            binding_metadata={
                "auto_created": True,
                "created_at": datetime.utcnow().isoformat(),
            },
        ),
    ]


@pytest.fixture
def test_sessions(test_credentials, test_external_accounts):
    """Test account session data."""
    return [
        AccountSessionCreate(
            credential_id=test_credentials[0].id,
            external_account_id=test_external_accounts[0].id,
            session_token="gmail-session-token-123",
            access_token="encrypted-gmail-access-token",
            refresh_token="encrypted-gmail-refresh-token",
            token_type=TokenType.ACCESS,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            session_metadata={
                "device": "web",
                "location": "US",
                "created_at": datetime.utcnow().isoformat(),
            },
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
        AccountSessionCreate(
            credential_id=test_credentials[1].id,
            external_account_id=test_external_accounts[1].id,
            session_token="github-session-token-456",
            access_token="encrypted-github-access-token",
            refresh_token="encrypted-github-refresh-token",
            token_type=TokenType.ACCESS,
            scopes=["repo", "user"],
            session_metadata={
                "device": "mobile",
                "location": "US",
                "created_at": datetime.utcnow().isoformat(),
            },
            ip_address="192.168.1.101",
            user_agent="Mozilla/5.0 (Test Browser)",
            expires_at=datetime.utcnow() + timedelta(hours=2),
        ),
    ]


@pytest.fixture
def test_grants(test_credentials, test_providers):
    """Test OAuth grant data."""
    return [
        AuthGrantCreate(
            credential_id=test_credentials[0].id,
            provider_id=test_providers[0].id,
            grant_type="authorization_code",
            authorization_code="gmail-auth-code-123",
            redirect_uri="https://example.com/callback",
            state="gmail-state-123",
            code_challenge="challenge-123",
            code_challenge_method="S256",
        ),
        AuthGrantCreate(
            credential_id=test_credentials[1].id,
            provider_id=test_providers[1].id,
            grant_type="authorization_code",
            authorization_code="github-auth-code-456",
            redirect_uri="https://example.com/callback",
            state="github-state-456",
            code_challenge="challenge-456",
            code_challenge_method="S256",
        ),
    ]


@pytest.fixture
def test_leases(test_credentials):
    """Test token lease data."""
    return [
        TokenLeaseCreate(
            credential_id=test_credentials[0].id,
            lease_token="gmail-lease-token-123",
            access_token="encrypted-gmail-access-token",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            metadata={
                "purpose": "temporary_access",
                "created_at": datetime.utcnow().isoformat(),
            },
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
        TokenLeaseCreate(
            credential_id=test_credentials[1].id,
            lease_token="github-lease-token-456",
            access_token="encrypted-github-access-token",
            scopes=["repo", "user"],
            metadata={
                "purpose": "temporary_access",
                "created_at": datetime.utcnow().isoformat(),
            },
            expires_at=datetime.utcnow() + timedelta(hours=2),
        ),
    ]


@pytest.fixture
def test_login_attempts(test_credentials):
    """Test login attempt data."""
    return [
        LoginAttemptCreate(
            credential_id=test_credentials[0].id,
            attempt_type="oauth",
            status=LoginStatus.SUCCESS,
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={
                "provider": "gmail",
                "device": "web",
                "location": "US",
            },
        ),
        LoginAttemptCreate(
            credential_id=test_credentials[1].id,
            attempt_type="oauth",
            status=LoginStatus.FAILED,
            error_code="invalid_grant",
            error_message="Token has been expired or revoked",
            ip_address="192.168.1.101",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={
                "provider": "github",
                "device": "mobile",
                "location": "US",
            },
        ),
    ]


@pytest.fixture
def test_audit_events(test_credentials, test_external_accounts, mock_tenant_id, mock_user_id):
    """Test audit event data."""
    return [
        CredentialAuditEventCreate(
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            credential_id=test_credentials[0].id,
            event_type=AuditEventType.CREATED,
            action="credential_creation",
            resource_type="credential",
            resource_id="test-credential-id-1",
            correlation_id="test-correlation-1",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={
                "provider_id": "gmail-provider",
                "credential_type": "oauth",
            },
        ),
        CredentialAuditEventCreate(
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            credential_id=test_credentials[1].id,
            account_id=test_external_accounts[1].id,
            event_type=AuditEventType.BINDING_CREATED,
            action="binding_creation",
            resource_type="binding",
            resource_id="test-binding-id-1",
            correlation_id="test-correlation-2",
            ip_address="192.168.1.101",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={
                "provider_id": "github-provider",
                "is_primary": True,
            },
        ),
        CredentialAuditEventCreate(
            tenant_id=mock_tenant_id,
            user_id=mock_user_id,
            credential_id=test_credentials[2].id,
            event_type=AuditEventType.ROTATED,
            action="credential_rotation",
            resource_type="credential",
            resource_id="test-credential-id-2",
            correlation_id="test-correlation-3",
            ip_address="192.168.1.102",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={
                "provider_id": "openai-provider",
                "rotation_count": 1,
            },
        ),
    ]


@pytest.fixture
def mock_database_responses():
    """Mock database responses for testing."""
    return {
        "provider_by_id": {
            "gmail-provider": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "github-provider": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "openai-provider": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "credential_by_id": {
            "credential-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "credential-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "credential-3": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "account_by_id": {
            "account-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "account-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "account-3": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "binding_by_id": {
            "binding-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "binding-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "binding-3": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "session_by_id": {
            "session-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "session-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "grant_by_id": {
            "grant-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "grant-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "lease_by_token": {
            "lease-token-1": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            "lease-token-2": AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        },
        "list_providers": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_credentials": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_accounts": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_bindings": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_sessions": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_grants": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_leases": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
        "list_audit_events": AsyncMock(return_value=[
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
            MagicMock(id=uuid.uuid4()),
        ]),
    }


@pytest.fixture
def service_with_mock_db(test_config, mock_database_responses):
    """Create service with mocked database."""
    service = CredentialVaultService(config=test_config)
    
    # Mock database operations
    service._session_scope = AsyncMock(return_value=mock_database_responses)
    
    return service


# Test constants
TEST_TIMEOUT = 30  # seconds
TEST_MAX_RETRIES = 3
TEST_RETRY_DELAY = 1  # second


# Test markers
pytestmark = pytest.mark.asyncio


# Custom assertions
def assert_credential_valid(credential):
    """Assert that a credential is valid."""
    assert credential is not None
    assert credential.id is not None
    assert credential.name is not None
    assert credential.provider_id is not None
    assert credential.credential_type is not None
    assert credential.status is not None
    assert credential.created_at is not None
    assert credential.updated_at is not None


def assert_account_valid(account):
    """Assert that an external account is valid."""
    assert account is not None
    assert account.id is not None
    assert account.provider_id is not None
    assert account.account_identifier is not None
    assert account.is_active is not None
    assert account.created_at is not None
    assert account.updated_at is not None


def assert_binding_valid(binding):
    """Assert that a credential binding is valid."""
    assert binding is not None
    assert binding.id is not None
    assert binding.credential_id is not None
    assert binding.external_account_id is not None
    assert binding.is_active is not None
    assert binding.created_at is not None
    assert binding.updated_at is not None


def assert_session_valid(session):
    """Assert that an account session is valid."""
    assert session is not None
    assert session.id is not None
    assert session.credential_id is not None
    assert session.external_account_id is not None
    assert session.session_token is not None
    assert session.token_type is not None
    assert session.is_active is not None
    assert session.created_at is not None
    assert session.updated_at is not None


def assert_grant_valid(grant):
    """Assert that an OAuth grant is valid."""
    assert grant is not None
    assert grant.id is not None
    assert grant.credential_id is not None
    assert grant.provider_id is not None
    assert grant.grant_type is not None
    assert grant.authorization_code is not None
    assert grant.redirect_uri is not None
    assert grant.state is not None
    assert grant.created_at is not None
    assert grant.updated_at is not None


def assert_lease_valid(lease):
    """Assert that a token lease is valid."""
    assert lease is not None
    assert lease.id is not None
    assert lease.credential_id is not None
    assert lease.lease_token is not None
    assert lease.expires_at is not None
    assert lease.is_active is not None
    assert lease.created_at is not None
    assert lease.updated_at is not None


def assert_login_attempt_valid(attempt):
    """Assert that a login attempt is valid."""
    assert attempt is not None
    assert attempt.id is not None
    assert attempt.credential_id is not None
    assert attempt.attempt_type is not None
    assert attempt.status is not None
    assert attempt.timestamp is not None


def assert_audit_event_valid(event):
    """Assert that an audit event is valid."""
    assert event is not None
    assert event.id is not None
    assert event.tenant_id is not None
    assert event.user_id is not None
    assert event.event_type is not None
    assert event.action is not None
    assert event.resource_type is not None
    assert event.timestamp is not None


# Test utilities
async def wait_for_condition(condition, timeout=TEST_TIMEOUT, interval=1):
    """Wait for a condition to be true."""
    import asyncio
    
    start_time = asyncio.get_event_loop().time()
    while True:
        if condition():
            return True
        
        if asyncio.get_event_loop().time() - start_time > timeout:
            raise TimeoutError(f"Condition not met within {timeout} seconds")
        
        await asyncio.sleep(interval)


def create_test_event_data(event_type, action, resource_type, resource_id, metadata=None):
    """Create test event data."""
    return {
        "event_type": event_type,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "metadata": metadata or {},
        "timestamp": datetime.utcnow().isoformat(),
    }


def create_test_error_response(error_code, error_message, details=None):
    """Create test error response."""
    return {
        "error": {
            "code": error_code,
            "message": error_message,
            "details": details or {},
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# Test fixtures for common scenarios
@pytest.fixture
def test_oauth_flow_scenario():
    """Test OAuth flow scenario data."""
    return {
        "provider": {
            "id": "oauth-provider",
            "name": "Test OAuth Provider",
            "type": ProviderType.OAUTH2,
            "config": {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "auth_url": "https://auth.example.com",
                "token_url": "https://token.example.com",
                "scope": "read write",
            },
        },
        "credential": {
            "name": "Test OAuth Credential",
            "type": "oauth",
            "scopes": ["read", "write"],
        },
        "authorization_code": "auth-code-123",
        "state": "state-123",
        "redirect_uri": "https://app.example.com/callback",
        "access_token": "access-token-456",
        "refresh_token": "refresh-token-789",
        "expires_in": 3600,
    }


@pytest.fixture
def test_api_key_scenario():
    """Test API key scenario data."""
    return {
        "provider": {
            "id": "api-key-provider",
            "name": "Test API Key Provider",
            "type": ProviderType.API_KEY,
            "config": {
                "api_url": "https://api.example.com",
                "api_version": "v1",
            },
        },
        "credential": {
            "name": "Test API Key Credential",
            "type": "api_key",
        },
        "api_key": "sk-test-api-key-123",
    }


@pytest.fixture
def test_basic_auth_scenario():
    """Test basic auth scenario data."""
    return {
        "provider": {
            "id": "basic-auth-provider",
            "name": "Test Basic Auth Provider",
            "type": ProviderType.BASIC_AUTH,
            "config": {
                "api_url": "https://api.example.com",
            },
        },
        "credential": {
            "name": "Test Basic Auth Credential",
            "type": "basic_auth",
        },
        "username": "test-user",
        "password": "test-password",
    }


# Test data generators
def generate_test_credentials(count=3):
    """Generate test credentials."""
    credentials = []
    for i in range(count):
        credentials.append(CredentialCreate(
            name=f"Test Credential {i+1}",
            description=f"Test credential {i+1}",
            provider_id=uuid.uuid4(),
            credential_type="oauth",
            metadata={"scope": "read write"},
            masked_hint=f"cred-{i+1}",
        ))
    return credentials


def generate_test_accounts(count=3):
    """Generate test external accounts."""
    accounts = []
    for i in range(count):
        accounts.append(ExternalAccountCreate(
            provider_id=uuid.uuid4(),
            account_identifier=f"test{i+1}@example.com",
            display_name=f"Test Account {i+1}",
            account_metadata={"verified": True},
            capabilities=[AccountCapability.READ],
            is_active=True,
        ))
    return accounts


def generate_test_bindings(count=3):
    """Generate test credential bindings."""
    bindings = []
    for i in range(count):
        bindings.append(CredentialBindingCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            is_primary=(i == 0),  # Only first binding is primary
            binding_metadata={"auto_created": True},
        ))
    return bindings


def generate_test_sessions(count=3):
    """Generate test account sessions."""
    sessions = []
    for i in range(count):
        sessions.append(AccountSessionCreate(
            credential_id=uuid.uuid4(),
            external_account_id=uuid.uuid4(),
            session_token=f"session-token-{i+1}",
            access_token=f"encrypted-access-token-{i+1}",
            refresh_token=f"encrypted-refresh-token-{i+1}",
            token_type=TokenType.ACCESS,
            scopes=["read", "write"],
            session_metadata={"device": "web"},
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
    return sessions


def generate_test_grants(count=3):
    """Generate test OAuth grants."""
    grants = []
    for i in range(count):
        grants.append(AuthGrantCreate(
            credential_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            grant_type="authorization_code",
            authorization_code=f"auth-code-{i+1}",
            redirect_uri="https://example.com/callback",
            state=f"state-{i+1}",
        ))
    return grants


def generate_test_leases(count=3):
    """Generate test token leases."""
    leases = []
    for i in range(count):
        leases.append(TokenLeaseCreate(
            credential_id=uuid.uuid4(),
            lease_token=f"lease-token-{i+1}",
            access_token=f"encrypted-access-token-{i+1}",
            scopes=["read"],
            metadata={"purpose": "temporary_access"},
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
    return leases


def generate_test_login_attempts(count=3):
    """Generate test login attempts."""
    attempts = []
    for i in range(count):
        attempts.append(LoginAttemptCreate(
            credential_id=uuid.uuid4(),
            attempt_type="oauth",
            status=LoginStatus.SUCCESS if i % 2 == 0 else LoginStatus.FAILED,
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={"provider": "test-provider"},
        ))
    return attempts


def generate_test_audit_events(count=3):
    """Generate test audit events."""
    events = []
    for i in range(count):
        events.append(CredentialAuditEventCreate(
            tenant_id=uuid.uuid4(),
            user_id="test-user",
            credential_id=uuid.uuid4(),
            event_type=AuditEventType.CREATED if i % 2 == 0 else AuditEventType.UPDATED,
            action=f"test-action-{i+1}",
            resource_type="credential",
            resource_id=f"test-resource-{i+1}",
            correlation_id=f"test-correlation-{i+1}",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Test Browser)",
            metadata={"test": f"data-{i+1}"},
        ))
    return events