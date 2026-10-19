-- KOC-07: durable deletion intent, never evidence that provider erased credentials.
BEGIN;
CREATE TABLE public.channel_personal_credential_deletions (
    tenant_id uuid NOT NULL,
    request_id uuid NOT NULL,
    connection_id text NOT NULL,
    provider_id text NOT NULL,
    user_id uuid NOT NULL,
    connection_revision bigint NOT NULL CHECK (connection_revision >= 1),
    session_reference text NOT NULL,
    credential_scope text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'provider_pending', 'provider_claimed', 'verification_pending', 'verified', 'unknown')),
    provider_receipt_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, request_id),
    UNIQUE (tenant_id, connection_id, provider_id, connection_revision, idempotency_key),
    FOREIGN KEY (tenant_id, connection_id, user_id)
        REFERENCES public.channel_connection_owners(tenant_id, connection_id, user_id),
    FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CHECK (length(trim(provider_id)) BETWEEN 1 AND 128),
    CHECK (length(trim(session_reference)) BETWEEN 1 AND 256),
    CHECK (length(trim(credential_scope)) BETWEEN 1 AND 128),
    CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 128),
    CHECK (provider_receipt_id IS NULL OR length(trim(provider_receipt_id)) BETWEEN 1 AND 256),
    CHECK (status NOT IN ('provider_claimed', 'verification_pending', 'verified') OR provider_receipt_id IS NOT NULL)
);
CREATE INDEX idx_channel_personal_deletion_pending
    ON public.channel_personal_credential_deletions(tenant_id, status, created_at)
    WHERE status IN ('requested', 'provider_pending', 'unknown');
ALTER TABLE public.channel_personal_credential_deletions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_personal_credential_deletions FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_personal_deletions_tenant_scope
    ON public.channel_personal_credential_deletions FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
COMMENT ON TABLE public.channel_personal_credential_deletions IS
    'Host-owned deletion intent and vendor claims; verified requires separate independent verification. No secrets or QR payloads.';
COMMIT;
