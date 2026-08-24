-- Migrated from database/migrations/007_memory_ledger.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 007_memory_ledger.sql
-- Description: Create canonical tables for memory event ledger and projection metadata.

-- memory_event
CREATE TABLE IF NOT EXISTS memory_event (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    source_type VARCHAR(100) NOT NULL,
    source_ref VARCHAR(255),
    payload_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(255),
    confidence DOUBLE PRECISION DEFAULT 1.0,
    scope VARCHAR(100) DEFAULT 'user',
    sensitivity_class VARCHAR(50) DEFAULT 'normal',
    consent_state VARCHAR(50) DEFAULT 'granted',
    valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_to TIMESTAMP,
    supersedes UUID,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_event_user_tenant ON memory_event(user_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_event_created ON memory_event(created_at);
ALTER TABLE memory_event ADD CONSTRAINT uq_memory_event_idempotency UNIQUE (idempotency_key);

-- memory_assertion
CREATE TABLE IF NOT EXISTS memory_assertion (
    assertion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    content TEXT NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 1.0,
    scope VARCHAR(100) DEFAULT 'user',
    sensitivity_class VARCHAR(50) DEFAULT 'normal',
    consent_state VARCHAR(50) DEFAULT 'granted',
    valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_to TIMESTAMP,
    supersedes UUID,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_assertion_user_tenant ON memory_assertion(user_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_assertion_validity ON memory_assertion(valid_from, valid_to);

-- memory_episode
CREATE TABLE IF NOT EXISTS memory_episode (
    episode_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    session_id VARCHAR(255),
    summary TEXT NOT NULL,
    snapshot_data JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_episode_user_tenant ON memory_episode(user_id, tenant_id);

-- profile_fact
CREATE TABLE IF NOT EXISTS profile_fact (
    fact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    category VARCHAR(100) NOT NULL,
    attribute VARCHAR(255) NOT NULL,
    value JSONB NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 1.0,
    source_type VARCHAR(100) NOT NULL,
    source_ref VARCHAR(255),
    valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_to TIMESTAMP,
    supersedes UUID,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profile_fact_user_category ON profile_fact(user_id, category);

-- memory_relation
CREATE TABLE IF NOT EXISTS memory_relation (
    relation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    target_id UUID NOT NULL,
    relation_type VARCHAR(100) NOT NULL,
    metadata_payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_relation_source ON memory_relation(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_relation_target ON memory_relation(target_id);

-- reinforcement_event
CREATE TABLE IF NOT EXISTS reinforcement_event (
    reinforcement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    target_assertion_id UUID NOT NULL,
    weight DOUBLE PRECISION DEFAULT 0.1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- contradiction_event
CREATE TABLE IF NOT EXISTS contradiction_event (
    contradiction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    source_assertion_id UUID NOT NULL,
    target_assertion_id UUID NOT NULL,
    resolution_status VARCHAR(50) DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

-- projection_status
CREATE TABLE IF NOT EXISTS projection_status (
    projection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES memory_event(event_id) ON DELETE CASCADE,
    target_store VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    retry_count BIGINT DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_status_event_store ON projection_status(event_id, target_store);
CREATE INDEX IF NOT EXISTS idx_projection_status_status ON projection_status(status);

-- consent_scope
CREATE TABLE IF NOT EXISTS consent_scope (
    scope_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    scope_name VARCHAR(100) NOT NULL,
    is_granted BOOLEAN DEFAULT TRUE,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);

-- retention_policy
CREATE TABLE IF NOT EXISTS retention_policy (
    policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID,
    memory_class VARCHAR(50) NOT NULL,
    ttl_days BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
