-- KCOMM-02A: UNVERSIONED REVIEW CANDIDATE. NOT A DEPLOYABLE MIGRATION.
-- Move this single source into a CLI-generated migration before acceptance.
-- Do not apply to a hosted or existing application database.
-- Requires canonical runtime and conversation composite source keys (46, 64).
BEGIN;

CREATE TABLE public.communications_inbox_entries (
    entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    execution_id UUID NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'terminal_chat_attention',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    read_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    revision BIGINT NOT NULL DEFAULT 1,
    CONSTRAINT communications_inbox_conversation_fk
        FOREIGN KEY (conversation_id, tenant_id, user_id)
        REFERENCES public.conversations (conversation_id, tenant_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT communications_inbox_execution_fk
        FOREIGN KEY (execution_id, tenant_id, user_id, conversation_id)
        REFERENCES public.runtime_chat_runs (execution_id, tenant_id, user_id, conversation_id)
        ON DELETE CASCADE,
    CONSTRAINT communications_inbox_source_unique
        UNIQUE (tenant_id, user_id, execution_id, source_kind),
    CONSTRAINT communications_inbox_source_kind_check
        CHECK (source_kind = 'terminal_chat_attention'),
    CONSTRAINT communications_inbox_revision_check
        CHECK (revision BETWEEN 1 AND 9223372036854775806),
    CONSTRAINT communications_inbox_lifecycle_check
        CHECK (
            (read_at IS NULL OR read_at >= created_at)
            AND (acknowledged_at IS NULL OR
                (read_at IS NOT NULL AND acknowledged_at >= read_at))
            AND (archived_at IS NULL OR archived_at >= created_at)
        )
);

CREATE INDEX communications_inbox_owner_order
    ON public.communications_inbox_entries
    (tenant_id, user_id, created_at DESC, entry_id DESC);
CREATE INDEX communications_inbox_owner_active
    ON public.communications_inbox_entries
    (tenant_id, user_id, created_at DESC, entry_id DESC)
    WHERE archived_at IS NULL;
CREATE INDEX communications_inbox_conversation_reference
    ON public.communications_inbox_entries (conversation_id, tenant_id, user_id);

-- The repository must use CAS predicates. This trigger independently prevents
-- source reassignment, state reversal, timestamp injection and no-op revisions.
CREATE FUNCTION public.communications_inbox_lifecycle_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $guard$
DECLARE
    changed_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.revision IS DISTINCT FROM 1
           OR NEW.read_at IS NOT NULL OR NEW.acknowledged_at IS NOT NULL
           OR NEW.archived_at IS NOT NULL THEN
            RAISE EXCEPTION 'communications_invalid_initial_state' USING ERRCODE = '23514';
        END IF;
        NEW.created_at := changed_at;
        RETURN NEW;
    END IF;

    IF ROW(NEW.entry_id, NEW.tenant_id, NEW.user_id, NEW.conversation_id,
           NEW.execution_id, NEW.source_kind, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.entry_id, OLD.tenant_id, OLD.user_id, OLD.conversation_id,
           OLD.execution_id, OLD.source_kind, OLD.created_at) THEN
        RAISE EXCEPTION 'communications_immutable_source' USING ERRCODE = '23514';
    END IF;

    IF NEW.revision IS DISTINCT FROM OLD.revision + 1
       OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at)
       OR (OLD.acknowledged_at IS NOT NULL
           AND NEW.acknowledged_at IS DISTINCT FROM OLD.acknowledged_at)
       OR (OLD.archived_at IS NOT NULL AND NEW.archived_at IS DISTINCT FROM OLD.archived_at)
       OR ROW(NEW.read_at, NEW.acknowledged_at, NEW.archived_at)
          IS NOT DISTINCT FROM ROW(OLD.read_at, OLD.acknowledged_at, OLD.archived_at) THEN
        RAISE EXCEPTION 'communications_invalid_lifecycle_transition' USING ERRCODE = '23514';
    END IF;

    -- A non-NULL proposed value requests a transition; only database time is saved.
    IF OLD.read_at IS NULL AND NEW.read_at IS NOT NULL THEN
        NEW.read_at := changed_at;
    END IF;
    IF OLD.acknowledged_at IS NULL AND NEW.acknowledged_at IS NOT NULL THEN
        NEW.acknowledged_at := changed_at;
        NEW.read_at := COALESCE(NEW.read_at, changed_at);
    END IF;
    IF OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL THEN
        NEW.archived_at := changed_at;
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.communications_inbox_lifecycle_guard() FROM PUBLIC;
CREATE TRIGGER communications_inbox_lifecycle_guard
    BEFORE INSERT OR UPDATE ON public.communications_inbox_entries
    FOR EACH ROW EXECUTE FUNCTION public.communications_inbox_lifecycle_guard();

ALTER TABLE public.communications_inbox_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.communications_inbox_entries FORCE ROW LEVEL SECURITY;

-- Existing backend transaction authority installs BOTH principal settings.
-- SELECT and UPDATE permit lifecycle readback even when source status changes;
-- callers still reauthorize original source before presenting attention.
CREATE POLICY communications_inbox_owner_select
    ON public.communications_inbox_entries FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY communications_inbox_owner_update
    ON public.communications_inbox_entries FOR UPDATE
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY communications_inbox_owner_insert
    ON public.communications_inbox_entries FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.runtime_chat_runs AS r
            WHERE r.execution_id = communications_inbox_entries.execution_id
              AND r.tenant_id = communications_inbox_entries.tenant_id
              AND r.user_id = communications_inbox_entries.user_id
              AND r.conversation_id = communications_inbox_entries.conversation_id
              AND r.status IN ('failed', 'orphaned')
              AND r.terminal_at IS NOT NULL
        )
    );
-- No standalone DELETE policy: privacy erasure proceeds via source cascade.
-- No user-facing creation, grants or provider delivery implied by this schema.
REVOKE ALL ON public.communications_inbox_entries FROM PUBLIC;
DO $revoke_client_access$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.communications_inbox_entries FROM anon;
        REVOKE ALL ON FUNCTION public.communications_inbox_lifecycle_guard() FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.communications_inbox_entries FROM authenticated;
        REVOKE ALL ON FUNCTION public.communications_inbox_lifecycle_guard() FROM authenticated;
    END IF;
END;
$revoke_client_access$;

COMMENT ON TABLE public.communications_inbox_entries IS
    'Principal-scoped attention lifecycle only. Runtime ledger remains execution authority; acknowledgment is not approval, restart, or delivery.';
COMMIT;
