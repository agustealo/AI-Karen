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
