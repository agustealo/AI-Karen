-- KOC-04B: governed, durable and tenant-isolated channel admission.
-- Installation remains PluginKernel-owned. Credentials are references into
-- the host secret vault, never plaintext transport tokens in this schema.
-- No implicit worker RLS bypass. Schema creation is migration-owned.
BEGIN;

CREATE TABLE IF NOT EXISTS public.channel_connections (
    connection_id text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    installation_id text NOT NULL,
    provider_account_id text NOT NULL,
    credential_handle text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT channel_connections_tenant_connection UNIQUE (tenant_id, connection_id),
    CONSTRAINT channel_connections_account UNIQUE (tenant_id, installation_id, provider_account_id),
    CONSTRAINT channel_connections_nonempty CHECK (
        length(trim(connection_id)) > 0 AND length(trim(installation_id)) > 0
        AND length(trim(provider_account_id)) > 0 AND length(trim(credential_handle)) > 0
    )
);

CREATE TABLE IF NOT EXISTS public.channel_identity_bindings (
    binding_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    external_sender_id text NOT NULL,
    user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    verified_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT channel_identity_unique_sender
        UNIQUE (tenant_id, connection_id, external_sender_id),
    CONSTRAINT channel_identity_tenant_binding_principal
        UNIQUE (tenant_id, connection_id, binding_id, user_id),
    CONSTRAINT channel_identity_tenant_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CONSTRAINT channel_identity_nonempty_sender CHECK (length(trim(external_sender_id)) > 0),
    CONSTRAINT channel_identity_verified_before_revocation CHECK (
        revoked_at IS NULL OR revoked_at >= verified_at
    )
);

CREATE INDEX IF NOT EXISTS idx_channel_identity_principal
    ON public.channel_identity_bindings (tenant_id, user_id)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS public.channel_inbox (
    inbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    external_event_id text NOT NULL,
    external_sender_id text NOT NULL,
    external_conversation_id text NOT NULL,
    message_kind text NOT NULL,
    message_text text,
    event_digest text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    claim_token uuid,
    claim_expires_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code text,
    binding_id uuid REFERENCES public.channel_identity_bindings(binding_id),
    user_id uuid REFERENCES public.auth_users(user_id),
    conversation_id text,
    correlation_id uuid NOT NULL DEFAULT gen_random_uuid(),
    result_receipt jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(result_receipt) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT channel_inbox_unique_event
        UNIQUE (tenant_id, connection_id, external_event_id),
    CONSTRAINT channel_inbox_tenant_identity
        FOREIGN KEY (tenant_id, connection_id, binding_id, user_id)
        REFERENCES public.channel_identity_bindings(tenant_id, connection_id, binding_id, user_id),
    CONSTRAINT channel_inbox_tenant_inbox
        UNIQUE (tenant_id, connection_id, inbox_id),
    CONSTRAINT channel_inbox_verified_binding_pair CHECK (
        (binding_id IS NULL AND user_id IS NULL)
        OR (binding_id IS NOT NULL AND user_id IS NOT NULL)
    ),
    CONSTRAINT channel_inbox_tenant_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CONSTRAINT channel_inbox_nonempty CHECK (
        length(trim(external_event_id)) > 0 AND length(trim(external_sender_id)) > 0
        AND length(trim(external_conversation_id)) > 0 AND length(trim(event_digest)) = 64
    ),
    CONSTRAINT channel_inbox_bounded_text CHECK (
        message_text IS NULL OR length(message_text) <= 32768
    ),
    CONSTRAINT channel_inbox_claim_consistency CHECK (
        (claim_token IS NULL AND claim_expires_at IS NULL)
        OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_channel_inbox_claim
    ON public.channel_inbox (tenant_id, status, claim_expires_at, created_at);
CREATE INDEX IF NOT EXISTS idx_channel_inbox_principal
    ON public.channel_inbox (tenant_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.channel_outbox (
    delivery_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    inbox_id uuid NOT NULL,
    destination_id text NOT NULL,
    idempotency_key text NOT NULL,
    message_kind text NOT NULL,
    message_text text,
    status text NOT NULL DEFAULT 'accepted'
        CHECK (status IN ('accepted', 'sent', 'delivered', 'read', 'failed', 'unknown')),
    provider_message_id text,
    provider_receipt_id text,
    last_error_code text,
    claim_token uuid,
    claim_expires_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT channel_outbox_unique_delivery UNIQUE (tenant_id, connection_id, idempotency_key),
    CONSTRAINT channel_outbox_tenant_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id) ON DELETE CASCADE,
    CONSTRAINT channel_outbox_tenant_inbox
        FOREIGN KEY (tenant_id, connection_id, inbox_id)
        REFERENCES public.channel_inbox(tenant_id, connection_id, inbox_id) ON DELETE CASCADE,
    CONSTRAINT channel_outbox_nonempty CHECK (
        length(trim(destination_id)) > 0 AND length(trim(idempotency_key)) > 0
    ),
    CONSTRAINT channel_outbox_bounded_text CHECK (
        message_text IS NULL OR length(message_text) <= 32768
    ),
    CONSTRAINT channel_outbox_claim_consistency CHECK (
        (claim_token IS NULL AND claim_expires_at IS NULL)
        OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_channel_outbox_dispatch
    ON public.channel_outbox (tenant_id, status, claim_expires_at, created_at);

ALTER TABLE public.channel_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE public.channel_identity_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_identity_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE public.channel_inbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_inbox FORCE ROW LEVEL SECURITY;
ALTER TABLE public.channel_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_outbox FORCE ROW LEVEL SECURITY;

CREATE POLICY channel_connections_tenant_scope ON public.channel_connections
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY channel_identity_tenant_scope ON public.channel_identity_bindings
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY channel_inbox_tenant_scope ON public.channel_inbox
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY channel_outbox_tenant_scope ON public.channel_outbox
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_connections IS
    'Tenant-scoped configured channel accounts; installation remains owned by PluginKernel.';
COMMENT ON TABLE public.channel_identity_bindings IS
    'Host-verified external sender bindings, never adapter-asserted Karen principals.';
COMMENT ON TABLE public.channel_inbox IS
    'Durable idempotent inbound events. Claims and runtime receipt need fencing.';
COMMENT ON TABLE public.channel_outbox IS
    'Durable deliveries. Provider receipts determine truth; accepted is not sent.';

COMMIT;
