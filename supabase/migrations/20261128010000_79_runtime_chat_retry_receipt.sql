-- KEXP-042A.6D6: causal evidence of a committed explicit draft retry CAS.
-- No backfill: historical successor revisions do not prove a retry mutation.
-- Keep all existing terminal execution identity and transcript evidence intact.
BEGIN;

ALTER TABLE public.runtime_chat_runs
    ADD COLUMN retry_prepared_revision BIGINT,
    ADD COLUMN retry_prepared_at TIMESTAMPTZ,
    ADD CONSTRAINT ck_runtime_chat_retry_receipt CHECK (
        (retry_prepared_revision IS NULL AND retry_prepared_at IS NULL)
        OR (
            retry_prepared_revision IS NOT NULL AND retry_prepared_at IS NOT NULL
            AND retry_prepared_revision BETWEEN 2 AND 9007199254740990
            AND status IN ('failed', 'cancelled')
            AND terminal_at IS NOT NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND user_message_id IS NULL AND assistant_message_id IS NULL
            AND assistant_message_digest IS NULL
            AND submission_id IS NOT NULL
            AND CASE
                WHEN submission_id ~ '^draft-v1-[1-9][0-9]{0,15}$'
                  OR submission_id ~ '^draft-v2-[1-9][0-9]{0,15}-[a-f0-9]{64}$'
                THEN retry_prepared_revision = split_part(submission_id, '-', 3)::bigint + 1
                ELSE FALSE
            END
        )
    );

COMMENT ON COLUMN public.runtime_chat_runs.retry_prepared_revision IS
    'Causal successor revision recorded atomically with explicit retained draft retry CAS; not an execution grant.';
COMMENT ON COLUMN public.runtime_chat_runs.retry_prepared_at IS
    'Database observation time of retry preparation; null for historical or unprepared rows.';

COMMIT;
