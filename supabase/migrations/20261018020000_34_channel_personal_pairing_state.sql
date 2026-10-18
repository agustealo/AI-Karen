-- KOC-05: persisted evidence state, not a source of QR payloads or credentials.
-- Revision/sequence changes are committed under a locked channel connection row.
BEGIN;
CREATE TABLE IF NOT EXISTS public.channel_personal_pairing_state (
    tenant_id uuid NOT NULL,
    connection_id text NOT NULL,
    provider_id text NOT NULL,
    connection_revision bigint NOT NULL CHECK (connection_revision >= 1),
    sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0),
    phase text NOT NULL DEFAULT 'ready'
        CHECK (phase IN (
            'ready', 'qr_available', 'connected',
            'disconnect_pending', 'disconnected', 'unknown'
        )),
    qr_expires_at timestamptz,
    provider_link_receipt_id text,
    provider_unlink_receipt_id text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id, provider_id),
    CONSTRAINT channel_personal_pairing_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE CASCADE,
    CONSTRAINT channel_personal_pairing_provider_nonempty
        CHECK (length(trim(provider_id)) BETWEEN 1 AND 128),
    CONSTRAINT channel_personal_pairing_receipts_bounded CHECK (
        (provider_link_receipt_id IS NULL OR length(provider_link_receipt_id) BETWEEN 1 AND 256)
        AND (provider_unlink_receipt_id IS NULL OR length(provider_unlink_receipt_id) BETWEEN 1 AND 256)
    )
);

ALTER TABLE public.channel_personal_pairing_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_personal_pairing_state FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_personal_pairing_tenant_scope
    ON public.channel_personal_pairing_state FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_personal_pairing_state IS
    'Only authenticated provider evidence admitted by the governed ChannelHost. Never store QR contents, tokens or sessions here; receipt IDs are not cryptographic proof by themselves.';
COMMIT;
