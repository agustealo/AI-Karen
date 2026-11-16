-- KWA-01B: signed provider status evidence, separate from inbound user turns.
-- Canonical owner: SqlChannelRepository. No native body, user, or Vault secret
-- is stored here. A send receipt and a delivery/read observation are distinct.
BEGIN;

CREATE TABLE public.channel_provider_status_events (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    connection_revision integer NOT NULL CHECK (connection_revision > 0),
    provider_message_id text NOT NULL
        CHECK (length(provider_message_id) BETWEEN 7 AND 256
               AND provider_message_id LIKE 'wamid.%'),
    recipient_id text NOT NULL
        CHECK (recipient_id ~ '^[0-9]{1,32}$'),
    state text NOT NULL CHECK (state IN ('sent', 'delivered', 'read', 'failed')),
    provider_timestamp bigint NOT NULL
        CHECK (provider_timestamp BETWEEN 1 AND 4102444800),
    receipt_id char(64) NOT NULL CHECK (receipt_id ~ '^[0-9a-f]{64}$'),
    event_digest char(64) NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    error_code text CHECK (
        (state = 'failed' AND error_code = 'whatsapp_provider_failed')
        OR (state <> 'failed' AND error_code IS NULL)
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id, receipt_id),
    CONSTRAINT channel_provider_status_connection_fk
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_channel_provider_status_match
    ON public.channel_provider_status_events (
        tenant_id, connection_id, connection_revision,
        provider_message_id, recipient_id
    );
CREATE INDEX idx_channel_provider_status_retention
    ON public.channel_provider_status_events (tenant_id, created_at);

-- A provider message ID is a single real send within a tenant/connection.
-- Refuse preexisting ambiguous attribution instead of updating multiple rows.
CREATE UNIQUE INDEX uq_channel_outbox_provider_message_scope
    ON public.channel_outbox (tenant_id, connection_id, provider_message_id)
    WHERE provider_message_id IS NOT NULL;

REVOKE ALL ON public.channel_provider_status_events FROM PUBLIC;
DO $channel_status_grants$
DECLARE
    client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON public.channel_provider_status_events FROM %I', client_role);
        END IF;
    END LOOP;
END
$channel_status_grants$;

ALTER TABLE public.channel_provider_status_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_provider_status_events FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_provider_status_tenant_scope
    ON public.channel_provider_status_events
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_provider_status_events IS
    'Tenant/revision/recipient-bound, deduplicated signed Meta status observations. '
    'No chat prompts, provider message text, credentials, or claimed user identity. '
    'Pending unmatched statuses require governed retention cleanup; not a delivery success.';

COMMIT;
