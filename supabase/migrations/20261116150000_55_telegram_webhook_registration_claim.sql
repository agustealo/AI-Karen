-- KWA-01D: durable, tenant-fenced Telegram webhook mutation claim.
-- A remote POST cannot roll back with SQL. Unknown/expired claims stay blocked
-- until a separately authorized, read-only provider reconciliation is added.
BEGIN;

CREATE TABLE public.channel_telegram_webhook_claims (
    tenant_id uuid NOT NULL,
    connection_id text NOT NULL,
    connection_revision integer NOT NULL CHECK (connection_revision > 0),
    claim_token uuid NOT NULL,
    state text NOT NULL DEFAULT 'in_flight'
        CHECK (state IN ('in_flight', 'uncertain', 'verified')),
    claim_expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id),
    CONSTRAINT channel_telegram_webhook_claim_connection_fk
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections (tenant_id, connection_id)
        ON DELETE CASCADE
);

-- Lifecycle changes on a connection cannot interleave with a Telegram
-- provider mutation. An expired claim is still ambiguous: NEVER ignore it.
CREATE FUNCTION public.guard_channel_telegram_webhook_transition()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF (NEW.revision IS DISTINCT FROM OLD.revision
        OR NEW.enabled IS DISTINCT FROM OLD.enabled)
       AND EXISTS (
           SELECT 1 FROM public.channel_telegram_webhook_claims claim
           WHERE claim.tenant_id = OLD.tenant_id
             AND claim.connection_id = OLD.connection_id
             AND claim.state IN ('in_flight', 'uncertain')
       ) THEN
        RAISE EXCEPTION 'Channel Telegram webhook mutation unresolved'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER guard_channel_telegram_webhook_lifecycle
BEFORE UPDATE OF enabled, revision ON public.channel_connections
FOR EACH ROW EXECUTE FUNCTION public.guard_channel_telegram_webhook_transition();

REVOKE ALL ON public.channel_telegram_webhook_claims FROM PUBLIC;
DO $channel_registration_grants$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format(
                'REVOKE ALL ON public.channel_telegram_webhook_claims FROM %I',
                client_role
            );
        END IF;
    END LOOP;
END
$channel_registration_grants$;

ALTER TABLE public.channel_telegram_webhook_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_telegram_webhook_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_telegram_claim_tenant_scope
ON public.channel_telegram_webhook_claims FOR ALL
USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
)
WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

COMMENT ON TABLE public.channel_telegram_webhook_claims IS
    'One durable mutation claim per tenant/connection. Expired or uncertain '
    'network operations must be reconciled, never retried blindly. No secrets.';

COMMIT;
