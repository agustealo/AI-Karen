-- WS-02: Host-owned, consent-gated KariSignature published expression read model.
-- This is a forward-only private data contract. It does NOT implement an
-- ingestion or publication API or make any writing style available to users.
BEGIN;

CREATE TABLE public.karisignature_profiles (
    profile_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    owner_user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    purpose varchar(48) NOT NULL,
    state varchar(16) NOT NULL DEFAULT 'draft',
    consent_state varchar(16) NOT NULL DEFAULT 'pending',
    current_revision_id uuid,
    revision_counter bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT kari_profile_scope UNIQUE (profile_id, tenant_id, owner_user_id),
    CONSTRAINT kari_profile_purpose CHECK (purpose ~ '^[a-z][a-z0-9_-]{0,47}$'),
    CONSTRAINT kari_profile_state CHECK (state IN ('draft', 'published', 'suspended', 'archived')),
    CONSTRAINT kari_profile_consent CHECK (consent_state IN ('pending', 'granted', 'revoked')),
    CONSTRAINT kari_profile_revision_counter CHECK (revision_counter >= 0),
    CONSTRAINT kari_profile_current_state CHECK (
        (state = 'published' AND consent_state = 'granted'
            AND current_revision_id IS NOT NULL AND revision_counter > 0)
        OR (state <> 'published')
    )
);

CREATE TABLE public.karisignature_revisions (
    revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    revision_number bigint NOT NULL,
    state varchar(16) NOT NULL DEFAULT 'published',
    approved_expression jsonb NOT NULL,
    content_digest char(64) NOT NULL,
    published_by uuid NOT NULL REFERENCES public.auth_users(user_id),
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT kari_revision_profile_fk FOREIGN KEY (
        profile_id, tenant_id, owner_user_id
    ) REFERENCES public.karisignature_profiles (
        profile_id, tenant_id, owner_user_id
    ) ON DELETE CASCADE,
    CONSTRAINT kari_revision_number_unique UNIQUE (profile_id, revision_number),
    CONSTRAINT kari_revision_composite_unique UNIQUE (profile_id, revision_id),
    CONSTRAINT kari_revision_number_valid CHECK (revision_number >= 1),
    CONSTRAINT kari_revision_state CHECK (state = 'published'),
    CONSTRAINT kari_revision_digest CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT kari_revision_expression CHECK (
        jsonb_typeof(approved_expression) = 'object'
        AND jsonb_object_length(approved_expression) BETWEEN 1 AND 5
        AND octet_length(approved_expression::text) <= 1024
    )
);

ALTER TABLE public.karisignature_profiles
    ADD CONSTRAINT kari_profile_current_revision_fk
    FOREIGN KEY (profile_id, current_revision_id)
    REFERENCES public.karisignature_revisions (profile_id, revision_id)
    DEFERRABLE INITIALLY IMMEDIATE;

CREATE INDEX kari_profiles_owner_current
    ON public.karisignature_profiles (
        tenant_id, owner_user_id, purpose, state, consent_state
    );
CREATE INDEX kari_revisions_owner_timeline
    ON public.karisignature_revisions (
        tenant_id, owner_user_id, profile_id, revision_number DESC
    );

-- Published revisions are never edited in place. Authorized erasure can
-- cascade through the profile under the existing governed deletion owner.
CREATE FUNCTION public.prevent_karisignature_revision_update()
RETURNS trigger LANGUAGE plpgsql AS $kari_revision_immutable$
BEGIN
    RAISE EXCEPTION 'Published KariSignature revisions are immutable'
        USING ERRCODE = '55000';
END;
$kari_revision_immutable$;

CREATE TRIGGER kari_revision_immutable
    BEFORE UPDATE ON public.karisignature_revisions
    FOR EACH ROW EXECUTE FUNCTION public.prevent_karisignature_revision_update();

-- Both scopes must be set by canonical async_transaction_scope.
-- A tenant-only transaction is insufficient for any read or write.
ALTER TABLE public.karisignature_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.karisignature_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.karisignature_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.karisignature_revisions FORCE ROW LEVEL SECURITY;

CREATE POLICY kari_profile_owner_read
    ON public.karisignature_profiles FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY kari_revision_owner_read
    ON public.karisignature_revisions FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- No INSERT/UPDATE/DELETE RLS policy exists in WS-02. Publication, consent
-- and governed erasure must first receive a separate audited mutation owner.
REVOKE ALL ON public.karisignature_profiles FROM PUBLIC;
REVOKE ALL ON public.karisignature_revisions FROM PUBLIC;

DO $kari_revoke_client_roles$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format(
                'REVOKE ALL ON public.karisignature_profiles, '
                || 'public.karisignature_revisions FROM %I',
                client_role
            );
        END IF;
    END LOOP;
END;
$kari_revoke_client_roles$;

COMMENT ON TABLE public.karisignature_profiles IS
    'Owner-scoped communication identity admission state; consent and current revision are authoritative. No consumer API in WS-02.';
COMMENT ON TABLE public.karisignature_revisions IS
    'Immutable approved expression revisions. Raw samples and source documents are never stored in this read model.';

COMMIT;
