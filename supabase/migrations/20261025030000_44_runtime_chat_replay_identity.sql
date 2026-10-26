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
  );

CREATE INDEX idx_runtime_chat_replay_completed
  ON public.runtime_chat_runs (tenant_id, user_id, conversation_id, created_at)
  WHERE status = 'completed';

COMMENT ON COLUMN public.runtime_chat_runs.user_message_id IS
  'Exact canonical user message UUID committed with completed run in the same SQL transaction.';
COMMENT ON COLUMN public.runtime_chat_runs.assistant_message_id IS
  'Exact canonical assistant message UUID used to attest replay provenance.';

COMMIT;
