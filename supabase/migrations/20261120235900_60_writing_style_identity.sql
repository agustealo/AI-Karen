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
    UNIQUE (tenant_id, profile_id, owner_actor_id),
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
      REFERENCES public.writing_style_profiles(tenant_id, profile_id) ON DELETE CASCADE
);

ALTER TABLE public.writing_style_profiles ADD CONSTRAINT writing_style_current_revision_fk
    FOREIGN KEY (tenant_id, profile_id, current_revision_id)
    REFERENCES public.writing_style_revisions(tenant_id, profile_id, revision_id)
    DEFERRABLE INITIALLY IMMEDIATE;

CREATE TABLE public.writing_style_grants (
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    owner_actor_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    purpose varchar(48) NOT NULL CHECK (purpose ~ '^[a-z][a-z0-9_-]{0,47}$'),
    granted_by uuid NOT NULL,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, profile_id, actor_id, purpose),
    FOREIGN KEY (tenant_id, profile_id, owner_actor_id)
      REFERENCES public.writing_style_profiles(
          tenant_id, profile_id, owner_actor_id
      ) ON DELETE CASCADE
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
RETURNS trigger LANGUAGE plpgsql AS $
BEGIN
    -- A committed revision cannot be edited or deleted directly. Governed
    -- parent/tenant deletion must still erase dependent private revisions.
    -- FK cascades run after the owning parent row has been removed.
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM public.writing_style_profiles p
        WHERE p.tenant_id = OLD.tenant_id AND p.profile_id = OLD.profile_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'published style revisions are immutable';
END $;
CREATE TRIGGER writing_style_no_revision_update
    BEFORE UPDATE OR DELETE ON public.writing_style_revisions
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_prevent_revision_mutation();

-- Private revision/grant rows follow existing governed tenant/profile erasure.
-- Direct revision deletion remains blocked by the immutable trigger and RLS.
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

-- Never grant a whole tenant visibility of confidential styles. The host
-- binds app.current_user_id and app.current_style_purpose from authenticated
-- execution context. Missing principal or purpose fails closed.
-- Grant SELECT policies have no profile subquery, avoiding recursive RLS.
CREATE POLICY writing_style_grants_principal_select
    ON public.writing_style_grants FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND (
            actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            OR granted_by = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
    );

CREATE POLICY writing_style_profiles_principal_select
    ON public.writing_style_profiles FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND (
            owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            OR EXISTS (
                SELECT 1 FROM public.writing_style_grants g
                WHERE g.tenant_id = writing_style_profiles.tenant_id
                  AND g.profile_id = writing_style_profiles.profile_id
                  AND g.actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                  AND g.purpose = NULLIF(current_setting('app.current_style_purpose', true), '')
                  AND g.revoked_at IS NULL
                  AND (g.expires_at IS NULL OR g.expires_at > clock_timestamp())
                  AND writing_style_profiles.state = 'published'
            )
        )
    );

CREATE POLICY writing_style_revisions_principal_select
    ON public.writing_style_revisions FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.writing_style_profiles p
            WHERE p.tenant_id = writing_style_revisions.tenant_id
              AND p.profile_id = writing_style_revisions.profile_id
              AND (
                  p.owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                  OR (
                      p.state = 'published'
                      AND p.current_revision_id = writing_style_revisions.revision_id
                  )
              )
        )
    );

-- Mutation policies additionally bind the owner to the authenticated
-- principal; passing a forged actor UUID as an SQL argument cannot suffice.
CREATE POLICY writing_style_profiles_owner_insert
    ON public.writing_style_profiles FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY writing_style_profiles_owner_update
    ON public.writing_style_profiles FOR UPDATE
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY writing_style_revisions_owner_insert
    ON public.writing_style_revisions FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND approved_by = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.writing_style_profiles p
            WHERE p.tenant_id = writing_style_revisions.tenant_id
              AND p.profile_id = writing_style_revisions.profile_id
              AND p.owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
    );

CREATE POLICY writing_style_grants_owner_insert
    ON public.writing_style_grants FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND granted_by = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY writing_style_grants_owner_update
    ON public.writing_style_grants FOR UPDATE
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND granted_by = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY writing_style_audit_owner_select
    ON public.writing_style_audit FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY writing_style_audit_owner_insert
    ON public.writing_style_audit FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.writing_style_profiles p
            WHERE p.tenant_id = writing_style_audit.tenant_id
              AND p.profile_id = writing_style_audit.profile_id
              AND p.owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
    );

COMMENT ON TABLE public.writing_style_profiles IS 'Tenant-scoped communication identities; no private sample bodies.';
COMMENT ON TABLE public.writing_style_revisions IS 'Immutable, bounded, expression-only published revision snapshots.';
COMMENT ON TABLE public.writing_style_grants IS 'Explicit actor and purpose use grants; not a replacement for RuntimePolicy.';
COMMENT ON TABLE public.writing_style_audit IS 'Value-free mutation receipts tied to identity lifecycle.';
COMMIT;
