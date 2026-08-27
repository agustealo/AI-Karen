-- MEMORY-RUNTIME-FULL / MEMORY-GRAPH-2
-- Evolve the existing canonical memory ledger into a tenant-safe temporal graph.
-- PostgreSQL/Supabase remains durable authority; graph rows are rebuildable projections.

CREATE TABLE IF NOT EXISTS memory_entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    canonical_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    entity_type VARCHAR(100),
    metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_entity_tenant_user_normalized
    ON memory_entity(tenant_id, user_id, normalized_text);
CREATE INDEX IF NOT EXISTS idx_memory_entity_tenant_type
    ON memory_entity(tenant_id, entity_type);

ALTER TABLE memory_relation
    ADD COLUMN IF NOT EXISTS user_id UUID,
    ADD COLUMN IF NOT EXISTS conversation_id UUID,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMP,
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMP,
    ADD COLUMN IF NOT EXISTS observed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS salience DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(50) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS source_memory_id UUID,
    ADD COLUMN IF NOT EXISTS source_event_id UUID,
    ADD COLUMN IF NOT EXISTS schema_version BIGINT NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_memory_relation_tenant_user_source
    ON memory_relation(tenant_id, user_id, source_id);
CREATE INDEX IF NOT EXISTS idx_memory_relation_tenant_user_target
    ON memory_relation(tenant_id, user_id, target_id);
CREATE INDEX IF NOT EXISTS idx_memory_relation_tenant_type
    ON memory_relation(tenant_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_memory_relation_validity
    ON memory_relation(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_memory_relation_source_event
    ON memory_relation(source_event_id);

-- Defense in depth. Runtime queries must still include tenant/user predicates.
ALTER TABLE memory_entity ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_relation ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_episode ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_fact ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_entity_tenant_isolation ON memory_entity;
CREATE POLICY memory_entity_tenant_isolation ON memory_entity
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS memory_relation_tenant_isolation ON memory_relation;
CREATE POLICY memory_relation_tenant_isolation ON memory_relation
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS memory_episode_tenant_isolation ON memory_episode;
CREATE POLICY memory_episode_tenant_isolation ON memory_episode
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS profile_fact_tenant_isolation ON profile_fact;
CREATE POLICY profile_fact_tenant_isolation ON profile_fact
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE memory_entity IS
    'Canonical tenant/user-scoped entity identity records used by rebuildable memory graph projections.';
COMMENT ON TABLE memory_relation IS
    'Rebuildable temporal/associative relation projection over canonical governed memory records.';
