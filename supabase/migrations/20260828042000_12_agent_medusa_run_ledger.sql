-- MEDUSA-DURABLE-RUNS-1
-- Durable execution history for Agent Medusa.
-- Redis remains the live coordination/lease plane; PostgreSQL owns durable run history.

CREATE TABLE agent_medusa_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    owner_worker_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    error_type TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT agent_medusa_runs_status_check CHECK (
        status IN (
            'running',
            'cancelling',
            'completed',
            'failed',
            'cancelled',
            'orphaned'
        )
    ),
    CONSTRAINT agent_medusa_runs_terminal_time_check CHECK (
        (status IN ('running', 'cancelling') AND completed_at IS NULL)
        OR
        (status IN ('completed', 'failed', 'cancelled', 'orphaned') AND completed_at IS NOT NULL)
    )
);

CREATE INDEX idx_agent_medusa_runs_tenant_started
    ON agent_medusa_runs (tenant_id, started_at DESC);

CREATE INDEX idx_agent_medusa_runs_tenant_status_started
    ON agent_medusa_runs (tenant_id, status, started_at DESC);

CREATE INDEX idx_agent_medusa_runs_active_heartbeat
    ON agent_medusa_runs (heartbeat_at)
    WHERE status IN ('running', 'cancelling');

CREATE INDEX idx_agent_medusa_runs_correlation
    ON agent_medusa_runs (tenant_id, correlation_id);

ALTER TABLE agent_medusa_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_medusa_runs FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_medusa_runs_tenant_isolation
    ON agent_medusa_runs
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE agent_medusa_runs IS
    'Durable Agent Medusa execution ledger. Redis is live coordination only; this table is historical execution truth.';
COMMENT ON COLUMN agent_medusa_runs.heartbeat_at IS
    'Last durable liveness observation used for restart/orphan reconciliation.';
COMMENT ON COLUMN agent_medusa_runs.metadata IS
    'Non-authoritative execution metadata. Provider/model/platform routing authority remains outside Medusa.';
