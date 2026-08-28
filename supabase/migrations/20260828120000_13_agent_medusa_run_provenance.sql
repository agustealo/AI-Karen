-- MEDUSA-DURABLE-RUNS-2
-- Forward-only provenance/history extension for the canonical Agent Medusa ledger.

ALTER TABLE agent_medusa_runs
    ADD COLUMN request_id TEXT,
    ADD COLUMN policy_decision_id TEXT,
    ADD COLUMN audit_event_id TEXT;

CREATE INDEX idx_agent_medusa_runs_request
    ON agent_medusa_runs (tenant_id, request_id)
    WHERE request_id IS NOT NULL;

CREATE INDEX idx_agent_medusa_runs_policy_decision
    ON agent_medusa_runs (tenant_id, policy_decision_id)
    WHERE policy_decision_id IS NOT NULL;

CREATE TABLE agent_medusa_run_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_medusa_runs(run_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN (
        'created', 'running', 'cancellation_requested',
        'cancelled', 'completed', 'failed', 'orphaned'
    )),
    worker_id TEXT,
    correlation_id TEXT NOT NULL,
    request_id TEXT,
    policy_decision_id TEXT,
    audit_event_id TEXT,
    error_type TEXT,
    reason_code TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_agent_medusa_run_events_run
    ON agent_medusa_run_events (tenant_id, run_id, event_id);
CREATE INDEX idx_agent_medusa_run_events_correlation
    ON agent_medusa_run_events (tenant_id, correlation_id, occurred_at DESC);

ALTER TABLE agent_medusa_run_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_medusa_run_events FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_medusa_run_events_tenant_select
    ON agent_medusa_run_events
    FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

CREATE POLICY agent_medusa_run_events_tenant_insert
    ON agent_medusa_run_events
    FOR INSERT
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE agent_medusa_run_events IS
    'Append-only Agent Medusa execution transition history. No UPDATE or DELETE tenant policy is intentionally defined.';
