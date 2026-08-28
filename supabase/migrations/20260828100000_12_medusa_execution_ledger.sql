-- Durable Agent Medusa execution history.
-- PostgreSQL owns durable run history; Redis remains transient live coordination.

CREATE TABLE medusa_execution_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    request_id TEXT,
    policy_decision_id TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'created', 'running', 'cancellation_requested',
        'cancelled', 'completed', 'failed', 'orphaned'
    )),
    owner_worker_id TEXT,
    worker_epoch BIGINT NOT NULL DEFAULT 0 CHECK (worker_epoch >= 0),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_type TEXT,
    terminal_reason TEXT,
    audit_event_id TEXT,
    distributed_control_state TEXT,
    CONSTRAINT medusa_execution_runs_terminal_timestamp CHECK (
        status NOT IN ('cancelled', 'completed', 'failed', 'orphaned')
        OR completed_at IS NOT NULL
    )
);

CREATE INDEX idx_medusa_execution_runs_tenant_updated
    ON medusa_execution_runs (tenant_id, updated_at DESC);
CREATE INDEX idx_medusa_execution_runs_tenant_active
    ON medusa_execution_runs (tenant_id, status, updated_at DESC)
    WHERE status IN ('created', 'running', 'cancellation_requested');
CREATE INDEX idx_medusa_execution_runs_correlation
    ON medusa_execution_runs (tenant_id, correlation_id);

CREATE TABLE medusa_execution_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES medusa_execution_runs(run_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN (
        'created', 'running', 'cancellation_requested',
        'cancelled', 'completed', 'failed', 'orphaned'
    )),
    worker_id TEXT,
    worker_epoch BIGINT,
    correlation_id TEXT NOT NULL,
    request_id TEXT,
    policy_decision_id TEXT,
    audit_event_id TEXT,
    reason_code TEXT,
    error_type TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_medusa_execution_events_run
    ON medusa_execution_events (tenant_id, run_id, event_id);
CREATE INDEX idx_medusa_execution_events_correlation
    ON medusa_execution_events (tenant_id, correlation_id, occurred_at DESC);

ALTER TABLE medusa_execution_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE medusa_execution_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE medusa_execution_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE medusa_execution_events FORCE ROW LEVEL SECURITY;

CREATE POLICY medusa_execution_runs_tenant_select ON medusa_execution_runs
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY medusa_execution_runs_tenant_insert ON medusa_execution_runs
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY medusa_execution_runs_tenant_update ON medusa_execution_runs
    FOR UPDATE
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Transition history is append-only by policy: tenants may SELECT and INSERT,
-- but there is intentionally no UPDATE or DELETE policy for event rows.
CREATE POLICY medusa_execution_events_tenant_select ON medusa_execution_events
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
CREATE POLICY medusa_execution_events_tenant_insert ON medusa_execution_events
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);

COMMENT ON TABLE medusa_execution_runs IS
    'Durable Medusa execution state. Redis must not be treated as historical authority.';
COMMENT ON TABLE medusa_execution_events IS
    'Append-only durable Medusa execution transition history.';
