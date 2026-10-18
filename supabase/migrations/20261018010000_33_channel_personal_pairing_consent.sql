-- KOC-05: durable, user-scoped risk consent for unofficial personal channel pairing.
-- No pairing process, QR generation or provider activation is authorized here.
BEGIN;

-- Assignment is operator-governed; the end-user consent action cannot assign itself ownership.
CREATE TABLE IF NOT EXISTS public.channel_connection_owners (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    user_id uuid NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id),
    UNIQUE (tenant_id, connection_id, user_id),
    CONSTRAINT channel_owner_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CONSTRAINT channel_owner_principal
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.auth_users(tenant_id, user_id) ON DELETE CASCADE
);
ALTER TABLE public.channel_connection_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_connection_owners FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_connection_owner_tenant_scope
    ON public.channel_connection_owners FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE TABLE IF NOT EXISTS public.channel_personal_pairing_consents (
    consent_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    user_id uuid NOT NULL,
    provider_id text NOT NULL,
    policy_version text NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT channel_pairing_consent_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CONSTRAINT channel_pairing_consent_owner
        FOREIGN KEY (tenant_id, connection_id, user_id)
        REFERENCES public.channel_connection_owners(tenant_id, connection_id, user_id),
    CONSTRAINT channel_pairing_consent_user
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.auth_users(tenant_id, user_id) ON DELETE CASCADE,
    CONSTRAINT channel_pairing_consent_provider_nonempty
        CHECK (length(trim(provider_id)) BETWEEN 1 AND 128),
    CONSTRAINT channel_pairing_consent_policy_nonempty
        CHECK (length(trim(policy_version)) BETWEEN 1 AND 128),
    CONSTRAINT channel_pairing_consent_revocation_order
        CHECK (revoked_at IS NULL OR revoked_at >= accepted_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_pairing_consent_current
    ON public.channel_personal_pairing_consents (tenant_id, connection_id, user_id, provider_id)
    WHERE revoked_at IS NULL;

ALTER TABLE public.channel_personal_pairing_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_personal_pairing_consents FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_pairing_consent_tenant_scope
    ON public.channel_personal_pairing_consents FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_personal_pairing_consents IS
    'Server-verified, policy-versioned acknowledgement of unofficial personal WhatsApp connection risk. A row is not a pairing authorization or provider receipt.';
COMMIT;
