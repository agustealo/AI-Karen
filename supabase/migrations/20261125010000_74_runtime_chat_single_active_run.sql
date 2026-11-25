-- KUI-004B4.48C7K: one active execution per tenant/user/conversation.
-- Apply before deploying the admission owner. Existing duplicate active
-- rows must block the migration; do not silently choose a winner or rewrite
-- any execution receipt. Quiesce chat admission during migration rollout.
BEGIN;

CREATE UNIQUE INDEX runtime_chat_runs_single_active_idx
    ON public.runtime_chat_runs (tenant_id, user_id, conversation_id)
    WHERE status IN ('running', 'cancelling');

COMMIT;
