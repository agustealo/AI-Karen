-- Durable Agent Medusa execution history.
-- PostgreSQL owns durable history. Redis remains live lease/cancellation coordination.
-- This is a forward-only post-baseline migration.

CREATE TABLE IF NOT EXISTS medusa_execution_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    session_id TEXT,
    policy_decision_id TEXT,
    status TEXT NOT NULL,
    owner_worker_id TEXT NOT NULL,
    audit_event_ref TEXT,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cancellation_requested_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    orphaned_at TIMESTAMPTZ,
    reconciled_at TIMESTAMPTZ,
    last_worker_transition_at TIMESTAMPTZ,
    CONSTRAINT medusa_execution_runs_status_check CHECK (
        status IN (
            'created',
            'running',
            'cancellation_requested',
            'cancelled',
            'completed',
            'failed',
            'orphaned'
        )
    ),
    CONSTRAINT medusa_execution_runs_terminal_time_check CHECK (
        status NOT IN ('cancelled', 'completed', 'failed', 'orphaned')
        OR completed_at IS NOT NULL
    ),
    CONSTRAINT medusa_execution_runs_cancel_time_check CHECK (
        status <> 'cancellation_requested'
        OR cancellation_requested_at IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_tenant_started
    ON medusa_execution_runs (tenant_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_tenant_status
    ON medusa_execution_runs (tenant_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_reconciliation
    ON medusa_execution_runs (updated_at ASC)
    WHERE status IN ('created', 'running', 'cancellation_requested');

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_correlation
    ON medusa_execution_runs (correlation_id);

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_policy_decision
    ON medusa_execution_runs (policy_decision_id)
    WHERE policy_decision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_medusa_execution_runs_audit_event
    ON medusa_execution_runs (audit_event_ref)
    WHERE audit_event_ref IS NOT NULL;

ALTER TABLE medusa_execution_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE medusa_execution_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS medusa_execution_runs_tenant_isolation
    ON medusa_execution_runs;

CREATE POLICY medusa_execution_runs_tenant_isolation
    ON medusa_execution_runs
    FOR ALL
    USING (
        tenant_id = current_setting('app.current_tenant_id', true)
    )
    WITH CHECK (
        tenant_id = current_setting('app.current_tenant_id', true)
    );

COMMENT ON TABLE medusa_execution_runs IS
    'Durable Medusa execution history. Never used as task ownership or lease authority.';
COMMENT ON COLUMN medusa_execution_runs.owner_worker_id IS
    'Worker that owned the concrete execution task when the run was registered; not a lease.';
COMMENT ON COLUMN medusa_execution_runs.audit_event_ref IS
    'Correlation token shared with the canonical audit event for administrative side effects.';
