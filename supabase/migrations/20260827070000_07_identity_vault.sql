-- AI KAREN production baseline: Identity Vault
-- Schema evolution authority: supabase/migrations only.

CREATE TABLE IF NOT EXISTS identity_providers (
    id UUID PRIMARY KEY,
    provider_id VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    provider_type VARCHAR(50) NOT NULL,
    config JSON NOT NULL,
    icon_url VARCHAR(500),
    website_url VARCHAR(500),
    supported_capabilities JSON NOT NULL DEFAULT '[]'::json,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_identity_providers_enabled ON identity_providers(enabled);
CREATE INDEX IF NOT EXISTS idx_identity_providers_type ON identity_providers(provider_type);

CREATE TABLE IF NOT EXISTS credentials (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    provider_id UUID NOT NULL REFERENCES identity_providers(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    credential_type VARCHAR(50) NOT NULL,
    credential_metadata JSON NOT NULL DEFAULT '{}'::json,
    masked_hint VARCHAR(255),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    rotation_interval_hours INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_credentials_provider ON credentials(provider_id);
CREATE INDEX IF NOT EXISTS idx_credentials_status ON credentials(status);
CREATE INDEX IF NOT EXISTS idx_credentials_type ON credentials(credential_type);
CREATE INDEX IF NOT EXISTS idx_credentials_expires ON credentials(expires_at);
CREATE INDEX IF NOT EXISTS idx_credentials_last_used ON credentials(last_used_at);

CREATE TABLE IF NOT EXISTS credential_secrets (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    secret_type VARCHAR(50) NOT NULL,
    encrypted_value TEXT NOT NULL,
    encryption_key_id VARCHAR(255),
    secret_metadata JSON NOT NULL DEFAULT '{}'::json,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_credential_secrets_credential ON credential_secrets(credential_id);
CREATE INDEX IF NOT EXISTS idx_credential_secrets_type ON credential_secrets(secret_type);

CREATE TABLE IF NOT EXISTS external_accounts (
    id UUID PRIMARY KEY,
    provider_id UUID NOT NULL REFERENCES identity_providers(id) ON DELETE CASCADE,
    account_identifier VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    account_metadata JSON NOT NULL DEFAULT '{}'::json,
    capabilities JSON NOT NULL DEFAULT '[]'::json,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_external_accounts_provider_identifier UNIQUE(provider_id, account_identifier)
);
CREATE INDEX IF NOT EXISTS idx_external_accounts_provider ON external_accounts(provider_id);
CREATE INDEX IF NOT EXISTS idx_external_accounts_identifier ON external_accounts(account_identifier);
CREATE INDEX IF NOT EXISTS idx_external_accounts_active ON external_accounts(is_active);

CREATE TABLE IF NOT EXISTS credential_bindings (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    external_account_id UUID NOT NULL REFERENCES external_accounts(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    binding_metadata JSON NOT NULL DEFAULT '{}'::json,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_external_account_primary UNIQUE(external_account_id, is_primary)
);
CREATE INDEX IF NOT EXISTS idx_credential_bindings_credential ON credential_bindings(credential_id);
CREATE INDEX IF NOT EXISTS idx_credential_bindings_account ON credential_bindings(external_account_id);
CREATE INDEX IF NOT EXISTS idx_credential_bindings_active ON credential_bindings(is_active);

CREATE TABLE IF NOT EXISTS account_sessions (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    external_account_id UUID NOT NULL REFERENCES external_accounts(id) ON DELETE CASCADE,
    session_token VARCHAR(255) NOT NULL UNIQUE,
    access_token TEXT,
    refresh_token TEXT,
    token_type VARCHAR(50) NOT NULL,
    expires_at TIMESTAMPTZ,
    scopes JSON NOT NULL DEFAULT '[]'::json,
    session_metadata JSON NOT NULL DEFAULT '{}'::json,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_account_sessions_credential ON account_sessions(credential_id);
CREATE INDEX IF NOT EXISTS idx_account_sessions_account ON account_sessions(external_account_id);
CREATE INDEX IF NOT EXISTS idx_account_sessions_active ON account_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_account_sessions_expires ON account_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_account_sessions_token ON account_sessions(session_token);

CREATE TABLE IF NOT EXISTS auth_grants (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES identity_providers(id) ON DELETE CASCADE,
    grant_type VARCHAR(50) NOT NULL,
    authorization_code VARCHAR(255),
    access_token TEXT,
    refresh_token TEXT,
    scopes JSON NOT NULL DEFAULT '[]'::json,
    expires_at TIMESTAMPTZ,
    redirect_uri VARCHAR(500),
    state VARCHAR(255),
    code_challenge VARCHAR(255),
    code_challenge_method VARCHAR(50),
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_auth_grants_credential ON auth_grants(credential_id);
CREATE INDEX IF NOT EXISTS idx_auth_grants_provider ON auth_grants(provider_id);
CREATE INDEX IF NOT EXISTS idx_auth_grants_completed ON auth_grants(is_completed);
CREATE INDEX IF NOT EXISTS idx_auth_grants_expires ON auth_grants(expires_at);

CREATE TABLE IF NOT EXISTS token_leases (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    lease_token VARCHAR(255) NOT NULL UNIQUE,
    access_token TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    scopes JSON NOT NULL DEFAULT '[]'::json,
    lease_metadata JSON NOT NULL DEFAULT '{}'::json,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_token_leases_credential ON token_leases(credential_id);
CREATE INDEX IF NOT EXISTS idx_token_leases_active ON token_leases(is_active);
CREATE INDEX IF NOT EXISTS idx_token_leases_expires ON token_leases(expires_at);
CREATE INDEX IF NOT EXISTS idx_token_leases_token ON token_leases(lease_token);

CREATE TABLE IF NOT EXISTS login_attempts (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    external_account_id UUID REFERENCES external_accounts(id) ON DELETE CASCADE,
    attempt_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    error_code VARCHAR(100),
    error_message TEXT,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempt_metadata JSON NOT NULL DEFAULT '{}'::json
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_credential ON login_attempts(credential_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_account ON login_attempts(external_account_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_status ON login_attempts(status);
CREATE INDEX IF NOT EXISTS idx_login_attempts_timestamp ON login_attempts(timestamp);

CREATE TABLE IF NOT EXISTS credential_audit_events (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    account_id UUID REFERENCES external_accounts(id) ON DELETE CASCADE,
    provider_id UUID REFERENCES identity_providers(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(255),
    correlation_id VARCHAR(255),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    audit_metadata JSON NOT NULL DEFAULT '{}'::json,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_tenant ON credential_audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_user ON credential_audit_events(user_id);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_credential ON credential_audit_events(credential_id);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_event ON credential_audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_timestamp ON credential_audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_credential_audit_events_correlation ON credential_audit_events(correlation_id);
