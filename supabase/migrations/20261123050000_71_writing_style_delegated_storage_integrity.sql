-- WS-04B7: server-only document identities for delegated-use byte attestation.
-- Reuse existing profile/grant/consent authorities. No new receipt store, ACL,
-- public RPC, document-text projection, or consumer ingestion activation.
BEGIN;

-- Never put a privileged private-receipt function in the Data API's public
-- schema. Only the trusted database runtime owner may access this schema.
CREATE SCHEMA IF NOT EXISTS kari_internal;
REVOKE ALL ON SCHEMA kari_internal FROM PUBLIC;

CREATE FUNCTION kari_internal.writing_style_authorized_document_sources(
    p_tenant uuid,
    p_profile uuid,
    p_actor uuid,
    p_purpose text,
    p_revision uuid,
    p_revision_number bigint,
    p_revision_digest text
)
RETURNS TABLE (
    artifact_id uuid,
    owner_actor_id uuid,
    source_sha256 text
)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = off
AS $kari_delegated_document_sources$
DECLARE
    source_owner uuid;
BEGIN
    -- app.current_* are bound to authenticated runtime context by the
    -- existing WritingStyleProfileRepository._scope. Caller arguments are
    -- never sufficient without that same connection-local principal.
    IF p_tenant IS DISTINCT FROM
         NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       OR p_actor IS DISTINCT FROM
         NULLIF(current_setting('app.current_user_id', true), '')::uuid
       OR p_purpose IS DISTINCT FROM
         NULLIF(current_setting('app.current_style_purpose', true), '')
       OR p_purpose !~ '^[a-z][a-z0-9_-]{0,47}$'
       OR p_revision_digest !~ '^[a-f0-9]{64}$'
       OR p_revision_number < 1 THEN
        RAISE EXCEPTION 'writing style source verification unavailable';
    END IF;

    -- The private owner cannot be supplied by the delegate. Reuse the
    -- canonical published revision plus unexpired purpose-specific grant,
    -- locking all rows against publication/grant changes during the bounded
    -- Storage verification. FORCE RLS is deliberately bypassed only inside
    -- this privileged internal function, never on the delegate's session.
    SELECT p.owner_actor_id
      INTO source_owner
      FROM public.writing_style_profiles p
      JOIN public.writing_style_revisions r
        ON r.tenant_id = p.tenant_id
       AND r.profile_id = p.profile_id
       AND r.revision_id = p.current_revision_id
      JOIN public.writing_style_grants g
        ON g.tenant_id = p.tenant_id
       AND g.profile_id = p.profile_id
       AND g.owner_actor_id = p.owner_actor_id
     WHERE p.tenant_id = p_tenant
       AND p.profile_id = p_profile
       AND p.state = 'published'
       AND r.revision_id = p_revision
       AND r.revision_number = p_revision_number
       AND r.content_digest = p_revision_digest
       AND g.actor_id = p_actor
       AND g.purpose = p_purpose
       AND g.revoked_at IS NULL
       AND (g.expires_at IS NULL OR g.expires_at > clock_timestamp())
     FOR SHARE OF p, r, g;

    IF source_owner IS NULL THEN
        RAISE EXCEPTION 'writing style source verification unavailable';
    END IF;

    -- Reuse the already-tested owner-only document receipt + sample
    -- reference validator, rather than creating an alternate permission
    -- algorithm. Under this SECURITY DEFINER owner it can inspect private
    -- author receipts without granting the delegate any table privileges.
    PERFORM public.writing_style_document_use_expiry(
        p_tenant, p_profile, source_owner
    );

    -- A successful empty result means a valid manually authored profile.
    -- Every document-backed profile yields every current author receipt.
    -- These identities exist only inside the trusted host and are never
    -- surfaced to the delegate, prompt, tool or UI.
    RETURN QUERY
    SELECT c.artifact_id, c.author_actor_id,
           btrim(c.source_sha256)::text
      FROM public.writing_style_document_consents c
      JOIN public.files f
        ON f.file_id = c.artifact_id::text
       AND f.tenant_id = c.tenant_id
       AND f.owner_user_id = c.author_actor_id
       AND f.sha256 = c.source_sha256
       AND f.deleted_at IS NULL
       AND f.mime_type = 'text/plain'
       AND f.bytes BETWEEN 1 AND 65536
     WHERE c.tenant_id = p_tenant
       AND c.profile_id = p_profile
       AND c.owner_actor_id = source_owner
       AND c.author_actor_id = source_owner
       AND c.analysis_allowed IS TRUE
       AND c.style_use_allowed IS TRUE
       AND c.author_attested IS TRUE
       AND c.revoked_at IS NULL
       AND c.expires_at > clock_timestamp()
     ORDER BY c.artifact_id
     FOR SHARE OF c, f;
END
$kari_delegated_document_sources$;

-- Functions otherwise default to EXECUTE for PUBLIC, including anonymous
-- Data API roles. No automatic grant is made to anon or authenticated.
REVOKE ALL ON FUNCTION kari_internal.writing_style_authorized_document_sources(
    uuid, uuid, uuid, text, uuid, bigint, text
) FROM PUBLIC;
DO $kari_private_revoke$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA kari_internal FROM %I', role_name);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION kari_internal.writing_style_authorized_document_sources(uuid, uuid, uuid, text, uuid, bigint, text) FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END
$kari_private_revoke$;

COMMENT ON FUNCTION kari_internal.writing_style_authorized_document_sources(
    uuid, uuid, uuid, text, uuid, bigint, text
) IS 'Internal, exact-grant and immutable-receipt verified source scopes for server-side bounded Storage integrity. Never Data API-exposed.';
COMMIT;
