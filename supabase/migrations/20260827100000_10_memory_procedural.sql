-- MEMORY-RUNTIME: durable procedural memory projection
-- Extends the canonical Supabase/Postgres memory ledger. This is not a
-- competing memory store; every durable procedure must retain provenance to a
-- governed memory_event.

CREATE TABLE IF NOT EXISTS memory_procedure (
    procedure_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    trigger_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    success_count BIGINT NOT NULL DEFAULT 0,
    failure_count BIGINT NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    lifecycle_state VARCHAR(50) NOT NULL DEFAULT 'active',
    valid_from TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to TIMESTAMP,
    metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_memory_procedure_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CONSTRAINT ck_memory_procedure_counts CHECK (success_count >= 0 AND failure_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_memory_procedure_tenant_user
    ON memory_procedure(tenant_id, user_id, lifecycle_state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_procedure_source_event
    ON memory_procedure(source_event_id);

CREATE INDEX IF NOT EXISTS idx_memory_procedure_validity
    ON memory_procedure(valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_memory_procedure_triggers
    ON memory_procedure USING GIN (trigger_patterns);

ALTER TABLE memory_procedure ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_procedure_tenant_isolation ON memory_procedure;
CREATE POLICY memory_procedure_tenant_isolation ON memory_procedure
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

COMMENT ON TABLE memory_procedure IS
    'Rebuildable durable procedural-memory projection derived from governed memory events.';
COMMENT ON COLUMN memory_procedure.source_event_id IS
    'Canonical provenance event that authorized/produced this procedure.';
