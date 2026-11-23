-- WS-04B4: repair existing document-consent validation against canonical files schema.
-- public.files.tenant_id is TEXT in the core artifact table; writing style
-- tenant IDs are UUID. Cast the governed UUID to text (never cast arbitrary
-- file metadata to UUID), preserving the original RLS, owner, digest,
-- attestation, expiry and one-way revocation checks. Forward-only migration:
-- do not rewrite the already-deployed WS-04A9 receipt ledger.
BEGIN;

CREATE OR REPLACE FUNCTION public.writing_style_document_consent_validate()
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
      AND f.tenant_id = NEW.tenant_id::text
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

COMMIT;
