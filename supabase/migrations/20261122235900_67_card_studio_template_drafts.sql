-- KGUI-CARD-STUDIO-01B: owner-scoped, immutable card-template drafts.
-- Backend-only persistence. No Data API grant, chat execution path, or
-- permission for model-supplied tenant/user identity is created here.
BEGIN;

CREATE TABLE public.card_studio_templates (
    template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    template_key VARCHAR(64) NOT NULL,
    head_revision BIGINT NOT NULL DEFAULT 1,
    lifecycle VARCHAR(16) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT card_studio_template_owner_unique
        UNIQUE (template_id, tenant_id, user_id),
    CONSTRAINT card_studio_template_slug_unique
        UNIQUE (tenant_id, user_id, template_key),
    CONSTRAINT card_studio_template_slug_safe
        CHECK (
            template_key ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'
            AND template_key NOT LIKE 'system-%'
        ),
    CONSTRAINT card_studio_template_revision_valid
        CHECK (head_revision BETWEEN 1 AND 9223372036854775805),
    CONSTRAINT card_studio_template_lifecycle_valid
        CHECK (lifecycle IN ('draft', 'archived'))
);

CREATE INDEX card_studio_template_owner_recent
    ON public.card_studio_templates
    (tenant_id, user_id, updated_at DESC, template_id DESC);

CREATE TABLE public.card_studio_template_revisions (
    template_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    revision BIGINT NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (template_id, revision),
    CONSTRAINT card_studio_revision_owner_fk
        FOREIGN KEY (template_id, tenant_id, user_id)
        REFERENCES public.card_studio_templates (template_id, tenant_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT card_studio_revision_valid
        CHECK (revision BETWEEN 1 AND 9223372036854775806),
    CONSTRAINT card_studio_revision_bounded
        CHECK (
            jsonb_typeof(definition) = 'object'
            AND octet_length(definition::text) <= 4096
        )
);

CREATE INDEX card_studio_revision_owner_history
    ON public.card_studio_template_revisions
    (tenant_id, user_id, template_id, revision DESC);

CREATE TABLE public.card_studio_template_mutation_receipts (
    receipt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    idempotency_key UUID NOT NULL,
    operation VARCHAR(12) NOT NULL,
    request_digest CHAR(64) NOT NULL,
    template_id UUID NOT NULL,
    committed_revision BIGINT NOT NULL,
    result_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT card_studio_receipt_owner_unique
        UNIQUE (tenant_id, user_id, idempotency_key),
    CONSTRAINT card_studio_receipt_template_fk
        FOREIGN KEY (template_id, tenant_id, user_id)
        REFERENCES public.card_studio_templates (template_id, tenant_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT card_studio_receipt_operation_valid
        CHECK (operation IN ('create', 'revise', 'archive')),
    CONSTRAINT card_studio_receipt_digest_valid
        CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT card_studio_receipt_revision_valid
        CHECK (committed_revision >= 1),
    CONSTRAINT card_studio_receipt_snapshot_bounded
        CHECK (
            jsonb_typeof(result_snapshot) = 'object'
            AND octet_length(result_snapshot::text) <= 6144
        )
);

CREATE INDEX card_studio_receipt_owner_recent
    ON public.card_studio_template_mutation_receipts
    (tenant_id, user_id, created_at DESC, receipt_id DESC);

-- The canonical server transaction sets both GUCs from the authenticated
-- principal, independent of all model/chat/template payloads.
ALTER TABLE public.card_studio_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card_studio_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY card_studio_template_owner ON public.card_studio_templates
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

ALTER TABLE public.card_studio_template_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card_studio_template_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY card_studio_revision_read ON public.card_studio_template_revisions
    FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY card_studio_revision_insert ON public.card_studio_template_revisions
    FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

ALTER TABLE public.card_studio_template_mutation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card_studio_template_mutation_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY card_studio_receipt_read ON public.card_studio_template_mutation_receipts
    FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY card_studio_receipt_insert ON public.card_studio_template_mutation_receipts
    FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- The stable parent may only be deleted by governed account/tenant erasure.
-- Ordinary template deletion must use a revision-checked soft archive, so it
-- cannot erase immutable history or ambiguous-response mutation receipts.
CREATE FUNCTION public.prevent_card_studio_template_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $immutable_card_studio_owner$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.tenants WHERE id = OLD.tenant_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.auth_users WHERE user_id = OLD.user_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Card Studio templates require soft archive'
        USING ERRCODE = '55000';
END;
$immutable_card_studio_owner$;

CREATE TRIGGER card_studio_template_soft_archive_only
    BEFORE DELETE ON public.card_studio_templates
    FOR EACH ROW EXECUTE FUNCTION public.prevent_card_studio_template_delete();

-- Version and receipt rows are immutable except governed parent deletion.
CREATE FUNCTION public.prevent_card_studio_history_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $immutable_card_studio$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM public.card_studio_templates
        WHERE template_id = OLD.template_id
          AND tenant_id = OLD.tenant_id
          AND user_id = OLD.user_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Card Studio committed history is immutable'
        USING ERRCODE = '55000';
END;
$immutable_card_studio$;

CREATE TRIGGER card_studio_revision_immutable
    BEFORE UPDATE OR DELETE ON public.card_studio_template_revisions
    FOR EACH ROW EXECUTE FUNCTION public.prevent_card_studio_history_mutation();
CREATE TRIGGER card_studio_receipt_immutable
    BEFORE UPDATE OR DELETE ON public.card_studio_template_mutation_receipts
    FOR EACH ROW EXECUTE FUNCTION public.prevent_card_studio_history_mutation();

REVOKE ALL ON public.card_studio_templates FROM PUBLIC;
REVOKE ALL ON public.card_studio_template_revisions FROM PUBLIC;
REVOKE ALL ON public.card_studio_template_mutation_receipts FROM PUBLIC;
DO $card_studio_client_revoke$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.card_studio_templates FROM anon;
        REVOKE ALL ON public.card_studio_template_revisions FROM anon;
        REVOKE ALL ON public.card_studio_template_mutation_receipts FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.card_studio_templates FROM authenticated;
        REVOKE ALL ON public.card_studio_template_revisions FROM authenticated;
        REVOKE ALL ON public.card_studio_template_mutation_receipts FROM authenticated;
    END IF;
END;
$card_studio_client_revoke$;

COMMENT ON TABLE public.card_studio_templates IS
    'Owned inert card-template metadata. No presentation content or execution authorization.';
COMMENT ON TABLE public.card_studio_template_revisions IS
    'Immutable owner-scoped declarative drafts. Source data is never stored as template data.';
COMMENT ON TABLE public.card_studio_template_mutation_receipts IS
    'Immutable idempotent mutation outcomes, created atomically with template changes.';

COMMIT;
