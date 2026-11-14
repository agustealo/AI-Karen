-- KOC-05/KOC-07: protect the canonical personal credential-deletion ledger.
-- An authenticated provider claim is NOT independent erasure verification.
-- Until a separately governed verifier exists, no SQL insert/update can mint
-- new "verified" evidence, even through a superuser-owned application path.
-- Existing historical rows are preserved, not silently rewritten.
BEGIN;

CREATE OR REPLACE FUNCTION public.channel_personal_deletion_evidence_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $channel_deletion$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Canonical request creation only; migration/import of historical
        -- statuses requires an explicitly privileged recovery procedure.
        IF NEW.status <> 'requested' OR NEW.provider_receipt_id IS NOT NULL THEN
            RAISE EXCEPTION 'Personal credential deletion evidence must begin as requested'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    -- An existing request's identity, scope, revision, creation timestamp and
    -- idempotency key must not drift after issuance. Account/tenant erasure is
    -- handled by existing ON DELETE CASCADE FKs, not UPDATE or this trigger.
    IF ROW(
        NEW.tenant_id, NEW.request_id, NEW.connection_id, NEW.provider_id,
        NEW.user_id, NEW.connection_revision, NEW.session_reference,
        NEW.credential_scope, NEW.idempotency_key, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.tenant_id, OLD.request_id, OLD.connection_id, OLD.provider_id,
        OLD.user_id, OLD.connection_revision, OLD.session_reference,
        OLD.credential_scope, OLD.idempotency_key, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Personal credential deletion request scope is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.provider_receipt_id IS NOT NULL
       AND NEW.provider_receipt_id IS DISTINCT FROM OLD.provider_receipt_id THEN
        RAISE EXCEPTION 'Personal credential deletion provider receipt is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.provider_receipt_id IS NULL
       AND NEW.provider_receipt_id IS NOT NULL
       AND NEW.status <> 'provider_claimed' THEN
        RAISE EXCEPTION 'Provider receipt requires a provider claim transition'
            USING ERRCODE = '23514';
    END IF;

    -- Prior historical "verified" records may remain legible and retain their
    -- original status. This does NOT attest their independent validity.
    -- No transition or new row may assert verified until a vetted independent
    -- verification contract, permissions and evidence exist.
    IF NEW.status = 'verified' AND OLD.status <> 'verified' THEN
        RAISE EXCEPTION 'Independent credential erasure verification is unavailable'
            USING ERRCODE = '23514';
    END IF;

    IF NOT (
        (OLD.status = 'requested'
         AND NEW.status IN ('requested', 'provider_pending', 'provider_claimed', 'unknown'))
        OR (OLD.status = 'provider_pending'
            AND NEW.status IN ('provider_pending', 'provider_claimed', 'unknown'))
        OR (OLD.status = 'provider_claimed'
            AND NEW.status IN ('provider_claimed', 'verification_pending', 'unknown'))
        OR (OLD.status = 'verification_pending'
            AND NEW.status IN ('verification_pending', 'unknown'))
        OR (OLD.status = 'unknown' AND NEW.status = 'unknown')
        OR (OLD.status = 'verified' AND NEW.status = 'verified')
    ) THEN
        RAISE EXCEPTION 'Personal credential deletion transition is not allowed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$channel_deletion$;

CREATE TRIGGER channel_personal_deletion_evidence_guard
BEFORE INSERT OR UPDATE ON public.channel_personal_credential_deletions
FOR EACH ROW
EXECUTE FUNCTION public.channel_personal_deletion_evidence_guard();

COMMENT ON FUNCTION public.channel_personal_deletion_evidence_guard() IS
    'Host ledger integrity: immutable deletion request scope and provider claims; no unverified transition to verified. Privileged restore requires a separately reviewed procedure.';
COMMIT;
