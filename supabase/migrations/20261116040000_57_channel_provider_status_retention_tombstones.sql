-- KWA-01C4: bounded, audited cleanup of unmatched Meta provider statuses.
-- Keep an immutable digest tombstone after removing recipient/provider IDs so
-- a replayed signed webhook cannot reintroduce expired sensitive evidence.
BEGIN;

CREATE TABLE public.channel_provider_status_tombstones (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    receipt_id char(64) NOT NULL CHECK (receipt_id ~ '^[0-9a-f]{64}$'),
    event_digest char(64) NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    source_created_at timestamptz NOT NULL,
    purged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id, receipt_id),
    CONSTRAINT channel_status_tombstone_connection_fk
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE CASCADE
);

REVOKE ALL ON public.channel_provider_status_tombstones FROM PUBLIC;
DO $channel_tombstone_roles$
DECLARE
    client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format(
                'REVOKE ALL ON public.channel_provider_status_tombstones FROM %I',
                client_role
            );
        END IF;
    END LOOP;
END
$channel_tombstone_roles$;

ALTER TABLE public.channel_provider_status_tombstones ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_provider_status_tombstones FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_status_tombstone_tenant_scope
    ON public.channel_provider_status_tombstones FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE OR REPLACE FUNCTION public.channel_status_tombstone_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Channel status retention tombstones are immutable';
END;
$$;
CREATE TRIGGER trg_channel_status_tombstone_immutable
    BEFORE UPDATE ON public.channel_provider_status_tombstones
    FOR EACH ROW EXECUTE FUNCTION public.channel_status_tombstone_immutable();

COMMENT ON TABLE public.channel_provider_status_tombstones IS
    'Tenant/connection-scoped digest-only anti-replay ledger for status evidence '
    'purged under an explicitly authorized, bounded retention action. '
    'No Meta message IDs, phone numbers, original payload, user ID, or credentials.';

COMMIT;
