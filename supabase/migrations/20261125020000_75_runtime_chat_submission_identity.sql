-- KUI-004B4.48C7M: preserve original submitted user-turn identity.
-- Historical rows have no reliable client message ID; never invent one.
-- Apply after migration 74 and before deploying the new admission owner.
BEGIN;

ALTER TABLE public.runtime_chat_runs
    ADD COLUMN submission_id VARCHAR(100),
    ADD CONSTRAINT ck_runtime_chat_submission_id
        CHECK (submission_id IS NULL OR submission_id ~ '^[A-Za-z0-9_-]{1,100}$');

CREATE UNIQUE INDEX runtime_chat_runs_submission_idx
    ON public.runtime_chat_runs (tenant_id, user_id, conversation_id, submission_id)
    WHERE submission_id IS NOT NULL;

COMMENT ON COLUMN public.runtime_chat_runs.submission_id IS
    'Untrusted retry-stable original user-message ID, scoped to the authenticated conversation; never an authorization credential.';

COMMIT;
