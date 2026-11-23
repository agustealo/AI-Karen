-- WS-04B5: current document authority at SQL grant/publication and file mutation.
-- Depends on 60/61/62/69. Never activates consumer document ingestion.
-- All new use decisions remain inside PostgreSQL's existing profile/receipt
-- owners. No private receipt rows become visible to delegated users.
BEGIN;

-- This owner-scoped, RLS-respecting helper is the sole document-use predicate
-- shared by the existing publication and grant triggers. No permissions are
-- inferred from file ownership. No document receipts or source bytes escape.
CREATE FUNCTION public.writing_style_document_use_expiry(
    p_tenant uuid, p_profile uuid, p_owner uuid
) RETURNS timestamptz
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $style_document_use_expiry$
DECLARE
    receipts_usable boolean;
    earliest_expiry timestamptz;
BEGIN
    SELECT bool_and(
        c.analysis_allowed IS TRUE
        AND c.style_use_allowed IS TRUE
        AND c.author_attested IS TRUE
        AND c.author_actor_id = p_owner
        AND c.revoked_at IS NULL
        AND c.expires_at > clock_timestamp()
        AND f.file_id IS NOT NULL
    ), min(c.expires_at)
    INTO receipts_usable, earliest_expiry
    FROM public.writing_style_document_consents c
    LEFT JOIN public.files f
        ON f.file_id = c.artifact_id::text
        AND f.tenant_id = c.tenant_id::text
        AND f.owner_user_id = c.author_actor_id
        AND f.sha256 = c.source_sha256
        AND f.deleted_at IS NULL
        AND f.mime_type = 'text/plain'
        AND f.bytes BETWEEN 1 AND 65536
    WHERE c.tenant_id = p_tenant
      AND c.profile_id = p_profile
      AND c.owner_actor_id = p_owner;

    IF receipts_usable IS FALSE THEN
        RAISE EXCEPTION 'writing style source use consent unavailable';
    END IF;

    -- A document sample's asserted receipt is not authority by itself.
    -- Require an exact first-party receipt and active canonical file for
    -- every attached document evidence row, even on direct owner SQL.
    IF EXISTS (
        SELECT 1 FROM public.writing_style_sample_evidence s
        WHERE s.tenant_id = p_tenant
          AND s.profile_id = p_profile
          AND s.owner_actor_id = p_owner
          AND s.source_type = 'document'
          AND NOT EXISTS (
              SELECT 1
              FROM public.writing_style_document_consents c
              JOIN public.files f
                ON f.file_id = c.artifact_id::text
               AND f.tenant_id = c.tenant_id::text
               AND f.owner_user_id = c.author_actor_id
               AND f.sha256 = c.source_sha256
               AND f.deleted_at IS NULL
               AND f.mime_type = 'text/plain'
               AND f.bytes BETWEEN 1 AND 65536
              WHERE c.tenant_id = s.tenant_id
                AND c.profile_id = s.profile_id
                AND c.owner_actor_id = s.owner_actor_id
                AND c.artifact_id = s.source_id
                AND c.receipt_id = s.consent_receipt_id
                AND c.author_actor_id = s.source_author_id
                AND c.analysis_allowed IS TRUE
                AND c.style_use_allowed IS TRUE
                AND c.author_attested IS TRUE
                AND c.revoked_at IS NULL
                AND c.expires_at > clock_timestamp()
          )
    ) THEN
        RAISE EXCEPTION 'writing style source use consent unavailable';
    END IF;
    RETURN earliest_expiry;
END
$style_document_use_expiry$;

-- Replace, do not duplicate, the existing DB owner for publication checks.
CREATE OR REPLACE FUNCTION public.writing_style_require_source_use_consent()
RETURNS trigger LANGUAGE plpgsql AS $style_publish_consent$
BEGIN
    IF NEW.state = 'published' AND EXISTS (
        SELECT 1 FROM public.writing_style_sample_evidence s
        WHERE s.tenant_id = NEW.tenant_id
          AND s.profile_id = NEW.profile_id
          AND (
              s.revoked_at IS NOT NULL
              OR s.style_use_allowed IS NOT TRUE
              OR (s.consent_expires_at IS NOT NULL
                  AND s.consent_expires_at <= clock_timestamp())
          )
    ) THEN
        RAISE EXCEPTION 'writing style source use consent unavailable';
    END IF;
    -- Profile publication must use the same current document-consent
    -- authority as owner grants, including attached document sample receipts.
    IF NEW.state = 'published' THEN
        PERFORM public.writing_style_document_use_expiry(
            NEW.tenant_id, NEW.profile_id, NEW.owner_actor_id
        );
    END IF;
    RETURN NEW;
END
$style_publish_consent$;

-- Replace, do not duplicate, the existing owner-scope grant trigger.
-- The active-grant UPDATE lock order remains unchanged.
CREATE OR REPLACE FUNCTION public.writing_style_bound_grant_to_source_consent()
RETURNS trigger LANGUAGE plpgsql AS $style_grant_consent$
DECLARE
    minimum_expiry timestamptz;
    all_usable boolean;
    document_expiry timestamptz;
BEGIN
    -- Re-granting an owner-revoked purpose is allowed only while the parent
    -- remains published and current source consent is valid. The checks below
    -- apply to both new grants and reactivated existing rows.

    -- Revocation must be allowed when the profile was already revoked.
    IF NEW.revoked_at IS NOT NULL THEN
        RETURN NEW;
    END IF;

    -- Grant UPDATE has already locked its own row before BEFORE UPDATE runs.
    -- Taking a profile FOR UPDATE here would invert the profile-then-grant
    -- order used by revocation and create a deadlock. Active grant updates
    -- only read the parent; parent revocation updates all grants and wins at
    -- the grant-row serialization boundary. New INSERT acquires the parent
    -- lock before any grant row exists.
    IF TG_OP = 'INSERT' THEN
        PERFORM 1 FROM public.writing_style_profiles p
        WHERE p.tenant_id = NEW.tenant_id
          AND p.profile_id = NEW.profile_id
          AND p.owner_actor_id = NEW.owner_actor_id
          AND p.state = 'published'
        FOR UPDATE;
    ELSE
        PERFORM 1 FROM public.writing_style_profiles p
        WHERE p.tenant_id = NEW.tenant_id
          AND p.profile_id = NEW.profile_id
          AND p.owner_actor_id = NEW.owner_actor_id
          AND p.state = 'published';
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'writing style grant unavailable';
    END IF;

    SELECT min(s.consent_expires_at),
           bool_and(s.style_use_allowed AND s.revoked_at IS NULL
               AND (s.consent_expires_at IS NULL
                    OR s.consent_expires_at > clock_timestamp()))
      INTO minimum_expiry, all_usable
    FROM public.writing_style_sample_evidence s
    WHERE s.tenant_id = NEW.tenant_id
      AND s.profile_id = NEW.profile_id;

    IF all_usable IS FALSE THEN
        RAISE EXCEPTION 'writing style source use consent unavailable';
    END IF;

    IF minimum_expiry IS NOT NULL AND (
        NEW.expires_at IS NULL OR NEW.expires_at > minimum_expiry
    ) THEN
        NEW.expires_at := minimum_expiry;
    END IF;
    -- Direct INSERT/UPDATE must not bypass the author-attested receipt.
    -- The helper is SECURITY INVOKER and executes under the same owner RLS
    -- that guards this grant mutation; it never exposes receipt metadata.
    document_expiry := public.writing_style_document_use_expiry(
        NEW.tenant_id, NEW.profile_id, NEW.owner_actor_id
    );
    IF document_expiry IS NOT NULL AND (
        NEW.expires_at IS NULL OR NEW.expires_at > document_expiry
    ) THEN
        NEW.expires_at := document_expiry;
    END IF;
    RETURN NEW;
END
$style_grant_consent$;

-- File mutation must revoke consent irreversibly. This privileged trigger
-- deliberately reuses writing_style_document_consent_revoke_fence, which
-- atomically revokes published/draft parent profiles and all delegated grants.
-- The canonical files table has no style-specific permission registry.
-- SECURITY DEFINER is required because file actors and service roles are not
-- entitled to modify the owner's private consent rows. FORCE RLS remains on;
-- row_security=off fails closed if migration ownership lacks BYPASSRLS.
CREATE FUNCTION public.writing_style_revoke_consent_on_file_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = off
AS $style_file_mutation_revoke$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.file_id, NEW.tenant_id, NEW.owner_user_id, NEW.name,
               NEW.mime_type, NEW.bytes, NEW.sha256, NEW.storage_uri,
               NEW.deleted_at)
           IS NOT DISTINCT FROM
           ROW(OLD.file_id, OLD.tenant_id, OLD.owner_user_id, OLD.name,
               OLD.mime_type, OLD.bytes, OLD.sha256, OLD.storage_uri,
               OLD.deleted_at) THEN
            RETURN NEW;
        END IF;
    END IF;

    UPDATE public.writing_style_document_consents c
       SET revoked_at = clock_timestamp()
     WHERE c.artifact_id::text = OLD.file_id
       AND c.tenant_id::text = OLD.tenant_id
       AND c.author_actor_id = OLD.owner_user_id
       AND c.revoked_at IS NULL;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$style_file_mutation_revoke$;

CREATE TRIGGER writing_style_file_change_revokes_document_consent
AFTER UPDATE OF file_id, tenant_id, owner_user_id, name, mime_type, bytes,
                sha256, storage_uri, deleted_at OR DELETE
ON public.files
FOR EACH ROW EXECUTE FUNCTION public.writing_style_revoke_consent_on_file_change();

REVOKE ALL ON FUNCTION public.writing_style_revoke_consent_on_file_change()
FROM PUBLIC;

-- Reconcile previously granted profiles on installation. Existing receipt
-- metadata might already have drifted before this trigger was installed.
UPDATE public.writing_style_document_consents c
SET revoked_at = clock_timestamp()
WHERE c.revoked_at IS NULL
  AND (
      c.expires_at <= clock_timestamp()
      OR (
          c.style_use_allowed IS NOT TRUE
          AND EXISTS (
              SELECT 1 FROM public.writing_style_profiles p
              WHERE p.tenant_id = c.tenant_id
                AND p.profile_id = c.profile_id
                AND p.state = 'published'
          )
      )
      OR NOT EXISTS (
          SELECT 1 FROM public.files f
          WHERE f.file_id = c.artifact_id::text
            AND f.tenant_id = c.tenant_id::text
            AND f.owner_user_id = c.author_actor_id
            AND f.sha256 = c.source_sha256
            AND f.deleted_at IS NULL
            AND f.mime_type = 'text/plain'
            AND f.bytes BETWEEN 1 AND 65536
      )
  );

-- Direct-SQL document sample references without matching current receipts
-- must never preserve previously published style use on migration install.
-- Existing sample revocation trigger revokes any published parent and grants.
UPDATE public.writing_style_sample_evidence s
SET revoked_at = clock_timestamp()
WHERE s.source_type = 'document'
  AND s.revoked_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM public.writing_style_document_consents c
      JOIN public.files f
        ON f.file_id = c.artifact_id::text
       AND f.tenant_id = c.tenant_id::text
       AND f.owner_user_id = c.author_actor_id
       AND f.sha256 = c.source_sha256
       AND f.deleted_at IS NULL
       AND f.mime_type = 'text/plain'
       AND f.bytes BETWEEN 1 AND 65536
      WHERE c.tenant_id = s.tenant_id
        AND c.profile_id = s.profile_id
        AND c.owner_actor_id = s.owner_actor_id
        AND c.artifact_id = s.source_id
        AND c.receipt_id = s.consent_receipt_id
        AND c.author_actor_id = s.source_author_id
        AND c.analysis_allowed IS TRUE
        AND c.style_use_allowed IS TRUE
        AND c.author_attested IS TRUE
        AND c.revoked_at IS NULL
        AND c.expires_at > clock_timestamp()
  );

-- Any pre-existing direct SQL grant with no expiry must now be bounded to
-- the earliest valid document receipt. The BEFORE UPDATE gate also proves
-- current sample/doc consent before accepting the corrected lease.
UPDATE public.writing_style_grants g
SET expires_at = receipts.expires_at
FROM (
    SELECT c.tenant_id, c.profile_id, c.owner_actor_id,
           min(c.expires_at) AS expires_at
    FROM public.writing_style_document_consents c
    WHERE c.revoked_at IS NULL
    GROUP BY c.tenant_id, c.profile_id, c.owner_actor_id
) receipts
WHERE g.tenant_id = receipts.tenant_id
  AND g.profile_id = receipts.profile_id
  AND g.owner_actor_id = receipts.owner_actor_id
  AND g.revoked_at IS NULL
  AND (g.expires_at IS NULL OR g.expires_at > receipts.expires_at);

COMMENT ON FUNCTION public.writing_style_document_use_expiry(uuid, uuid, uuid) IS
'Owner RLS-scoped current document consent check for canonical profile publication and grant triggers.';
COMMENT ON FUNCTION public.writing_style_revoke_consent_on_file_change() IS
'Internal privileged metadata drift fence; revokes immutable author consent via the existing profile/grant lifecycle.';
COMMIT;
