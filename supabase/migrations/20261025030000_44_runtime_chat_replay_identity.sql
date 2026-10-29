-- CK-07D: bind completed-run replay to the exact atomic transcript pair.
-- Forward-only; no SDK-owned messages, tool output, or independent history store.
BEGIN;

ALTER TABLE public.runtime_chat_runs
  ADD COLUMN user_message_id UUID,
  ADD COLUMN assistant_message_id UUID;

ALTER TABLE public.runtime_chat_runs
  ADD CONSTRAINT ck_runtime_chat_completed_message_identity CHECK (
    status <> 'completed'
    OR (
      user_message_id IS NOT NULL
      AND assistant_message_id IS NOT NULL
      AND user_message_id <> assistant_message_id
    )
  ) NOT VALID;

-- Earlier gated runs without exact message identities remain non-replayable.
-- Do not infer or backfill historical proof.
CREATE INDEX idx_runtime_chat_replay_completed
  ON public.runtime_chat_runs (tenant_id, user_id, conversation_id, created_at)
  WHERE status = 'completed';

COMMENT ON COLUMN public.runtime_chat_runs.user_message_id IS
  'Canonical user message UUID committed with run completion.';
COMMENT ON COLUMN public.runtime_chat_runs.assistant_message_id IS
  'Canonical assistant message UUID committed with run completion.';

COMMIT;
