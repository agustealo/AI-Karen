-- WS-02 foundation: governed communication identity metadata only.
-- No uploaded samples, source text, credentials, or unrestricted system prompts.
BEGIN;

CREATE TABLE public.writing_style_profiles (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    profile_id uuid NOT NULL,
    owner_actor_id uuid NOT NULL,
    kind varchar(16) NOT NULL CHECK (kind IN ('personal', 'professional', 'business', 'client', 'team')),
    label varchar(120) NOT NULL CHECK (length(trim(label)) BETWEEN 1 AND 120),
    state varchar(16) NOT NULL DEFAULT 'draft' CHECK (state IN ('draft', 'published', 'revoked')),
    publication_revision bigint NOT NULL DEFAULT 0 CHECK (publication_revision >= 0),
    current_revision_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, profile_id),
    CONSTRAINT writing_style_profile_published_revision CHECK (
       (state = 'published' AND publication_revision > 0 AND current_revision_id IS NOT NULL)
       OR (state <> 'published')
    )
);

CREATE TABLE public.writing_style_revisions (
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    revision_id uuid NOT NULL,
    revision_number bigint NOT NULL CHECK (revision_number > 0),
    approved_expression jsonb NOT NULL CHECK (
        jsonb_typeof(approved_expression) = 'object'
        AND octet_length(approved_expression::text) <= 4096
    ),
    content_digest char(64) NOT NULL CHECK (content_digest ~ '^[a-f0-9]{64}$'),
    approved_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, profile_id, revision_id),
    UNIQUE (tenant_id, profile_id, revision_number),
    FOREIGN KEY (tenant_id, profile_id)
      REFERENCES public.writing_style_profiles(tenant_id, profile_id) ON DELETE RESTRICT
);

ALTER TABLE public.writing_style_profiles ADD CONSTRAINT writing_style_current_revision_fk
    FOREIGN KEY (tenant_id, profile_id, current_revision_id)
    REFERENCES public.writing_style_revisions(tenant_id, profile_id, revision_id)
    DEFERRABLE INITIALLY IMMEDIATE;

CREATE TABLE public.writing_style_grants (
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    purpose varchar(48) NOT NULL CHECK (purpose ~ '^[a-z][a-z0-9_-]{0,47}$'),
    granted_by uuid NOT NULL,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, profile_id, actor_id, purpose),
    FOREIGN KEY (tenant_id, profile_id)
      REFERENCES public.writing_style_profiles(tenant_id, profile_id) ON DELETE RESTRICT
);

CREATE TABLE public.writing_style_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    profile_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    action varchar(24) NOT NULL CHECK (action IN ('create', 'publish', 'grant', 'revoke_grant', 'revoke_profile')),
    publication_revision bigint NOT NULL DEFAULT 0,
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX writing_style_grants_actor ON public.writing_style_grants(tenant_id, actor_id, purpose)
    WHERE revoked_at IS NULL;
CREATE INDEX writing_style_audit_profile ON public.writing_style_audit(tenant_id, profile_id, created_at DESC);

-- Immutable published revision history, even for privileged backend callers.
CREATE FUNCTION public.writing_style_prevent_revision_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published style revisions are immutable';
END $$;
CREATE TRIGGER writing_style_no_revision_update
    BEFORE UPDATE OR DELETE ON public.writing_style_revisions
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_prevent_revision_mutation();

-- Retention is managed by explicit governed lifecycle, not cascade deletion of
-- referenced profiles/revisions. Tenant deletion follows canonical tenant policy.
REVOKE ALL ON public.writing_style_profiles, public.writing_style_revisions,
    public.writing_style_grants, public.writing_style_audit FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.writing_style_audit_id_seq FROM PUBLIC;
DO $revoke$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL ON public.writing_style_profiles, public.writing_style_revisions, public.writing_style_grants, public.writing_style_audit FROM %I', role_name
            );
            EXECUTE format('REVOKE ALL ON SEQUENCE public.writing_style_audit_id_seq FROM %I', role_name);
        END IF;
    END LOOP;
END $revoke$;

ALTER TABLE public.writing_style_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_audit FORCE ROW LEVEL SECURITY;

CREATE POLICY writing_style_profiles_tenant ON public.writing_style_profiles
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY writing_style_revisions_tenant ON public.writing_style_revisions
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY writing_style_grants_tenant ON public.writing_style_grants
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
CREATE POLICY writing_style_audit_tenant ON public.writing_style_audit
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

COMMENT ON TABLE public.writing_style_profiles IS 'Tenant-scoped communication identities; no private sample bodies.';
COMMENT ON TABLE public.writing_style_revisions IS 'Immutable, bounded, expression-only published revision snapshots.';
COMMENT ON TABLE public.writing_style_grants IS 'Explicit actor and purpose use grants; not a replacement for RuntimePolicy.';
COMMENT ON TABLE public.writing_style_audit IS 'Value-free mutation receipts tied to identity lifecycle.';
COMMIT;
