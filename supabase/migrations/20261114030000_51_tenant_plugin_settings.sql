-- Governed local plugin settings. No credentials or secret material may be
-- written here. Configuration remains separate from runtime/chat execution.
BEGIN;

CREATE TABLE public.extension_plugin_settings (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    plugin_id varchar(128) NOT NULL,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1,
    updated_by varchar(255) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_extension_plugin_settings PRIMARY KEY (tenant_id, plugin_id),
    CONSTRAINT ck_extension_plugin_settings_object CHECK (
        jsonb_typeof(settings) = 'object'
        AND octet_length(settings::text) <= 16384
    ),
    CONSTRAINT ck_extension_plugin_settings_revision CHECK (revision >= 1)
);

CREATE TABLE public.extension_plugin_settings_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    plugin_id varchar(128) NOT NULL,
    actor_user_id varchar(255) NOT NULL,
    operation varchar(16) NOT NULL,
    revision bigint NOT NULL,
    request_id varchar(128) NOT NULL,
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_extension_plugin_settings_audit_action CHECK (
        operation IN ('save', 'reset')
    )
);
CREATE INDEX idx_extension_plugin_settings_audit_tenant_plugin
    ON public.extension_plugin_settings_audit
       (tenant_id, plugin_id, revision DESC);

ALTER TABLE public.extension_plugin_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.extension_plugin_settings FORCE ROW LEVEL SECURITY;
ALTER TABLE public.extension_plugin_settings_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.extension_plugin_settings_audit FORCE ROW LEVEL SECURITY;

CREATE POLICY extension_plugin_settings_select
    ON public.extension_plugin_settings FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );
CREATE POLICY extension_plugin_settings_insert
    ON public.extension_plugin_settings FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );
CREATE POLICY extension_plugin_settings_update
    ON public.extension_plugin_settings FOR UPDATE
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

CREATE POLICY extension_plugin_settings_audit_select
    ON public.extension_plugin_settings_audit FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );
CREATE POLICY extension_plugin_settings_audit_insert
    ON public.extension_plugin_settings_audit FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.extension_plugin_settings IS
    'Tenant-scoped, manifest-validated nonsecret plugin settings; version fenced, no credentials.';
COMMENT ON TABLE public.extension_plugin_settings_audit IS
    'Atomic audit receipts without configuration values or credentials. Mutations are not exposed.';
COMMIT;
