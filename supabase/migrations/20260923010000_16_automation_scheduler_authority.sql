-- CAPABILITY-TRUTH-2
-- Durable, tenant-scoped automation definitions and queue authority.
-- Runtime code must never create these tables or fall back to process/file memory.

BEGIN;

CREATE TABLE IF NOT EXISTS public.automation_tasks (
    task_id text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    name text NOT NULL,
    description text NOT NULL,
    primary_agent text NOT NULL,
    primary_agent_instructions text NOT NULL DEFAULT '',
    task_type text NOT NULL,
    sub_agents jsonb NOT NULL DEFAULT '[]'::jsonb,
    status varchar(32) NOT NULL DEFAULT 'Pending',
    last_run_at timestamptz,
    last_error text,
    run_count integer NOT NULL DEFAULT 0 CHECK (run_count >= 0),
    runtime_task_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT automation_tasks_status_check
        CHECK (status IN ('Pending', 'Running', 'Success', 'Failed'))
);

CREATE INDEX IF NOT EXISTS idx_automation_tasks_tenant_created
    ON public.automation_tasks (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_tasks_tenant_status
    ON public.automation_tasks (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_automation_tasks_tenant_agent
    ON public.automation_tasks (tenant_id, primary_agent);

CREATE TABLE IF NOT EXISTS public.automation_jobs (
    job_id text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    name text NOT NULL,
    description text NOT NULL,
    tasks jsonb NOT NULL DEFAULT '[]'::jsonb,
    trigger text NOT NULL DEFAULT 'Manual Run',
    status varchar(32) NOT NULL DEFAULT 'Pending',
    last_results jsonb NOT NULL DEFAULT '[]'::jsonb,
    last_run_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT automation_jobs_status_check
        CHECK (status IN ('Pending', 'Running', 'Success', 'Failed'))
);

CREATE INDEX IF NOT EXISTS idx_automation_jobs_tenant_created
    ON public.automation_jobs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_jobs_tenant_status
    ON public.automation_jobs (tenant_id, status);

CREATE TABLE IF NOT EXISTS public.automation_cron_jobs (
    cron_id text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    task_name text NOT NULL,
    schedule text NOT NULL,
    job_type varchar(16) NOT NULL,
    target_id text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    action varchar(16) NOT NULL DEFAULT 'execute',
    next_run_at timestamptz NOT NULL,
    last_run_at timestamptz,
    last_error text,
    claim_token uuid,
    claimed_by text,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT automation_cron_type_check
        CHECK (job_type IN ('Task', 'Job', 'Sequence')),
    CONSTRAINT automation_cron_action_check
        CHECK (action IN ('execute', 'enqueue'))
);

CREATE INDEX IF NOT EXISTS idx_automation_cron_tenant_created
    ON public.automation_cron_jobs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_cron_due
    ON public.automation_cron_jobs (enabled, next_run_at)
    WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_automation_cron_claim_expiry
    ON public.automation_cron_jobs (claim_expires_at)
    WHERE claim_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.automation_queue_items (
    item_id text PRIMARY KEY,
    queue_name text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    tenant_id uuid REFERENCES public.tenants(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    available_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    last_error text,
    status varchar(24) NOT NULL DEFAULT 'pending',
    claimed_by text,
    claim_token uuid,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    completed_at timestamptz,
    CONSTRAINT automation_queue_status_check
        CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter'))
);

CREATE INDEX IF NOT EXISTS idx_automation_queue_available
    ON public.automation_queue_items (queue_name, status, available_at, created_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_automation_queue_claim_expiry
    ON public.automation_queue_items (claim_expires_at)
    WHERE status = 'processing';

ALTER TABLE public.automation_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.automation_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.automation_cron_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_cron_jobs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS automation_tasks_tenant_scope ON public.automation_tasks;
CREATE POLICY automation_tasks_tenant_scope ON public.automation_tasks
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS automation_jobs_tenant_scope ON public.automation_jobs;
CREATE POLICY automation_jobs_tenant_scope ON public.automation_jobs
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS automation_cron_tenant_scope ON public.automation_cron_jobs;
CREATE POLICY automation_cron_tenant_scope ON public.automation_cron_jobs
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        OR current_setting('app.scheduler_worker', true) = '1'
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        OR current_setting('app.scheduler_worker', true) = '1'
    );

ALTER TABLE public.automation_queue_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_queue_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS automation_queue_worker_scope ON public.automation_queue_items;
CREATE POLICY automation_queue_worker_scope ON public.automation_queue_items
    FOR ALL
    USING (current_setting('app.automation_worker', true) = '1')
    WITH CHECK (current_setting('app.automation_worker', true) = '1');

COMMENT ON TABLE public.automation_tasks IS
    'Durable tenant-scoped saved task definitions. AI execution remains owned by ChatRuntime.';
COMMENT ON TABLE public.automation_jobs IS
    'Durable tenant-scoped multi-step job definitions. Steps delegate to the canonical task/runtime adapter.';
COMMENT ON TABLE public.automation_cron_jobs IS
    'Durable cron commitments with claim leases for multi-replica scheduler safety.';
COMMENT ON TABLE public.automation_queue_items IS
    'Internal durable work queue with retry, dead-letter, and claim-lease semantics.';

COMMIT;
