-- KCOMM-02C UNVERSIONED REVIEW CANDIDATE. DO NOT DEPLOY.
-- Promote once via Supabase CLI after parent acceptance; no historical backfill.
BEGIN;

ALTER TABLE public.runtime_chat_runs
    ADD COLUMN communications_attention_eligible_at timestamptz,
    ADD COLUMN communications_attention_conversation_id uuid,
    ADD CONSTRAINT runtime_chat_attention_conversation_fk
        FOREIGN KEY (communications_attention_conversation_id, tenant_id, user_id)
        REFERENCES public.conversations (conversation_id, tenant_id, user_id)
        ON DELETE SET NULL (communications_attention_conversation_id),
    ADD CONSTRAINT ck_runtime_chat_attention_conversation
        CHECK (communications_attention_conversation_id IS NULL OR
               communications_attention_conversation_id = conversation_id),
    ADD CONSTRAINT ck_runtime_chat_communications_attention
    CHECK (
        communications_attention_eligible_at IS NULL OR (
            status IN ('failed', 'orphaned') AND terminal_at IS NOT NULL
            AND communications_attention_eligible_at = terminal_at
        )
    );

CREATE INDEX runtime_chat_communications_attention_idx
    ON public.runtime_chat_runs
        (tenant_id, user_id, communications_attention_eligible_at, execution_id)
    WHERE communications_attention_eligible_at IS NOT NULL
      AND communications_attention_conversation_id IS NOT NULL;

CREATE INDEX runtime_chat_attention_conversation_idx
    ON public.runtime_chat_runs (communications_attention_conversation_id, tenant_id, user_id)
    WHERE communications_attention_conversation_id IS NOT NULL;

-- The runtime explicitly writes the marker in the terminal transition.
-- No historical terminal row or already-marked run may be retroactively marked.
CREATE FUNCTION public.runtime_chat_communications_attention_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.communications_attention_eligible_at IS NOT NULL OR (
            NEW.communications_attention_conversation_id IS NOT NULL AND NEW.status <> 'running'
        ) THEN
            RAISE EXCEPTION 'communications_attention_requires_transition' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    -- Source binding is write-once at run admission. The FK clears it on
    -- deletion without removing the canonical runtime ledger. Never rebind
    -- even if an erased conversation UUID is later recreated.
    IF NEW.communications_attention_conversation_id IS DISTINCT FROM OLD.communications_attention_conversation_id
       AND NEW.communications_attention_conversation_id IS NOT NULL THEN
        RAISE EXCEPTION 'communications_attention_source_immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.communications_attention_eligible_at IS DISTINCT FROM OLD.communications_attention_eligible_at
       AND (
           OLD.communications_attention_eligible_at IS NOT NULL
           OR OLD.status NOT IN ('running', 'cancelling')
           OR NEW.status NOT IN ('failed', 'orphaned')
           OR OLD.communications_attention_conversation_id IS NULL
           OR NEW.communications_attention_conversation_id IS NULL
           OR NEW.communications_attention_eligible_at IS NULL
           OR NEW.terminal_at IS NULL
           OR NEW.communications_attention_eligible_at IS DISTINCT FROM NEW.terminal_at
       ) THEN
        RAISE EXCEPTION 'communications_attention_requires_transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.runtime_chat_communications_attention_guard() FROM PUBLIC;
DO $revoke$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.runtime_chat_communications_attention_guard() FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.runtime_chat_communications_attention_guard() FROM authenticated;
    END IF;
END;
$revoke$;
CREATE TRIGGER runtime_chat_communications_attention_guard
    BEFORE INSERT OR UPDATE OF communications_attention_eligible_at, communications_attention_conversation_id
    ON public.runtime_chat_runs
    FOR EACH ROW EXECUTE FUNCTION public.runtime_chat_communications_attention_guard();

-- Existing owner policy is narrowed: the marker is mandatory for new entries.
ALTER POLICY communications_inbox_owner_insert
    ON public.communications_inbox_entries
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
              AND r.communications_attention_eligible_at = r.terminal_at
              AND r.communications_attention_conversation_id = r.conversation_id
        )
    );

COMMENT ON COLUMN public.runtime_chat_runs.communications_attention_eligible_at IS
    'Opt-in marker written only by a new terminal transition; not delivery, approval, or a historical backfill.';

COMMENT ON COLUMN public.runtime_chat_runs.communications_attention_conversation_id IS
    'Revocable source binding established at opt-in run admission; FK deletion clears it permanently, without erasing runtime evidence.';

COMMIT;
