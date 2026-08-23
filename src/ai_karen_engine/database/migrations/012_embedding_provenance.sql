-- Migration: 012_embedding_provenance.sql
-- Description: Add embedding provenance tracking to memory_items.
-- Columns: embedding_model, embedding_version, embedding_dimension, embedded_at

-- ============================================================================
-- 1. Add embedding provenance columns
-- ============================================================================
ALTER TABLE memory_items
    ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255),
    ADD COLUMN IF NOT EXISTS embedding_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP;

-- ============================================================================
-- 2. Backfill existing rows with safe defaults
-- ============================================================================
UPDATE memory_items
SET
    embedding_model = COALESCE(metadata->>'embedding_model', 'unknown'),
    embedding_version = COALESCE(metadata->>'embedding_version', 'v1'),
    embedding_dimension = COALESCE((metadata->>'embedding_dimension')::INTEGER, 384),
    embedded_at = COALESCE(created_at, NOW())
WHERE embedding_model IS NULL;

-- ============================================================================
-- 3. Create index for model/version queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_provenance
    ON memory_items (embedding_model, embedding_version, tenant_id);
