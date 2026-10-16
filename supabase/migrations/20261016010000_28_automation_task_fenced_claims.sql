-- MI-08: Add durable fencing to saved-task execution.
-- The existing automation_tasks row remains the definition and latest-run owner.
-- Only one active claim can finalize; expired owners cannot overwrite newer work.
-- Live legacy Running rows without a claim deliberately remain unclaimable until
-- operator reconciliation. They are NOT silently resumed or marked successful.
BEGIN;

ALTER TABLE public.automation_tasks
    ADD COLUMN IF NOT EXISTS claim_token uuid,
    ADD COLUMN IF NOT EXISTS claim_expires_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_automation_tasks_claim_expiry
    ON public.automation_tasks (tenant_id, claim_expires_at)
    WHERE status = 'Running' AND claim_token IS NOT NULL;

COMMENT ON COLUMN public.automation_tasks.claim_token IS
    'Current execution fencing token. Only its owner can renew or finalize.';
COMMENT ON COLUMN public.automation_tasks.claim_expires_at IS
    'Execution lease deadline. Expired execution cannot report task success.';

COMMIT;
