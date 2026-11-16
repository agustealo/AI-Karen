-- KWA-01D3: Globally exclusive Telegram bot identity ownership.
-- Telegram's getMe numeric bot ID is provider-verifiable. A caller label or
-- Vault reference is NOT a globally unique identity. Never store bot tokens.
BEGIN;

CREATE TABLE public.channel_telegram_bot_owners (
    provider_bot_id bigint PRIMARY KEY CHECK (provider_bot_id > 0),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    connection_revision bigint NOT NULL CHECK (connection_revision > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, connection_id),
    CONSTRAINT channel_telegram_bot_owner_connection_fk
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections (tenant_id, connection_id)
        ON DELETE CASCADE
);

REVOKE ALL ON public.channel_telegram_bot_owners FROM PUBLIC;
DO $telegram_owner_grants$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format(
                'REVOKE ALL ON public.channel_telegram_bot_owners FROM %I',
                client_role
            );
        END IF;
    END LOOP;
END
$telegram_owner_grants$;

ALTER TABLE public.channel_telegram_bot_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_telegram_bot_owners FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_telegram_bot_owner_tenant_scope
ON public.channel_telegram_bot_owners FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.channel_telegram_bot_owners IS
    'Provider-verified numeric Telegram bot identity, globally unique across '
    'tenants and connections. No token, signing secret, or provider URL. '
    'Ownership is retained until separately authorized lifecycle recovery.';

COMMIT;
