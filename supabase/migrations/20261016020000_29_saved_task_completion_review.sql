-- MI-09: Separate completed inference from verified task objectives.
-- The automation_tasks row remains the latest-run/review source of truth.
-- Legacy Success never becomes human-verified without review evidence.
BEGIN;

ALTER TABLE public.automation_tasks
    ADD COLUMN IF NOT EXISTS execution_id uuid,
    ADD COLUMN IF NOT EXISTS result_receipt jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS reviewed_at timestamptz,
    ADD COLUMN IF NOT EXISTS reviewed_by uuid,
    ADD COLUMN IF NOT EXISTS review_note text;

ALTER TABLE public.automation_tasks
    DROP CONSTRAINT IF EXISTS automation_tasks_status_check;
ALTER TABLE public.automation_tasks
    ADD CONSTRAINT automation_tasks_status_check
    CHECK (
        status IN (
            'Pending', 'Running', 'ReviewRequired',
            'Success', 'Rejected', 'Failed', 'LegacyUnverified'
        )
    );

UPDATE public.automation_tasks
SET status = 'LegacyUnverified',
    updated_at = clock_timestamp()
WHERE status = 'Success' AND reviewed_at IS NULL;

-- A verified task must have a concrete reviewer, review time and execution.
ALTER TABLE public.automation_tasks
    ADD CONSTRAINT automation_tasks_verified_receipt_check
    CHECK (
        status <> 'Success'
        OR (
            reviewed_by IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND execution_id IS NOT NULL
        )
    );

COMMENT ON COLUMN public.automation_tasks.result_receipt IS
    'Runtime-confirmed identifiers and references for the latest execution; not proof of goal satisfaction.';
COMMENT ON COLUMN public.automation_tasks.execution_id IS
    'Opaque latest task-attempt identity; reviews must match this exact attempt.';
COMMENT ON COLUMN public.automation_tasks.reviewed_by IS
    'Authenticated task creator who explicitly verified or rejected the latest result.';
COMMENT ON TABLE public.automation_tasks IS
    'Durable tenant-scoped saved-task definitions and latest attempt outcome. Success requires explicit human verification; execution stays in ChatRuntime.';

COMMIT;
