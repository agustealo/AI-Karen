-- KUI-002D2: durable reference-only pins for already attested, owned messages.
-- Neither the table nor its existence proves that a presentation is safe to pin.
-- Runtime must reauthorize every source and verify its completed-run digest.
-- No Data API access or frontend mutation is enabled by this migration.
BEGIN;

-- Tie the source message to its stated conversation, not merely to a
-- valid message UUID from another conversation.
ALTER TABLE public.messages
    ADD CONSTRAINT messages_conversation_message_unique
    UNIQUE (conversation_id, message_id);

-- Anchor tenant and user scope in the canonical conversation row. The
-- pinning user cannot redirect a reference to another owner's conversation.
ALTER TABLE public.conversations
    ADD CONSTRAINT conversations_scope_reference_unique
    UNIQUE (conversation_id, tenant_id, user_id);

CREATE TABLE public.conversation_presentation_pins (
    pin_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL,
    assistant_message_id UUID NOT NULL,
    presentation_id VARCHAR(160) NOT NULL,
    evidence_ref VARCHAR(160) NOT NULL,
    position SMALLINT NOT NULL DEFAULT 0,
    revision BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT conversation_presentation_pin_owner_fk
        FOREIGN KEY (conversation_id, tenant_id, user_id)
        REFERENCES public.conversations(conversation_id, tenant_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT conversation_presentation_pin_message_fk
        FOREIGN KEY (conversation_id, assistant_message_id)
        REFERENCES public.messages(conversation_id, message_id)
        ON DELETE CASCADE,
    CONSTRAINT conversation_presentation_pin_origin_unique
        UNIQUE (tenant_id, user_id, conversation_id, assistant_message_id, presentation_id),
    CONSTRAINT conversation_presentation_pin_presentation_id_check
        CHECK (length(btrim(presentation_id)) BETWEEN 1 AND 160),
    CONSTRAINT conversation_presentation_pin_evidence_ref_check
        CHECK (length(btrim(evidence_ref)) BETWEEN 1 AND 160),
    CONSTRAINT conversation_presentation_pin_position_check
        CHECK (position BETWEEN 0 AND 99),
    CONSTRAINT conversation_presentation_pin_revision_check
        CHECK (revision BETWEEN 1 AND 9223372036854775806)
);

CREATE INDEX conversation_presentation_pins_owner_order
    ON public.conversation_presentation_pins
    (tenant_id, user_id, position, created_at, pin_id);

-- Defense in depth. The authenticated application transaction must set BOTH
-- app.current_tenant_id and app.current_user_id, never client-provided values.
ALTER TABLE public.conversation_presentation_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_presentation_pins FORCE ROW LEVEL SECURITY;

CREATE POLICY conversation_presentation_pins_owner
    ON public.conversation_presentation_pins
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.conversation_id = conversation_presentation_pins.conversation_id
              AND c.tenant_id = conversation_presentation_pins.tenant_id
              AND c.user_id = conversation_presentation_pins.user_id
        )
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.conversation_id = conversation_presentation_pins.conversation_id
              AND c.tenant_id = conversation_presentation_pins.tenant_id
              AND c.user_id = conversation_presentation_pins.user_id
        )
    );

REVOKE ALL ON public.conversation_presentation_pins FROM PUBLIC;

-- Supabase exposes anon/authenticated roles, while the canonical plain
-- PostgreSQL first-boot smoke image may not create either role. Revocation
-- remains mandatory whenever those roles exist, without making the
-- migration depend on a Supabase-only role bootstrap.
DO $revoke_client_pin_access$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.conversation_presentation_pins FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.conversation_presentation_pins FROM authenticated;
    END IF;
END;
$revoke_client_pin_access$;

COMMENT ON TABLE public.conversation_presentation_pins IS
    'Reference-only user-scoped saved presentation pins. Contents, verified attestation and authorization stay in canonical conversation runtime; every read must revalidate.';
COMMENT ON COLUMN public.conversation_presentation_pins.revision IS
    'Optimistic compare-and-swap version for bounded pin position mutations.';

COMMIT;
