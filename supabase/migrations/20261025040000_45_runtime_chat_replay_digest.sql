-- CK-07D: forward-only tamper evidence for atomically completed transcripts.
-- Separate from migration 44 for already-upgraded installations.
BEGIN;

ALTER TABLE public.runtime_chat_runs
  ADD COLUMN assistant_message_digest CHAR(64);

ALTER TABLE public.runtime_chat_runs
  ADD CONSTRAINT ck_runtime_chat_completed_digest CHECK (
    status <> 'completed'
    OR assistant_message_digest ~ '^[0-9a-f]{64}$'
  ) NOT VALID;

-- Existing completed rows have no digest and remain non-replayable.
-- Never backfill from mutable historical messages or infer a provider receipt.
COMMENT ON COLUMN public.runtime_chat_runs.assistant_message_digest IS
  'SHA-256 of canonical assistant message content and metadata at atomic run completion.';

COMMIT;
