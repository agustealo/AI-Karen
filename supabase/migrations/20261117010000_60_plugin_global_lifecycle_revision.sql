-- KPLUG-CONV-02C2: host-only global lifecycle revision and immutable claim ledger.
-- A database claim is NOT a PluginKernel mutation or proof of enable/disable.
-- A crash after claiming remains unresolved and cannot be retried blindly.
BEGIN;

CREATE TABLE public.extension_lifecycle_revisions (
    installation_id varchar(50) PRIMARY KEY,
    manifest_checksum char(64) NOT NULL,
    observed_state varchar(8) NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    disposition varchar(16) NOT NULL DEFAULT 'ready',
    active_operation_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT extension_lifecycle_id_check
        CHECK (installation_id ~ '^[a-z][a-z0-9_-]{0,49}$'),
    CONSTRAINT extension_lifecycle_checksum_check
        CHECK (manifest_checksum ~ '^[0-9a-f]{64}$'),
    CONSTRAINT extension_lifecycle_state_check
        CHECK (observed_state IN ('enabled','disabled')),
    CONSTRAINT extension_lifecycle_revision_check CHECK (revision >= 1),
    CONSTRAINT extension_lifecycle_disposition_check
        CHECK (disposition IN ('ready','unresolved')),
    CONSTRAINT extension_lifecycle_claim_consistency_check
        CHECK ((disposition = 'ready' AND active_operation_id IS NULL)
            OR (disposition = 'unresolved' AND active_operation_id IS NOT NULL))
);

CREATE TABLE public.extension_lifecycle_operations (
    operation_id uuid PRIMARY KEY,
    installation_id varchar(50) NOT NULL
        REFERENCES public.extension_lifecycle_revisions(installation_id)
        ON DELETE RESTRICT,
    approval_id uuid NOT NULL UNIQUE
        REFERENCES public.runtime_approval_requests(approval_id)
        ON DELETE RESTRICT,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES public.auth_users(user_id)
        ON DELETE RESTRICT,
    action varchar(7) NOT NULL,
    manifest_checksum char(64) NOT NULL,
    expected_state varchar(8) NOT NULL,
    target_state varchar(8) NOT NULL,
    expected_revision bigint NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'prepared',
    request_id varchar(128) NOT NULL,
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT extension_lifecycle_operation_action_check
        CHECK (
            (action = 'enable' AND expected_state = 'disabled' AND target_state = 'enabled')
            OR (action = 'disable' AND expected_state = 'enabled' AND target_state = 'disabled')
        ),
    CONSTRAINT extension_lifecycle_operation_checksum_check
        CHECK (manifest_checksum ~ '^[0-9a-f]{64}$'),
    CONSTRAINT extension_lifecycle_operation_revision_check
        CHECK (expected_revision >= 1),
    CONSTRAINT extension_lifecycle_operation_status_check
        CHECK (status IN ('prepared','unknown','verified_committed','rejected')),
    CONSTRAINT extension_lifecycle_operation_request_check
        CHECK (length(btrim(request_id)) > 0 AND length(btrim(correlation_id)) > 0),
    CONSTRAINT extension_lifecycle_one_operation_per_revision
        UNIQUE (installation_id, expected_revision)
);

ALTER TABLE public.extension_lifecycle_revisions
    ADD CONSTRAINT extension_lifecycle_active_operation_fk
    FOREIGN KEY (active_operation_id)
    REFERENCES public.extension_lifecycle_operations(operation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX extension_lifecycle_actor_history
    ON public.extension_lifecycle_operations(tenant_id, actor_user_id, created_at DESC);

-- These tables are application-global host-side evidence, NOT tenant settings.
-- Do not grant Data API clients access. Application database role receives
-- explicit deployment privileges; normal clients only see verified projections.
REVOKE ALL ON public.extension_lifecycle_revisions FROM PUBLIC;
REVOKE ALL ON public.extension_lifecycle_operations FROM PUBLIC;
DO $extension_lifecycle_client_revoke$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format(
                'REVOKE ALL ON public.extension_lifecycle_revisions, '
                || 'public.extension_lifecycle_operations FROM %I', client_role
            );
        END IF;
    END LOOP;
END
$extension_lifecycle_client_revoke$;

-- Revision rows represent one application-global installation; tenant RLS
-- would incorrectly partition that single mutex. Restrict them by backend DB
-- privileges instead. Operation receipts are additionally tenant-scoped.
ALTER TABLE public.extension_lifecycle_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.extension_lifecycle_operations FORCE ROW LEVEL SECURITY;

CREATE POLICY extension_lifecycle_operation_tenant_scope
    ON public.extension_lifecycle_operations FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.extension_lifecycle_revisions IS
    'Host-only application-global revision fence of observed PluginKernel state; unresolved claims require explicit reconciliation.';
COMMENT ON TABLE public.extension_lifecycle_operations IS
    'Tenant-scoped, value-free lifecycle action claims; prepared is not executed, and unknown is not success.';

COMMIT;
