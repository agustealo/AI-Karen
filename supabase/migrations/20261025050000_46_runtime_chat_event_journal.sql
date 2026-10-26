-- CK-07E0: runtime-owned, owner-scoped observed AG-UI event cursor.
-- Experimental and disabled by default. This is not a new conversation store.
-- Only projected, bounded, already-observed transport events may be recorded.
BEGIN;

CREATE UNIQUE INDEX uq_runtime_chat_run_full_scope
  ON public.runtime_chat_runs (execution_id, tenant_id, user_id, conversation_id);

CREATE TABLE public.runtime_chat_run_events (
  execution_id UUID NOT NULL,
  tenant_id UUID NOT NULL,
  user_id UUID NOT NULL,
  conversation_id UUID NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  event_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT pk_runtime_chat_run_events PRIMARY KEY (execution_id, event_seq),
  CONSTRAINT fk_runtime_chat_event_scoped_run
    FOREIGN KEY (execution_id, tenant_id, user_id, conversation_id)
    REFERENCES public.runtime_chat_runs (
      execution_id, tenant_id, user_id, conversation_id
    ) ON DELETE CASCADE,
  CONSTRAINT ck_runtime_chat_event_sequence CHECK (
    event_seq >= 1 AND event_seq <= 2048
  ),
  CONSTRAINT ck_runtime_chat_event_type CHECK (
    event_type IN (
      'RUN_STARTED', 'TEXT_MESSAGE_START', 'TEXT_MESSAGE_CONTENT',
      'TEXT_MESSAGE_END', 'ACTIVITY_SNAPSHOT', 'TOOL_CALL_START',
      'TOOL_CALL_END', 'SUBAGENT_STARTED', 'SUBAGENT_FINISHED',
      'SUBAGENT_ERROR', 'CUSTOM', 'RUN_ERROR', 'RUN_FINISHED'
    )
  ),
  CONSTRAINT ck_runtime_chat_event_payload CHECK (
    jsonb_typeof(event_payload) = 'object'
    AND event_payload ->> 'type' = event_type
    AND octet_length(event_payload::text) <= 32768
  )
);

CREATE INDEX idx_runtime_chat_event_owned_cursor
  ON public.runtime_chat_run_events
  (tenant_id, user_id, conversation_id, execution_id, event_seq);

ALTER TABLE public.runtime_chat_run_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_chat_run_events FORCE ROW LEVEL SECURITY;

CREATE POLICY runtime_chat_event_scoped_read_write
  ON public.runtime_chat_run_events
  FOR ALL
  USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
  );

COMMENT ON TABLE public.runtime_chat_run_events IS
  'Append-only, server-projected AG-UI observation journal; not a model transcript or authority for terminal success.';
COMMENT ON COLUMN public.runtime_chat_run_events.event_seq IS
  'Per-run cursor serialized with the parent execution row lock; starts at 1.';
COMMENT ON COLUMN public.runtime_chat_run_events.event_payload IS
  'Allowlisted bounded AG-UI event only; replay must retain interruption and terminal provenance.';

COMMIT;
