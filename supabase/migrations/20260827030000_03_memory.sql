-- AI KAREN production baseline migration
-- Consolidated pre-production history. Future production changes are forward-only.
-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.


-- ============================================================================
-- BASELINE SOURCE: 20260823060000_memory_ledger.sql
-- ============================================================================

﻿-- Migrated from database/migrations/007_memory_ledger.sql (preserving original lineage)
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

-- ============================================================================
-- BASELINE SOURCE: 20260823070000_memory_convergence.sql
-- ============================================================================

﻿-- Migrated from database/migrations/008_memory_convergence.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 008_memory_convergence.sql
-- Description: Converge memory persistence onto PostgreSQL with pgvector and FTS.
-- Retires Milvus/Elasticsearch projections for memory_items.

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add canonical columns to memory_items for tenant/user scoping and lifecycle
ALTER TABLE memory_items
    ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS user_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS conversation_id UUID,
    ADD COLUMN IF NOT EXISTS content_tsv TEXT GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    ADD COLUMN IF NOT EXISTS importance FLOAT DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(100) DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS source_ref VARCHAR(255),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;

-- Convert legacy ARRAY(Float) embedding to pgvector when dimensions match
ALTER TABLE memory_items
    ADD COLUMN IF NOT EXISTS embedding_vector vector;

UPDATE memory_items
SET embedding_vector = embedding::vector
WHERE embedding IS NOT NULL
  AND array_length(embedding, 1) IS NOT NULL
  AND embedding_vector IS NULL;

-- Drop legacy embedding column after backfill verification
-- ALTER TABLE memory_items DROP COLUMN embedding;

-- Backfill tenant_id/user_id from metadata when not yet set
UPDATE memory_items
SET tenant_id = COALESCE((metadata->>'tenant_id')::uuid, gen_random_uuid()),
    user_id = COALESCE((metadata->>'user_id')::uuid, gen_random_uuid())
WHERE tenant_id = gen_random_uuid();

-- Indexes for tenant-scoped access
CREATE INDEX IF NOT EXISTS idx_memory_items_tenant_user
    ON memory_items(tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_items_scope_kind
    ON memory_items(scope, kind);

-- pgvector HNSW index for semantic search
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_vector
    ON memory_items
    USING hnsw (embedding_vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- PostgreSQL FTS index over content
CREATE INDEX IF NOT EXISTS idx_memory_items_content_tsv
    ON memory_items USING GIN (content_tsv);
