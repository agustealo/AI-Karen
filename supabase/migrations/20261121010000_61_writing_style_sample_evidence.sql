-- WS-02B: sample metadata and source-consent lineage, never raw writing content.
-- Depends on WS-02A migration 20261120235900_60_writing_style_identity.sql.
BEGIN;

CREATE TABLE public.writing_style_sample_evidence (
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    owner_actor_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    source_type varchar(24) NOT NULL
        CHECK (source_type IN ('document', 'message', 'email', 'transcript')),
    source_id uuid NOT NULL,
    source_author_id uuid NOT NULL,
    consent_receipt_id uuid NOT NULL,
    analysis_allowed boolean NOT NULL CHECK (analysis_allowed),
    style_use_allowed boolean NOT NULL DEFAULT false,
    consent_expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, profile_id, sample_id),
    UNIQUE (tenant_id, profile_id, source_type, source_id),
    FOREIGN KEY (tenant_id, profile_id, owner_actor_id)
        REFERENCES public.writing_style_profiles
            (tenant_id, profile_id, owner_actor_id) ON DELETE CASCADE
);

CREATE TABLE public.writing_style_sample_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    owner_actor_id uuid NOT NULL,
    action varchar(20) NOT NULL CHECK (action IN ('register', 'revoke')),
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, profile_id, sample_id)
        REFERENCES public.writing_style_sample_evidence
            (tenant_id, profile_id, sample_id) ON DELETE CASCADE
);

CREATE INDEX writing_style_sample_source_idx ON public.writing_style_sample_evidence
    (tenant_id, source_type, source_id) WHERE revoked_at IS NULL;

-- Preserve provenance fields, consent receipt and author identity. The sole
-- permitted in-place change is a one-way revocation timestamp.
CREATE FUNCTION public.writing_style_sample_revoke_only()
RETURNS trigger LANGUAGE plpgsql AS $writing_sample_immutable$
BEGIN
    IF ROW(NEW.tenant_id, NEW.profile_id, NEW.owner_actor_id, NEW.sample_id,
        NEW.source_type, NEW.source_id, NEW.source_author_id,
        NEW.consent_receipt_id, NEW.analysis_allowed, NEW.style_use_allowed,
        NEW.consent_expires_at, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.tenant_id, OLD.profile_id, OLD.owner_actor_id, OLD.sample_id,
        OLD.source_type, OLD.source_id, OLD.source_author_id,
        OLD.consent_receipt_id, OLD.analysis_allowed, OLD.style_use_allowed,
        OLD.consent_expires_at, OLD.created_at)
       OR OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL
    THEN
        RAISE EXCEPTION 'writing style sample evidence is immutable';
    END IF;
    RETURN NEW;
END
$writing_sample_immutable$;
CREATE TRIGGER writing_style_sample_revoke_only
    BEFORE UPDATE ON public.writing_style_sample_evidence
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_sample_revoke_only();

REVOKE ALL ON public.writing_style_sample_evidence,
    public.writing_style_sample_audit FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.writing_style_sample_audit_id_seq FROM PUBLIC;

DO $writing_sample_revoke_roles$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON public.writing_style_sample_evidence, public.writing_style_sample_audit FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON SEQUENCE public.writing_style_sample_audit_id_seq FROM %I', role_name);
        END IF;
    END LOOP;
END
$writing_sample_revoke_roles$;

ALTER TABLE public.writing_style_sample_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_sample_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_sample_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_sample_audit FORCE ROW LEVEL SECURITY;

-- Evidence metadata is visible only to its owner, never to a style-use delegate.
CREATE POLICY writing_style_sample_owner_select
    ON public.writing_style_sample_evidence FOR SELECT USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY writing_style_sample_owner_insert
    ON public.writing_style_sample_evidence FOR INSERT WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND analysis_allowed = true
    );
CREATE POLICY writing_style_sample_owner_update
    ON public.writing_style_sample_evidence FOR UPDATE
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY writing_style_sample_audit_owner_select
    ON public.writing_style_sample_audit FOR SELECT USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY writing_style_sample_audit_owner_insert
    ON public.writing_style_sample_audit FOR INSERT WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

COMMENT ON TABLE public.writing_style_sample_evidence IS
    'Opaque, consent-backed sample source references only; raw content remains in the canonical source owner.';
COMMENT ON TABLE public.writing_style_sample_audit IS
    'Value-free sample registration and revocation receipts; no uploaded content.';
COMMIT;
