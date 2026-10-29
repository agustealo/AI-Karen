-- CK-07E6: one canonical tenant/user/conversation-scoped unsent composer draft.
-- This is NOT transcript, memory, model execution or an AG-UI run.
-- Apply before enabling CopilotKit persistent draft reads/writes.
BEGIN;

CREATE TABLE public.conversation_composer_drafts (
    conversation_id UUID PRIMARY KEY
        REFERENCES public.conversations(conversation_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL
        REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL
        REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    draft_text TEXT NOT NULL DEFAULT '',
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_conversation_composer_draft_revision CHECK (revision BETWEEN 1 AND 9223372036854775806),
    CONSTRAINT ck_conversation_composer_draft_size CHECK (
        char_length(draft_text) <= 65536
        AND octet_length(draft_text) <= 262144
    )
);

CREATE INDEX idx_conversation_composer_draft_owner
    ON public.conversation_composer_drafts (tenant_id, user_id, updated_at DESC);

ALTER TABLE public.conversation_composer_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_composer_drafts FORCE ROW LEVEL SECURITY;

CREATE POLICY conversation_composer_draft_owner
    ON public.conversation_composer_drafts FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.conversations AS c
            WHERE c.conversation_id = conversation_composer_drafts.conversation_id
              AND c.tenant_id = conversation_composer_drafts.tenant_id
              AND c.user_id = conversation_composer_drafts.user_id
        )
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.conversations AS c
            WHERE c.conversation_id = conversation_composer_drafts.conversation_id
              AND c.tenant_id = conversation_composer_drafts.tenant_id
              AND c.user_id = conversation_composer_drafts.user_id
        )
    );

COMMENT ON TABLE public.conversation_composer_drafts IS
    'Canonical unsent user-authored draft only; optimistic revision; conversation deletion cascades; no provider/tools/AI transcript.';
COMMENT ON COLUMN public.conversation_composer_drafts.revision IS
    'Compare-and-swap revision. Empty unsaved drafts have virtual revision 0.';

COMMIT;
