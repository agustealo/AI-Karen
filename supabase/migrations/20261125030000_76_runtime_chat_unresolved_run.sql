-- KUI-004B4.48C7T: uncertainty retains the scoped admission fence.
-- Quiesce admission during rollout. Conflicting historical unresolved rows
-- must block migration; never rewrite or discard their execution evidence.
BEGIN;

CREATE UNIQUE INDEX runtime_chat_runs_unresolved_idx
    ON public.runtime_chat_runs (tenant_id, user_id, conversation_id)
    WHERE status IN ('running', 'cancelling', 'orphaned');

DROP INDEX public.runtime_chat_runs_single_active_idx;

COMMIT;
