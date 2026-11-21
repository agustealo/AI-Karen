-- WS-04A9A: independently issued, first-party document author-consent ledger.
-- This migration does not expose an API or activate writing-style ingestion.
-- Artifact ownership is a necessary eligibility check, NOT proof of third-party authorship.
-- First-party author attestations must originate from authenticated runtime policy.
BEGIN;

CREATE TABLE public.writing_style_document_consents (
    tenant_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    owner_actor_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    author_actor_id uuid NOT NULL,
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    receipt_id uuid NOT NULL,
    analysis_allowed boolean NOT NULL CHECK (analysis_allowed),
    style_use_allowed boolean NOT NULL DEFAULT false,
    author_attested boolean NOT NULL CHECK (author_attested),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    correlation_id varchar(128) NOT NULL CHECK (length(trim(correlation_id)) BETWEEN 1 AND 128),
    PRIMARY KEY (tenant_id, profile_id, artifact_id),
    UNIQUE (tenant_id, receipt_id),
    FOREIGN KEY (tenant_id, profile_id, owner_actor_id)
        REFERENCES public.writing_style_profiles (tenant_id, profile_id, owner_actor_id)
        ON DELETE CASCADE,
    CHECK (author_actor_id = owner_actor_id),
    CHECK (expires_at > issued_at)
);

CREATE INDEX writing_style_document_consents_current_idx
    ON public.writing_style_document_consents (tenant_id, owner_actor_id, profile_id)
    WHERE revoked_at IS NULL;

-- A future authenticated consent issuer must call INSERT only after RuntimePolicy
-- authorizes the action and verifies the author's first-party attestation.
-- DB enforcement rejects request metadata pretending to be another author.
CREATE FUNCTION public.writing_style_document_consent_validate()
RETURNS trigger LANGUAGE plpgsql AS $ws_document_consent_validate$
DECLARE
    matched_file boolean;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.tenant_id, NEW.profile_id, NEW.owner_actor_id,
               NEW.artifact_id, NEW.author_actor_id, NEW.source_sha256,
               NEW.receipt_id, NEW.analysis_allowed, NEW.style_use_allowed,
               NEW.author_attested, NEW.expires_at, NEW.issued_at,
               NEW.correlation_id)
           IS DISTINCT FROM
           ROW(OLD.tenant_id, OLD.profile_id, OLD.owner_actor_id,
               OLD.artifact_id, OLD.author_actor_id, OLD.source_sha256,
               OLD.receipt_id, OLD.analysis_allowed, OLD.style_use_allowed,
               OLD.author_attested, OLD.expires_at, OLD.issued_at,
               OLD.correlation_id)
           OR OLD.revoked_at IS NOT NULL
           OR NEW.revoked_at IS NULL THEN
            RAISE EXCEPTION 'document style consent is immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.author_actor_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_user_id', true), '')::uuid
       OR NEW.owner_actor_id IS DISTINCT FROM NEW.author_actor_id
       OR NEW.tenant_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       OR NEW.author_attested IS NOT TRUE
       OR NEW.analysis_allowed IS NOT TRUE
       OR NEW.expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'document style consent denied';
    END IF;

    -- Source owner, revision, and archive state are checked on the actual
    -- canonical artifact row, not in user-controlled metadata.
    SELECT TRUE INTO matched_file
    FROM public.files f
    WHERE f.file_id = NEW.artifact_id::text
      AND f.tenant_id = NEW.tenant_id
      AND f.owner_user_id = NEW.author_actor_id
      AND f.deleted_at IS NULL
      AND f.sha256 = NEW.source_sha256
      AND f.mime_type = 'text/plain'
      AND f.bytes BETWEEN 1 AND 65536
    FOR SHARE;

    IF matched_file IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'document style consent source unavailable';
    END IF;
    RETURN NEW;
END
$ws_document_consent_validate$;

CREATE TRIGGER writing_style_document_consent_validate_insert
    BEFORE INSERT ON public.writing_style_document_consents
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_document_consent_validate();

CREATE TRIGGER writing_style_document_consent_revoke_only
    BEFORE UPDATE ON public.writing_style_document_consents
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_document_consent_validate();

-- Do not allow an owner to rewrite receipt identity, source revision, or purpose.
-- After revocation, the published profile and delegates are fenced in the same
-- transaction; the existing profile lifecycle remains authoritative.
CREATE FUNCTION public.writing_style_document_consent_revoke_fence()
RETURNS trigger LANGUAGE plpgsql AS $ws_document_consent_revoke$
DECLARE
    active_revision bigint;
BEGIN
    IF NEW.revoked_at IS NULL OR OLD.revoked_at IS NOT NULL THEN
        RETURN NEW;
    END IF;

    UPDATE public.writing_style_profiles p
    SET state = 'revoked', updated_at = clock_timestamp()
    WHERE p.tenant_id = NEW.tenant_id
      AND p.profile_id = NEW.profile_id
      AND p.owner_actor_id = NEW.owner_actor_id
      AND p.state = 'published'
    RETURNING p.publication_revision INTO active_revision;

    IF FOUND THEN
        UPDATE public.writing_style_grants g
        SET revoked_at = clock_timestamp()
        WHERE g.tenant_id = NEW.tenant_id
          AND g.profile_id = NEW.profile_id
          AND g.owner_actor_id = NEW.owner_actor_id
          AND g.revoked_at IS NULL;

        INSERT INTO public.writing_style_audit
            (tenant_id, profile_id, actor_id, action, publication_revision, correlation_id)
        VALUES (NEW.tenant_id, NEW.profile_id, NEW.owner_actor_id,
                'revoke_profile', active_revision, NEW.correlation_id);
    END IF;
    RETURN NEW;
END
$ws_document_consent_revoke$;

CREATE TRIGGER writing_style_document_consent_revoke_fence
    AFTER UPDATE OF revoked_at ON public.writing_style_document_consents
    FOR EACH ROW EXECUTE FUNCTION public.writing_style_document_consent_revoke_fence();

REVOKE ALL ON public.writing_style_document_consents FROM PUBLIC;
DO $ws_document_consent_roles$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL ON public.writing_style_document_consents FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END
$ws_document_consent_roles$;

ALTER TABLE public.writing_style_document_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.writing_style_document_consents FORCE ROW LEVEL SECURITY;

CREATE POLICY writing_style_document_consent_owner_select
ON public.writing_style_document_consents FOR SELECT USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
);
CREATE POLICY writing_style_document_consent_author_insert
ON public.writing_style_document_consents FOR INSERT WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    AND author_actor_id = owner_actor_id AND author_attested IS TRUE
);
CREATE POLICY writing_style_document_consent_author_revoke
ON public.writing_style_document_consents FOR UPDATE USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
) WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND owner_actor_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
);

COMMENT ON TABLE public.writing_style_document_consents IS
    'First-party author-attested consent receipts only; no source text or implied permission from ownership. Runtime issuer/consumer inactive pending live proof.';
COMMIT;
