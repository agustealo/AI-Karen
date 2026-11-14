-- Tenant-scoped plugin field -> Identity Vault credential binding.
-- Only Identity Vault may own plaintext encryption, status, rotation or audit.
-- No secret bytes, plaintext, ciphertext, or credential suffixes in this table.
BEGIN;

CREATE TABLE public.plugin_credential_slots (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    plugin_id varchar(50) NOT NULL,
    field_key varchar(50) NOT NULL,
    credential_id uuid NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_plugin_credential_slots PRIMARY KEY (tenant_id, plugin_id, field_key),
    CONSTRAINT uq_plugin_credential_slots_tenant_credential UNIQUE (tenant_id, credential_id),
    CONSTRAINT fk_plugin_credential_slots_scoped_credential
        FOREIGN KEY (tenant_id, credential_id)
        REFERENCES public.credentials(tenant_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_plugin_credential_slots_revision CHECK (revision >= 1),
    CONSTRAINT ck_plugin_credential_slots_plugin CHECK (plugin_id ~ '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$'),
    CONSTRAINT ck_plugin_credential_slots_field CHECK (field_key ~ '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$')
);

CREATE INDEX idx_plugin_credential_slots_credential
    ON public.plugin_credential_slots (tenant_id, credential_id);

-- Settings/credentials only through authenticated application ingress. API
-- roles never get direct table grants, even on projects with legacy defaults.
REVOKE ALL ON public.plugin_credential_slots FROM PUBLIC;
DO $plugin_vault_grants$
DECLARE
    client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON public.plugin_credential_slots FROM %I', client_role);
        END IF;
    END LOOP;
END
$plugin_vault_grants$;

ALTER TABLE public.plugin_credential_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plugin_credential_slots FORCE ROW LEVEL SECURITY;

CREATE POLICY plugin_credential_slots_read ON public.plugin_credential_slots
    FOR SELECT USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );
CREATE POLICY plugin_credential_slots_insert ON public.plugin_credential_slots
    FOR INSERT WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );
CREATE POLICY plugin_credential_slots_update ON public.plugin_credential_slots
    FOR UPDATE USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.plugin_credential_slots IS
    'Tenant-local plugin secret field reference to canonical Identity Vault credentials. No secrets stored here.';

COMMIT;
