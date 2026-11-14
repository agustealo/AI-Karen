-- KOC-05: durable operator-initiated local retirement hold.
-- This is NOT vendor unlink, credential/data erasure or final connection deletion.
-- A single transaction fences the connection revision, disables channel
-- admission/dispatch and records the operator's explicit idempotent request.
BEGIN;

-- A nonreversible connection fence survives owner-account erasure, when the
-- personal audit hold itself is removed by the governed privacy cascade.
ALTER TABLE public.channel_connections
    ADD COLUMN retirement_locked boolean NOT NULL DEFAULT false;

CREATE TABLE public.channel_personal_retirement_holds (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    connection_id text NOT NULL,
    hold_id uuid NOT NULL DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL,
    operator_user_id uuid NOT NULL,
    requested_revision bigint NOT NULL CHECK (requested_revision >= 1),
    fenced_revision bigint NOT NULL CHECK (fenced_revision = requested_revision + 1),
    idempotency_key uuid NOT NULL,
    status text NOT NULL DEFAULT 'held' CHECK (status = 'held'),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, connection_id),
    UNIQUE (tenant_id, hold_id),
    CONSTRAINT channel_personal_retirement_hold_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT channel_personal_retirement_hold_owner
        FOREIGN KEY (tenant_id, connection_id, owner_user_id)
        REFERENCES public.channel_connection_owners(tenant_id, connection_id, user_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT channel_personal_retirement_hold_owner_erasure
        FOREIGN KEY (tenant_id, owner_user_id)
        REFERENCES public.auth_users(tenant_id, user_id) ON DELETE CASCADE
);

-- Preserve operator audit identity while the tenant retains the hold. User
-- account deletion and audit retention policy are separately governed; an
-- absent operator account does not lift the connection's activation fence.
ALTER TABLE public.channel_personal_retirement_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_personal_retirement_holds FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_retirement_hold_tenant_read
    ON public.channel_personal_retirement_holds FOR SELECT
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY channel_retirement_hold_tenant_insert
    ON public.channel_personal_retirement_holds FOR INSERT
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
-- No UPDATE or DELETE policy for ordinary tenant-scoped actors.
-- Tenant/user erasure uses the existing database FK cascade authority.

CREATE OR REPLACE FUNCTION public.channel_personal_retirement_activation_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $retirement_guard$
BEGIN
    IF OLD.retirement_locked IS TRUE AND NEW.retirement_locked IS NOT TRUE THEN
        RAISE EXCEPTION 'Personal channel retirement fence is irreversible'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.enabled IS TRUE
       AND (
           NEW.retirement_locked IS TRUE
           OR EXISTS (
           SELECT 1 FROM public.channel_personal_retirement_holds h
           WHERE h.tenant_id = NEW.tenant_id
             AND h.connection_id = NEW.connection_id
           )
       ) THEN
        RAISE EXCEPTION 'Personal channel has a durable retirement hold'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$retirement_guard$;

CREATE TRIGGER channel_personal_retirement_activation_guard
BEFORE UPDATE OF enabled, retirement_locked ON public.channel_connections
FOR EACH ROW EXECUTE FUNCTION public.channel_personal_retirement_activation_guard();

COMMENT ON TABLE public.channel_personal_retirement_holds IS
    'Durable, immutable operator retirement hold. Fences local channel activation but does not imply vendor unlink or credential/data erasure.';
COMMENT ON COLUMN public.channel_connections.retirement_locked IS
    'Irreversible local channel activation fence; retained after user account erasure; not proof of remote unlink or deletion.';
COMMENT ON FUNCTION public.channel_personal_retirement_activation_guard() IS
    'Reject reactivation of held personal channels, including noncanonical SQL updates and stale activation callers.';
COMMIT;
