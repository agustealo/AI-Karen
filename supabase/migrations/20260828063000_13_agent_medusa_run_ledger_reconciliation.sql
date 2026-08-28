-- MEDUSA-DURABLE-RUNS-2
-- Complete durable Medusa execution history without moving live control out of Redis/runtime.
-- Forward-only extension of 20260828042000_12_agent_medusa_run_ledger.sql.

ALTER TABLE agent_medusa_runs
    ADD COLUMN request_id TEXT,
    ADD COLUMN session_id TEXT,
    ADD COLUMN policy_decision_id TEXT,
    ADD COLUMN audit_event_ref TEXT,
    ADD COLUMN created_at TIMESTAMPTZ,
    ADD COLUMN reconciled_at TIMESTAMPTZ,
    ADD COLUMN last_worker_transition_at TIMESTAMPTZ;

UPDATE agent_medusa_runs
SET request_id = COALESCE(request_id, correlation_id, run_id),
    created_at = COALESCE(created_at, started_at),
    last_worker_transition_at = COALESCE(last_worker_transition_at, updated_at, started_at);

ALTER TABLE agent_medusa_runs
    ALTER COLUMN request_id SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE agent_medusa_runs
    DROP CONSTRAINT agent_medusa_runs_status_check,
    DROP CONSTRAINT agent_medusa_runs_terminal_time_check;

UPDATE agent_medusa_runs
SET status = 'cancellation_requested'
WHERE status = 'cancelling';

ALTER TABLE agent_medusa_runs
    ADD CONSTRAINT agent_medusa_runs_status_check CHECK (
        status IN (
            'created',
            'running',
            'cancellation_requested',
            'completed',
            'failed',
            'cancelled',
            'orphaned'
        )
    ),
    ADD CONSTRAINT agent_medusa_runs_terminal_time_check CHECK (
        (status IN ('created', 'running', 'cancellation_requested') AND completed_at IS NULL)
        OR
        (status IN ('completed', 'failed', 'cancelled', 'orphaned') AND completed_at IS NOT NULL)
    );

DROP INDEX IF EXISTS idx_agent_medusa_runs_active_heartbeat;
CREATE INDEX idx_agent_medusa_runs_active_updated
    ON agent_medusa_runs (tenant_id, updated_at, run_id)
    WHERE status IN ('created', 'running', 'cancellation_requested');

CREATE INDEX idx_agent_medusa_runs_request
    ON agent_medusa_runs (tenant_id, request_id);

CREATE INDEX idx_agent_medusa_runs_policy_decision
    ON agent_medusa_runs (tenant_id, policy_decision_id)
    WHERE policy_decision_id IS NOT NULL;

CREATE INDEX idx_agent_medusa_runs_audit_event
    ON agent_medusa_runs (tenant_id, audit_event_ref)
    WHERE audit_event_ref IS NOT NULL;

CREATE TABLE agent_medusa_run_transitions (
    transition_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_medusa_runs(run_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    worker_id TEXT,
    source TEXT NOT NULL,
    event_at TIMESTAMPTZ NOT NULL,
    audit_event_ref TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT agent_medusa_run_transitions_from_status_check CHECK (
        from_status IS NULL OR from_status IN (
            'created', 'running', 'cancellation_requested',
            'completed', 'failed', 'cancelled', 'orphaned'
        )
    ),
    CONSTRAINT agent_medusa_run_transitions_to_status_check CHECK (
        to_status IN (
            'created', 'running', 'cancellation_requested',
            'completed', 'failed', 'cancelled', 'orphaned'
        )
    ),
    CONSTRAINT agent_medusa_run_transitions_source_check CHECK (
        source IN ('runtime', 'admin_cancel', 'redis_reconciliation', 'migration_backfill')
    )
);

INSERT INTO agent_medusa_run_transitions (
    run_id, tenant_id, from_status, to_status, worker_id, source, event_at, metadata
)
SELECT
    run_id,
    tenant_id,
    NULL,
    status,
    owner_worker_id,
    'migration_backfill',
    COALESCE(updated_at, started_at),
    jsonb_build_object('backfilled', true)
FROM agent_medusa_runs;

CREATE INDEX idx_agent_medusa_run_transitions_run_event
    ON agent_medusa_run_transitions (run_id, event_at, transition_id);

CREATE INDEX idx_agent_medusa_run_transitions_tenant_event
    ON agent_medusa_run_transitions (tenant_id, event_at DESC);

ALTER TABLE agent_medusa_run_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_medusa_run_transitions FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_medusa_run_transitions_tenant_isolation
    ON agent_medusa_run_transitions
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE agent_medusa_run_transitions IS
    'Append-only durable Medusa lifecycle history. This table never owns task cancellation, leases, or worker election.';
COMMENT ON COLUMN agent_medusa_runs.reconciled_at IS
    'Timestamp of the latest Redis-to-PostgreSQL state repair; never a liveness authority by itself.';
COMMENT ON COLUMN agent_medusa_runs.audit_event_ref IS
    'Correlation token linking an administrative lifecycle transition to canonical audit logging.';
