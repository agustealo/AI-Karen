-- AI KAREN Identity Vault tenant ownership closure.
-- Existing unowned rows remain inaccessible until explicitly reconciled by an operator.

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'identity_providers',
        'credentials',
        'credential_secrets',
        'external_accounts',
        'credential_bindings',
        'account_sessions',
        'auth_grants',
        'token_leases',
        'login_attempts'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id UUID', table_name);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (tenant_id)',
            'idx_' || table_name || '_tenant',
            table_name
        );
    END LOOP;
END $$;

-- Tenant-local identity and account uniqueness.
ALTER TABLE identity_providers DROP CONSTRAINT IF EXISTS identity_providers_provider_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_providers_tenant_provider
    ON identity_providers (tenant_id, provider_id)
    WHERE tenant_id IS NOT NULL;

ALTER TABLE external_accounts DROP CONSTRAINT IF EXISTS uq_external_accounts_provider_identifier;
CREATE UNIQUE INDEX IF NOT EXISTS uq_external_accounts_tenant_provider_identifier
    ON external_accounts (tenant_id, provider_id, account_identifier)
    WHERE tenant_id IS NOT NULL;

-- Composite identity keys provide database-level tenant consistency for relationships.
CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_providers_tenant_id
    ON identity_providers (tenant_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_credentials_tenant_id
    ON credentials (tenant_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_external_accounts_tenant_id
    ON external_accounts (tenant_id, id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credentials_tenant_provider') THEN
        ALTER TABLE credentials
            ADD CONSTRAINT fk_credentials_tenant_provider
            FOREIGN KEY (tenant_id, provider_id)
            REFERENCES identity_providers (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_secrets_tenant_credential') THEN
        ALTER TABLE credential_secrets
            ADD CONSTRAINT fk_credential_secrets_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_external_accounts_tenant_provider') THEN
        ALTER TABLE external_accounts
            ADD CONSTRAINT fk_external_accounts_tenant_provider
            FOREIGN KEY (tenant_id, provider_id)
            REFERENCES identity_providers (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_bindings_tenant_credential') THEN
        ALTER TABLE credential_bindings
            ADD CONSTRAINT fk_credential_bindings_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_bindings_tenant_account') THEN
        ALTER TABLE credential_bindings
            ADD CONSTRAINT fk_credential_bindings_tenant_account
            FOREIGN KEY (tenant_id, external_account_id)
            REFERENCES external_accounts (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_account_sessions_tenant_credential') THEN
        ALTER TABLE account_sessions
            ADD CONSTRAINT fk_account_sessions_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_account_sessions_tenant_account') THEN
        ALTER TABLE account_sessions
            ADD CONSTRAINT fk_account_sessions_tenant_account
            FOREIGN KEY (tenant_id, external_account_id)
            REFERENCES external_accounts (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_auth_grants_tenant_credential') THEN
        ALTER TABLE auth_grants
            ADD CONSTRAINT fk_auth_grants_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_auth_grants_tenant_provider') THEN
        ALTER TABLE auth_grants
            ADD CONSTRAINT fk_auth_grants_tenant_provider
            FOREIGN KEY (tenant_id, provider_id)
            REFERENCES identity_providers (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_token_leases_tenant_credential') THEN
        ALTER TABLE token_leases
            ADD CONSTRAINT fk_token_leases_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_login_attempts_tenant_credential') THEN
        ALTER TABLE login_attempts
            ADD CONSTRAINT fk_login_attempts_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_login_attempts_tenant_account') THEN
        ALTER TABLE login_attempts
            ADD CONSTRAINT fk_login_attempts_tenant_account
            FOREIGN KEY (tenant_id, external_account_id)
            REFERENCES external_accounts (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_audit_tenant_credential') THEN
        ALTER TABLE credential_audit_events
            ADD CONSTRAINT fk_credential_audit_tenant_credential
            FOREIGN KEY (tenant_id, credential_id)
            REFERENCES credentials (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_audit_tenant_account') THEN
        ALTER TABLE credential_audit_events
            ADD CONSTRAINT fk_credential_audit_tenant_account
            FOREIGN KEY (tenant_id, account_id)
            REFERENCES external_accounts (tenant_id, id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_credential_audit_tenant_provider') THEN
        ALTER TABLE credential_audit_events
            ADD CONSTRAINT fk_credential_audit_tenant_provider
            FOREIGN KEY (tenant_id, provider_id)
            REFERENCES identity_providers (tenant_id, id);
    END IF;
END $$;

-- The old two-column uniqueness rule accidentally allowed only one non-primary binding.
ALTER TABLE credential_bindings DROP CONSTRAINT IF EXISTS uq_external_account_primary;
CREATE UNIQUE INDEX IF NOT EXISTS uq_credential_bindings_primary_per_account
    ON credential_bindings (tenant_id, external_account_id)
    WHERE is_primary IS TRUE AND is_active IS TRUE AND tenant_id IS NOT NULL;

-- Audit events cover provider/account/session actions that do not always have a credential.
ALTER TABLE credential_audit_events ALTER COLUMN credential_id DROP NOT NULL;

-- New application writes always carry tenant ownership. If pre-existing unowned rows exist,
-- they are intentionally quarantined instead of being silently assigned to a tenant.
DO $$
DECLARE
    table_name text;
    null_count bigint;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'identity_providers',
        'credentials',
        'credential_secrets',
        'external_accounts',
        'credential_bindings',
        'account_sessions',
        'auth_grants',
        'token_leases',
        'login_attempts'
    ]
    LOOP
        EXECUTE format('SELECT count(*) FROM %I WHERE tenant_id IS NULL', table_name) INTO null_count;
        IF null_count = 0 THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN tenant_id SET NOT NULL', table_name);
        END IF;
    END LOOP;
END $$;
