-- MEMORY-RUNTIME: deterministic entity resolution for the canonical memory graph.
-- pg_trgm is a PostgreSQL/Supabase capability, not a new runtime service.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS memory_entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES memory_entity(entity_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source_event_id UUID REFERENCES memory_event(event_id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_memory_entity_alias_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CONSTRAINT uq_memory_entity_alias UNIQUE (tenant_id, user_id, normalized_alias, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_entity_normalized_trgm
    ON memory_entity USING GIN (normalized_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_memory_entity_alias_normalized_trgm
    ON memory_entity_alias USING GIN (normalized_alias gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_memory_entity_alias_scope
    ON memory_entity_alias(tenant_id, user_id, entity_id);

ALTER TABLE memory_entity_alias ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_entity_alias_tenant_isolation ON memory_entity_alias;
CREATE POLICY memory_entity_alias_tenant_isolation ON memory_entity_alias
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

COMMENT ON TABLE memory_entity_alias IS
    'Tenant-scoped aliases for canonical memory_entity identities; uncertain aliases remain separate until governed merge.';
