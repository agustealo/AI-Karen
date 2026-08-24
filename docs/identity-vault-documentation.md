# Identity Vault System Documentation

## Overview

The Identity Vault System is a comprehensive identity and secrets management solution that supports one credential assigned to multiple external accounts/providers. It provides secure credential storage, OAuth flow management, account binding, token lifecycle management, and comprehensive audit logging.

## Architecture

### Core Components

1. **Database Schema** (`src/ai_karen_engine/database/identity_vault_schema.py`)
   - PostgreSQL schema for all identity vault entities
   - Proper indexes and foreign key relationships
   - Encrypted secret storage

2. **Data Models** (`src/ai_karen_engine/database/models/identity_vault.py`)
   - Pydantic models for API serialization and validation
   - Enums for credential status, token types, provider types, etc.
   - Utility functions for validation and processing

3. **Service Layer** (`src/ai_karen_engine/services/identity_vault/credential_vault_service.py`)
   - Main service providing comprehensive credential management
   - Encryption/decryption capabilities
   - OAuth flow integration
   - Account binding system
   - Audit logging
   - Health monitoring

4. **API Routes** (`server/routes/identity_vault.py`)
   - FastAPI routes for all identity vault operations
   - Provider management
   - Credential management
   - OAuth flows
   - Session management
   - Audit logging

### Core Entities

#### Credential
- Main entity for storing authentication information
- Supports multiple credential types (OAuth, API key, Basic Auth, etc.)
- Status tracking (ACTIVE, REFRESH_REQUIRED, EXPIRED, REVOKED, INVALID, ROTATING)
- Metadata storage and rotation intervals

#### CredentialSecret
- Encrypted storage for sensitive data
- Support for multiple secret types per credential
- HMAC-based integrity verification
- Key rotation support

#### ExternalAccount
- Representation of external service accounts
- Capability discovery and management
- Account-specific metadata

#### ProviderDefinition
- Configuration for external service providers
- OAuth settings and API endpoints
- Supported capabilities enumeration

#### CredentialBinding
- Links credentials to external accounts (1:N relationship)
- Primary binding designation
- Binding-specific metadata

#### AccountSession
- Active session management
- Token lease tracking
- Session metadata and expiration

#### AuthGrant
- OAuth authorization grant management
- Code-based authentication flow
- Token refresh handling

#### TokenLease
- Temporary token access management
- Lease-based access control
- Expiration and invalidation

#### LoginAttempt
- Authentication attempt tracking
- Success/failure recording
- Security monitoring

#### CredentialAuditEvent
- Comprehensive audit logging
- Event correlation and tracking
- Sensitive data redaction

## Key Features

### 1. Secure Credential Storage
- AES-256-GCM encryption for all secrets
- HMAC-based integrity verification
- Key rotation with proper fallback handling
- Secrets never returned raw to the UI

### 2. OAuth Flow Management
- Complete OAuth 2.0 flow implementation
- Authorization code and implicit grant support
- Token refresh with automatic rotation
- State and challenge parameter handling

### 3. Account Binding System
- One-to-many relationship (1 credential → many accounts)
- Primary binding designation
- Binding metadata and capabilities
- Bulk operations support

### 4. Token Lifecycle Management
- Status tracking (ACTIVE, REFRESH_REQUIRED, EXPIRED, REVOKED, INVALID, ROTATING)
- Automatic rotation with configurable intervals
- Lease-based temporary access
- Refresh token handling

### 5. Audit Trail
- Comprehensive logging for all sensitive operations
- Event correlation with correlation IDs
- IP address and user agent tracking
- Sensitive data redaction
- Configurable retention policies

### 6. Account Capability Discovery
- Automatic capability detection
- Provider-specific capability enumeration
- Dynamic capability updates
- Permission-based access control

### 7. RBAC Integration
- Multi-tenant isolation
- User-based access control
- Permission boundaries at all levels
- Tenant-aware operations

## API Endpoints

### Provider Management
- `POST /providers` - Create new provider definition
- `GET /providers/{provider_id}` - Get provider details
- `GET /providers` - List all providers
- `PUT /providers/{provider_id}` - Update provider
- `DELETE /providers/{provider_id}` - Delete provider

### Credential Management
- `POST /credentials` - Create new credential
- `GET /credentials/{credential_id}` - Get credential details
- `GET /credentials` - List credentials with filtering
- `PUT /credentials/{credential_id}` - Update credential
- `DELETE /credentials/{credential_id}` - Delete credential
- `POST /credentials/{credential_id}/rotate` - Rotate credential tokens
- `POST /credentials/{credential_id}/revoke` - Revoke credential

### External Account Management
- `POST /accounts` - Create external account
- `GET /accounts/{account_id}` - Get account details
- `GET /accounts` - List accounts with filtering
- `PUT /accounts/{account_id}` - Update account
- `DELETE /accounts/{account_id}` - Delete account

### Binding Management
- `POST /bindings` - Create credential binding
- `GET /bindings/{binding_id}` - Get binding details
- `GET /bindings` - List bindings with filtering
- `PUT /bindings/{binding_id}` - Update binding
- `DELETE /bindings/{binding_id}` - Delete binding

### OAuth Flow Management
- `POST /oauth/grants` - Create OAuth grant
- `POST /oauth/grants/{grant_id}/complete` - Complete OAuth flow
- `POST /oauth/refresh` - Refresh access token
- `POST /oauth/discover/{account_id}` - Discover account capabilities

### Session Management
- `POST /sessions` - Create account session
- `GET /sessions/{session_id}` - Get session details
- `GET /sessions` - List sessions with filtering
- `DELETE /sessions/{session_id}` - Invalidate session

### Token Lease Management
- `POST /leases` - Create token lease
- `GET /leases/{lease_token}` - Get lease details
- `DELETE /leases/{lease_token}` - Invalidate lease

### Audit Logging
- `GET /audit/events` - List audit events with filtering
- `GET /audit/events/{event_id}` - Get audit event details

## Security Considerations

### Encryption
- All secrets encrypted at rest using AES-256-GCM
- Separate encryption key management
- HMAC-based integrity verification
- Key rotation with proper handling

### OAuth Security
- State parameter enforcement for CSRF protection
- PKCE support for public clients
- Secure token storage with expiration
- Refresh token rotation

### Audit Security
- Comprehensive logging of all sensitive operations
- IP address and user agent tracking
- Correlation ID for request tracing
- Sensitive data redaction in logs

### Access Control
- Multi-tenant data isolation
- User-based permission boundaries
- Role-based access control integration
- Resource-level permissions

## Testing

The system includes comprehensive test coverage:

### Unit Tests
- Service layer functionality
- Data model validation
- Utility function testing
- Edge case handling

### Integration Tests
- Database operations
- API endpoint testing
- OAuth flow validation
- Audit logging verification

### Test Fixtures
- Mock database responses
- Test data generators
- Service mocking utilities
- Security scenario testing

## Configuration

### Identity Vault Config
```python
class IdentityVaultConfig(ServiceConfig):
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
    health_check_interval_minutes: int = 15
```

## Usage Examples

### Creating a Provider Definition
```python
from ai_karen_engine.database.models.identity_vault import ProviderDefinitionCreate

provider_data = ProviderDefinitionCreate(
    provider_id="github-provider",
    display_name="GitHub",
    description="GitHub API",
    provider_type=ProviderType.OAUTH2,
    config={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token"
    },
    supported_capabilities=[AccountCapability.GITHUB_READ, AccountCapability.GITHUB_WRITE]
)
```

### Creating a Credential
```python
from ai_karen_engine.database.models.identity_vault import CredentialCreate

credential_data = CredentialCreate(
    name="GitHub API Access",
    description="Access to GitHub API",
    provider_id=provider.id,
    credential_type="oauth",
    metadata={"scope": "repo user"}
)
```

### Creating an OAuth Grant
```python
from ai_karen_engine.database.models.identity_vault import AuthGrantCreate

grant_data = AuthGrantCreate(
    credential_id=credential.id,
    provider_id=provider.id,
    grant_type="authorization_code",
    authorization_code="auth-code-123",
    redirect_uri="https://your-app.com/callback",
    state="csrf-state-123"
)
```

### Completing OAuth Flow
```python
completed_grant = await service.complete_oauth_grant(
    grant_id=grant.id,
    access_token="access-token-123",
    refresh_token="refresh-token-456",
    scopes=["repo", "user"],
    tenant_id=tenant_id,
    user_id=user_id
)
```

## Monitoring and Health

### Health Checks
- Service availability monitoring
- Database connection health
- Encryption key status
- Token lease tracking

### Metrics
- Credential count by status
- Authentication success/failure rates
- Token refresh frequency
- Audit event volume

### Alerts
- Expiring credentials
- Failed authentication attempts
- Security events
- System health issues

## Future Enhancements

1. **Multi-factor Authentication** - Support for 2FA and MFA integrations
2. **Biometric Authentication** - Integration with biometric authentication systems
3. **Advanced Threat Detection** - Machine learning-based anomaly detection
4. **Federation Support** - SAML and OpenID Connect federation
5. **Key Management Service** - Integration with enterprise KMS
6. **Advanced Analytics** - Usage patterns and security insights
7. **Automated Remediation** - Automated response to security events

## Contributing

When contributing to the Identity Vault System:

1. Follow the existing code patterns and conventions
2. Ensure all new functionality is properly tested
3. Update documentation for new features
4. Follow security best practices
5. Ensure backward compatibility where possible

## License

This project is part of the AI-Karen platform and follows the same licensing terms.