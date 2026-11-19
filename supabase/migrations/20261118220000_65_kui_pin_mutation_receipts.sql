-- KUI-002D3B1: immutable receipt evidence for presentation-pin mutations.
-- This ledger is part of the existing presentation-pin persistence authority.
-- The owning repository MUST insert a receipt in the SAME authenticated RLS
-- transaction as the corresponding pin mutation. This migration alone does
-- not authorize mutations, expose HTTP routes, or activate UI controls.
BEGIN;

CREATE TABLE public.conversation_presentation_pin_mutation_receipts (
    receipt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    request_id VARCHAR(160) NOT NULL,
    correlation_id VARCHAR(160) NOT NULL,
    request_digest CHAR(64) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    pin_id UUID,
    expected_revision BIGINT,
    committed_revision BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT conversation_pin_receipt_identity_unique
        UNIQUE (tenant_id, user_id, idempotency_key),
    CONSTRAINT conversation_pin_receipt_request_nonempty
        CHECK (length(btrim(request_id)) BETWEEN 1 AND 160),
    CONSTRAINT conversation_pin_receipt_correlation_nonempty
        CHECK (length(btrim(correlation_id)) BETWEEN 1 AND 160),
    CONSTRAINT conversation_pin_receipt_digest_format
        CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT conversation_pin_receipt_operation
        CHECK (operation IN ('pin', 'unpin', 'reorder')),
    CONSTRAINT conversation_pin_receipt_outcome
        CHECK (
            (operation = 'pin' AND outcome = 'pinned')
            OR (operation = 'unpin' AND outcome IN ('unpinned', 'already_absent'))
            OR (operation = 'reorder' AND outcome = 'reordered')
        ),
    CONSTRAINT conversation_pin_receipt_revision
        CHECK (
            (expected_revision IS NULL OR expected_revision >= 1)
            AND (committed_revision IS NULL OR committed_revision >= 1)
        ),
    CONSTRAINT conversation_pin_receipt_pin_identity
        CHECK (
            (outcome = 'already_absent' OR pin_id IS NOT NULL)
            AND (operation <> 'reorder' OR (
                expected_revision IS NOT NULL AND committed_revision IS NOT NULL
                AND committed_revision = expected_revision + 1
            ))
        )
);

-- Do not FK receipt pin_id to the mutable pin table: unpin and source-deletion
-- must not erase an already committed mutation receipt.
CREATE INDEX conversation_pin_receipts_owner_timeline
    ON public.conversation_presentation_pin_mutation_receipts
    (tenant_id, user_id, created_at DESC, receipt_id DESC);

ALTER TABLE public.conversation_presentation_pin_mutation_receipts
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_presentation_pin_mutation_receipts
    FORCE ROW LEVEL SECURITY;

CREATE POLICY conversation_pin_receipt_owner_read
    ON public.conversation_presentation_pin_mutation_receipts
    FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY conversation_pin_receipt_owner_insert
    ON public.conversation_presentation_pin_mutation_receipts
    FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- Even a table owner that acquires UPDATE/DELETE privileges must not mutate
-- committed receipts through an ordinary application SQL statement.
CREATE FUNCTION public.prevent_presentation_pin_receipt_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $immutable_pin_receipt$
BEGIN
    -- Parent-table FK cascades must remain possible for governed account and
    -- tenant erasure. PostgreSQL has already removed the parent row when its
    -- referential-action trigger deletes the dependent receipt. A direct
    -- receipt DELETE while the parent still exists remains prohibited.
    -- UPDATE is never permitted.
    IF TG_OP = 'DELETE' AND (
        NOT EXISTS (
            SELECT 1 FROM public.tenants WHERE id = OLD.tenant_id
        ) OR NOT EXISTS (
            SELECT 1 FROM public.auth_users WHERE user_id = OLD.user_id
        )
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Committed presentation pin receipt is immutable'
        USING ERRCODE = '55000';
END;
$immutable_pin_receipt$;

CREATE TRIGGER conversation_pin_receipt_immutable
    BEFORE UPDATE OR DELETE
    ON public.conversation_presentation_pin_mutation_receipts
    FOR EACH ROW EXECUTE FUNCTION public.prevent_presentation_pin_receipt_mutation();

REVOKE ALL ON public.conversation_presentation_pin_mutation_receipts FROM PUBLIC;
DO $revoke_pin_receipt_clients$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.conversation_presentation_pin_mutation_receipts FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.conversation_presentation_pin_mutation_receipts FROM authenticated;
    END IF;
END;
$revoke_pin_receipt_clients$;

COMMENT ON TABLE public.conversation_presentation_pin_mutation_receipts IS
    'Immutable per-principal mutation receipts. Written atomically by the existing presentation-pin repository, never an independent audit or execution authority.';

COMMIT;
