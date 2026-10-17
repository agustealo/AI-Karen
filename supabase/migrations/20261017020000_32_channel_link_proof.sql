-- KOC-04D: one-use, tenant-scoped and expiry-bound external identity proofs.
-- Host-issued 256-bit challenge plaintext is returned once to authenticated
-- user; database stores only SHA-256. Telegram /link text never enters ChatRuntime.
BEGIN;

CREATE TABLE public.channel_link_challenges (
    challenge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    connection_id text NOT NULL,
    connection_revision bigint NOT NULL CHECK (connection_revision >= 1),
    user_id uuid NOT NULL,
    proof_digest char(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT channel_link_challenge_tenant_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE CASCADE,
    CONSTRAINT channel_link_challenge_tenant_user
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.auth_users(tenant_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT channel_link_challenge_digest_format
        CHECK (proof_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT channel_link_challenge_expiry
        CHECK (expires_at > created_at AND expires_at <= created_at + interval '15 minutes'),
    CONSTRAINT channel_link_challenge_finalized_once
        CHECK (consumed_at IS NULL OR revoked_at IS NULL)
);

CREATE UNIQUE INDEX idx_channel_link_challenge_active_user
    ON public.channel_link_challenges(tenant_id, connection_id, user_id)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

CREATE INDEX idx_channel_link_challenge_expiry
    ON public.channel_link_challenges(tenant_id, expires_at)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

ALTER TABLE public.channel_link_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_link_challenges FORCE ROW LEVEL SECURITY;

CREATE POLICY channel_link_challenge_tenant_scope
    ON public.channel_link_challenges
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_link_challenges IS
    'Host-governed expiring link challenges; no plaintext secret or external principal claim';

COMMIT;
